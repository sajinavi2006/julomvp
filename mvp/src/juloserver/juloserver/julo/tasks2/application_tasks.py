import json
import logging
from celery import task
from django.utils import timezone
from datetime import timedelta, datetime

from juloserver.julo.models import Application, Loan
from juloserver.julo.models import AppVersion
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import CreditMatrixProductLine
from juloserver.account.models import (
    CreditLimitGeneration,
    AccountLimit
)
from juloserver.julo.constants import WorkflowConst
from juloserver.entry_limit.constants import CreditLimitGenerationReason
from juloserver.application_flow.models import EmulatorCheck

logger = logging.getLogger(__name__)


@task(queue='application_normal')
def bucket_150_auto_expiration():
    from juloserver.julo.services import process_application_status_change

    applications = Application.objects.filter(
        product_line__in=[ProductLineCodes.MTL1,
                          ProductLineCodes.MTL2,
                          ProductLineCodes.STL1,
                          ProductLineCodes.STL2],
        application_status=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
    )

    if not applications:
        logger.info({
            'action': 'bucket_150_auto_expiration',
            'status': 'no applications found'
        })

    for application in applications:
        new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
        note = 'Automated bank name validation expired please validate manually'
        reason = 'Name validation failed'
        process_application_status_change(application.id,
                                          new_status_code,
                                          reason,
                                          note)
        logger.info({
            'action': 'bucket_150_auto_expiration',
            'status': 'application status changed',
            'application_id': application.id
        })


@task(queue='application_high')
def send_deprecated_apps_push_notif(application_id, app_version):
    version = AppVersion.objects.filter(app_version=app_version).last()

    if not app_version or version and version.status not in ['deprecated', 'not_supported']:
        return

    pn_client = get_julo_pn_client()
    pn_client.send_pn_depracated_app(application_id)


@task(name='update_limit_for_good_customers')
def update_limit_for_good_customers(
        application_id,
        old_limit_adjustment_factor,
        new_limit_adjustment_factor
):
    from juloserver.account.services.credit_limit import (
        calculate_credit_limit,
        store_credit_limit_generated,
        get_credit_matrix_parameters,
        get_transaction_type,
        get_credit_matrix
    )
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return

    old_credit_limit_generation = CreditLimitGeneration.objects.filter(
        application=application).last()

    if old_limit_adjustment_factor:
        if '"limit_adjustment_factor": {}'.format(old_limit_adjustment_factor) not \
                in old_credit_limit_generation.log:
            return

    if not old_credit_limit_generation:
        return

    credit_limit_generation = old_credit_limit_generation
    custom_matrix_parameters = get_credit_matrix_parameters(application)
    if not custom_matrix_parameters:
        return
    transaction_type = get_transaction_type()
    credit_matrix = get_credit_matrix(custom_matrix_parameters, transaction_type)

    affordability_history = credit_limit_generation.affordability_history
    affordability_value = affordability_history.affordability_value

    credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
        credit_matrix=credit_matrix
    ).last()
    credit_limit_result = calculate_credit_limit(
        credit_matrix_product_line,
        affordability_value,
        new_limit_adjustment_factor
    )

    log_data = {
        'simple_limit': credit_limit_result['simple_limit'],
        'reduced_limit': credit_limit_result['reduced_limit'],
        'limit_adjustment_factor': credit_limit_result['limit_adjustment_factor'],
        'max_limit (pre-matrix)': credit_limit_result['simple_limit_rounded'],
        'set_limit (pre-matrix)': credit_limit_result['reduced_limit_rounded'],
    }
    reason = CreditLimitGenerationReason.UPDATE_ADJUSTMENT_FACTOR

    new_max_limit = credit_limit_result['max_limit']
    new_set_limit = credit_limit_result['set_limit']

    account = application.account
    if not account:
        return
    account_limit = AccountLimit.objects.filter(account=account).last()

    if new_set_limit <= account_limit.set_limit and new_max_limit <= account_limit.max_limit:
        logger.info({
            "action": "update_limit_adjustment_not_updated",
            "application": application_id
        })
        return

    logger.info({
        "action": "update_limit_adjustment_updated",
        "application": application_id
    })

    store_credit_limit_generated(
        application,
        account,
        credit_matrix,
        affordability_history,
        new_max_limit,
        new_set_limit,
        json.dumps(log_data),
        reason
    )

    available_limit = new_set_limit - account_limit.used_limit
    account_limit.update_safely(
        max_limit=new_max_limit,
        set_limit=new_set_limit,
        available_limit=available_limit
    )


