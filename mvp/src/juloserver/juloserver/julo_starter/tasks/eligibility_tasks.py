from celery import task

from django.conf import settings

from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    FDCInquiry,
    FeatureSetting,
    Device,
    Customer,
    OnboardingEligibilityChecking,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.julo_starter.services.credit_limit import check_is_good_score
from juloserver.julo_starter.exceptions import PDCreditModelNotFound, SettingNotFound
from juloserver.julo_starter.constants import (
    NotificationSetJStarter,
)
from juloserver.julo_starter.services.submission_process import (
    process_fraud_check,
    binary_check_result,
)
from juloserver.julo_starter.tasks.app_tasks import (
    trigger_push_notif_check_scoring,
    trigger_pn_emulator_detection,
)
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.models import ApplicationNote
from juloserver.fraud_security.binary_check import process_fraud_binary_check
from juloserver.application_flow.services import (
    send_application_event_by_certain_pgood,
    eligible_to_offline_activation_flow,
    send_application_event_base_on_mycroft,
)
from juloserver.application_flow.constants import ApplicationStatusEventType

juloLogger = JuloLog(__name__)


@task(queue='application_high')
def run_eligibility_check(
    fdc_inquiry_data,
    reason,
    retry_count=0,
    retry=False,
    is_fdc_eligible=True,
    customer_id=None,
    application_id=None,
    is_send_pn=True,
    process_change_application_status=False,
    onboarding_id=None,
):
    from juloserver.julo_starter.services.onboarding_check import (
        process_eligibility_check,
        process_application_eligibility_check_for_jturbo_j360,
    )

    on_check = None
    try:
        on_check = process_eligibility_check(
            fdc_inquiry_data,
            reason,
            retry,
            is_fdc_eligible,
            customer_id,
            application_id,
            onboarding_id,
        )

        if not is_fdc_eligible:
            return

        # No need to detokenize fdc inquiry here,
        # because is only check the existence and use `customer_id`.
        # Do more detokenization if used PII attribute!
        fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])

        if not fdc_inquiry:
            return

        # No need to detokenize customer here,
        # because is only the `id`.
        # Do more detokenization if used PII attribute!
        customer = Customer.objects.get(id=fdc_inquiry.customer_id)

    except FDCServerUnavailableException:
        juloLogger.error(
            {
                "action": "run_eligibility_check",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
            }
        )

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        juloLogger.info(
            {
                "action": "run_eligibility_check",
                "message": "retry fdc request with error: %(e)s" % {'e': e},
            }
        )
    else:
        if is_send_pn:
            trigger_eligibility_check_pn_subtask.delay(customer.id)
        if process_change_application_status:
            process_application_eligibility_check_for_jturbo_j360(application_id, on_check)

        return

    # variable reason equal to 1 is for FDCx100
    if reason != 1:
        return

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY, category="fdc", is_active=True
    ).first()

    if not on_check:
        on_check = OnboardingEligibilityChecking.objects.filter(customer_id=customer_id).last()

    if not fdc_retry_feature:
        juloLogger.info(
            {"action": "run_eligibility_check", "error": "fdc_retry_feature is not active"}
        )
        if on_check:
            on_check.update_safely(fdc_inquiry_id=fdc_inquiry_data['id'])
        return

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:
        raise JuloException(
            "Parameter retry_interval_minutes: "
            "%(retry_interval_minutes)s can not be zero value "
            % {'retry_interval_minutes': retry_interval_minutes}
        )
    if not isinstance(retry_interval_minutes, int):
        raise JuloException("Parameter retry_interval_minutes should integer")

    if not isinstance(max_retries, int):
        raise JuloException("Parameter max_retries should integer")
    if max_retries <= 0:
        raise JuloException("Parameter max_retries should greater than zero")

    countdown_seconds = retry_interval_minutes * 60

    if retry_count > max_retries:
        juloLogger.info(
            {
                "action": "run_eligibility_check",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
            }
        )
        if on_check:
            on_check.update_safely(fdc_inquiry_id=fdc_inquiry_data['id'])

        return

    retry_count += 1

    juloLogger.info(
        {
            'action': 'run_fdc_for_failure_status',
            'retry_count': retry_count,
            'count_down': countdown_seconds,
        }
    )

    run_eligibility_check.apply_async(
        (
            fdc_inquiry_data,
            reason,
            retry_count,
            retry,
            is_fdc_eligible,
            customer_id,
            application_id,
            is_send_pn,
        ),
        countdown=countdown_seconds,
    )