@task(name='update_is_5_days_unreachable')
def update_is_5_days_unreachable():
    from juloserver.julo.services import (get_oldest_unpaid_account_payment_ids_within_dpd,
                                          get_oldest_unpaid_payment_within_dpd
                                          )
    # TODO
    today = timezone.localtime(timezone.now())
    range1_ago = today - timedelta(days=1)
    range2_ago = today - timedelta(days=90)

    # non julo1 payments
    payment_ids = get_oldest_unpaid_payment_within_dpd(range1_ago, range2_ago)
    for payment_id in payment_ids:
        update_is_5_days_unreachable_subtask.delay(payment_id, is_account_payment=False, is_real_time=False)

    # julo1 account payments
    account_payment_ids = get_oldest_unpaid_account_payment_ids_within_dpd(range1_ago, range2_ago)
    for payment_id in account_payment_ids:
        update_is_5_days_unreachable_subtask.delay(payment_id, is_account_payment=True, is_real_time=False)


@task(name='update_is_5_days_unreachable_subtask')
def update_is_5_days_unreachable_subtask(payment_id, is_account_payment=False, is_real_time=False):
    from juloserver.julo.services import update_flag_is_5_days_unreachable_and_sendemail

    payment_or_account_payment = update_flag_is_5_days_unreachable_and_sendemail(payment_id, is_account_payment,
                                                                                 is_real_time)
    logger.info({
        'action': 'update_is_5_days_unreachable_subtask',
        'payment_or_account_payment': payment_or_account_payment,
        'is_real_time': is_real_time,
        'is_account_payment': is_account_payment
    })


@task(queue='application_normal')
def high_score_131_or_132_move_to_124_or_130():
    from juloserver.julo.services2.high_score import feature_high_score_full_bypass
    resubmitted_statuses = [
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED
    ]
    new_status_code = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
    message = 'high_score_full_bypass'
    applications = Application.objects.filter(application_status__in=resubmitted_statuses,
                                              workflow__name=WorkflowConst.JULO_ONE)
    for app in applications:
        high_score = feature_high_score_full_bypass(app)
        if high_score:
            high_score_131_or_132_move_to_124_or_130_subtask.delay(app.id, new_status_code, message)


@task(name='high_score_131_or_132_move_to_124_or_130_subtask')
def high_score_131_or_132_move_to_124_or_130_subtask(application_id, new_status_code, message):
    from juloserver.julo.services import process_application_status_change
    application = Application.objects.get_or_none(id=application_id)

    if application is None:
        return

    process_application_status_change(
        application.id,
        new_status_code,
        message
    )

    if application.name_bank_validation is not None:
        if application.name_bank_validation.validation_status == 'SUCCESS':
            message = 'high_score_full_bypass'
            new_status_code = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
            process_application_status_change(
                application.id,
                new_status_code,
                message
            )


@task(queue='application_normal')
def expired_application_emulator_check():
    from juloserver.julo.services import process_application_status_change
    from juloserver.account.services.account_related import process_change_account_status
    current_status_id = [120, 121, 122, 124, 125, 131, 132, 138, 140, 141, 142, 145, 175]
    final_status_id = [190]
    status_id = current_status_id + final_status_id
    application_ids = Application.objects.filter(application_status_id__in=status_id,
                                                 workflow_id=7, product_line_id=1).values_list('id', flat=True)
    ecs = EmulatorCheck.objects.filter(application_id__in=application_ids,
                                       cts_profile_match=False, basic_integrity=False, error_msg__isnull=True)

    for ec in ecs:
        application = ec.application

        if application.application_status_id in current_status_id:
            process_application_status_change(application.id,
                                              135,
                                              'emulator_detected')

        elif application.application_status_id in final_status_id:
            last_loan = Loan.objects.filter(application_id2=application.id).last()
            if not last_loan and application.account:
                process_change_account_status(application.account,
                                              432,
                                              change_reason='emulator_detected_by_script')