@task(queue='application_normal')
def handle_julo_starter_generated_credit_model(application_id):
    """
    From card: https://juloprojects.atlassian.net/browse/RUS1-2849
    Function modified from previously include: bpjs, pgood, heimdall, and binary
    To only include: binary and heimdall check score

    BPJS check and pgood is moved after emulator check
    """
    from juloserver.julo_starter.services.services import (
        process_offer_to_j1,
        has_good_score_mycroft_turbo,
    )

    juloLogger.info(
        {
            "msg": "Function call -> handle_julo_starter_generated_credit_model",
            "application_id": application_id,
        }
    )

    # No need to detokenize application here,
    # because is only check the existence, relationships, and use `status`, `id`.
    # Also passed to several functions as object.
    # Do more detokenization if used PII attribute!
    application = Application.objects.get_or_none(pk=application_id)

    if application is None:
        juloLogger.warning(
            {
                "msg": "handle_julo_starter_income_check, application not found",
                "application_id": application_id,
            }
        )
        return

    if (
        application.status != ApplicationStatusCodes.FORM_PARTIAL
        or application.workflow.name != WorkflowConst.JULO_STARTER
    ):
        return

    is_fraud = process_fraud_check(application)
    if is_fraud:
        juloLogger.warning(
            {
                "msg": "handle_julo_starter_income_check, fraud check found",
                "application_id": application_id,
            }
        )
        return

    # BINARY CHECK
    binary_result = binary_check_result(application)
    offline_activation_flow = eligible_to_offline_activation_flow(application)

    offer_regular = False
    offer_regular_reason = ''
    if not binary_result and not offline_activation_flow:
        juloLogger.info(
            {
                "msg": "handle_julo_starter_income_check, failed binary check",
                "application_id": application_id,
            }
        )
        process_application_status_change(
            application,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='binary_check_failed',
        )
        trigger_push_notif_check_scoring.delay(
            application.id, NotificationSetJStarter.KEY_MESSAGE_REJECTED
        )
        return 'success'
    else:
        # By default, if the check is failed the application status is moved to x133 and
        # in turn moved to x190 LOC reject.
        is_pass_fraud_check, fail_fraud_check_handler = process_fraud_binary_check(
            application, 'handle_julo_starter_generated_credit_model'
        )
        if not is_pass_fraud_check:
            juloLogger.info(
                {
                    'action': 'handle_julo_starter_generated_credit_model',
                    'message': 'application failed fraud check',
                    'application': application_id,
                    'handler': fail_fraud_check_handler.__class__.__name__,
                }
            )
            process_application_status_change(
                application_id=application_id,
                new_status_code=fail_fraud_check_handler.fail_status_code,
                change_reason=fail_fraud_check_handler.fail_change_reason,
            )
            return

        # send GA event for certain pgood
        send_application_event_by_certain_pgood(
            application,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusEventType.APPSFLYER_AND_GA,
        )
        send_application_event_base_on_mycroft(
            application,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusEventType.APPSFLYER_AND_GA,
        )

        # Checking for new flow if bpjs_check is 3.
        # No need to detokenize customer here,
        # because is only pass to another function as object, and use `id`.
        # Do more detokenization if used PII attribute!
        customer = application.customer

        # WARNING: override section
        from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists

        is_target_whitelist = is_email_for_whitelists(customer)
        if is_target_whitelist:
            # record to application notes
            ApplicationNote.objects.create(
                note_text="whitelist email for JTurbo to bypass check",
                application_id=application.id,
                application_history_id=None,
            )

            juloLogger.info(
                {
                    'message': '[eligibility_check_task] override result for email whitelist',
                    'override_to': 'no_fraud',
                    'customer': customer.id if customer else None,
                }
            )
            # call task notif emulator
            trigger_pn_emulator_detection.delay(application.id)

            return 'success'

        # HEIMDALL CHECK
        try:
            is_good_score = check_is_good_score(application=application)
        except (SettingNotFound, PDCreditModelNotFound):
            # mocking process testing purpose
            heimdall_passing_testing = FeatureSetting.objects.get_or_none(
                feature_name='heimdall_testing_purpose_only', is_active=True
            )
            # bypass heimdal for testing env only
            if heimdall_passing_testing and settings.ENVIRONMENT != 'prod':
                is_good_score = True
            else:
                return

        if not is_good_score:
            juloLogger.info(
                {
                    "msg": "Julo starter threshold failed",
                    "application_id": application.id,
                }
            )
            offer_regular = True
            offer_regular_reason = 'sphinx_threshold_failed'

        pass_mycroft = has_good_score_mycroft_turbo(application)
        if not pass_mycroft:
            juloLogger.warning(
                {
                    "msg": "handle_julo_starter_income_check, reject mycroft",
                    "application_id": application_id,
                }
            )
            offer_regular = True
            offer_regular_reason = 'failed_mycroft'

        # MOVE TO 107
        if offer_regular:
            # moving application to x107 and trigger_push_notif_check_scoring
            process_offer_to_j1(application, offer_regular_reason)

    # call task notif emulator
    trigger_pn_emulator_detection.delay(application.id)

    return 'success'


def process_offer_to_j1(application, offer_regular_reason):
    juloLogger.info(
        {
            'message': 'Moving application to {}'.format(ApplicationStatusCodes.OFFER_REGULAR),
            'application': application.id,
            'change_reason': offer_regular_reason,
        }
    )

    process_application_status_change(
        application.id,
        ApplicationStatusCodes.OFFER_REGULAR,
        change_reason=offer_regular_reason,
    )

    template_code_for_notif = NotificationSetJStarter.KEY_MESSAGE_OFFER

    # Call task notif to customer
    trigger_push_notif_check_scoring.delay(application.id, template_code_for_notif)


@task(queue='application_normal')
def trigger_eligibility_check_pn_subtask(customer_id):
    from juloserver.julo.utils import have_pn_device
    from juloserver.julo_starter.services.onboarding_check import check_process_eligible

    device = Device.objects.filter(customer_id=customer_id).last()
    eligibility = check_process_eligible(customer_id)
    if (
        not eligibility['is_eligible']
        or not have_pn_device(device)
        or eligibility['process_eligibility_checking'] != 'finished'
    ):
        return

    template_code = None
    if eligibility['is_eligible'] == 'passed':
        template_code = 'pn_eligibility_ok'
    elif eligibility['is_eligible'] == 'offer_regular':
        template_code = 'pn_eligibility_j1_offer'
    elif eligibility['is_eligible'] == 'not_passed':
        template_code = 'pn_eligbility_rejected'

    juloLogger.info(
        {
            'action': 'JULO Starter Eligibility Notification',
            'customer_id': customer_id,
            'template_code': template_code,
        }
    )

    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_julo_starter_eligibility(device.gcm_reg_id, template_code)
