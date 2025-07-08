import logging
from datetime import timedelta
from operator import itemgetter

from celery import task
from dateutil.relativedelta import relativedelta
from django.db.models import Case, Count, IntegerField, When, Q
from django.utils import timezone

from juloserver.account.constants import (
    AccountConstant,
    AccountChangeReason,
)
from juloserver.account.models import (
    Account,
    AccountStatusHistory,
)
from juloserver.account.services.account_related import (
    process_change_account_status,
    do_update_user_timezone,
    is_account_permanent_risk_block,
    trigger_send_email_suspension,
    trigger_send_email_reactivation,
)
from juloserver.account_payment.models import AccountPaymentStatusHistory, AccountPayment
from juloserver.account_payment.utils import get_account_payment_status_based_on_dpd
from juloserver.customer_module.services.customer_related import (
    update_cashback_balance_status,
)
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import FeatureSetting, CashbackCounterHistory, Device
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_selloff.models import LoanSelloffBatch
from juloserver.loan_selloff.services import process_account_selloff_j1
from juloserver.account_payment.services.earning_cashback import (
    get_due_date_for_cashback_new_scheme,
)
from juloserver.julo.clients import (
    get_julo_pn_client,
)
from juloserver.julo.utils import (
    have_pn_device,
)

logger = logging.getLogger(__name__)


@task(queue='collection_normal')
def process_account_reactivation(
    account_id, previous_account_status_code=None, is_from_scheduler=False
):
    logger.info(
        {
            'action': 'process_account_reactivation',
            'account_id': account_id,
            'message': 'task begin',
        }
    )
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ACCOUNT_REACTIVATION_SETTING, is_active=True
    ).last()
    if not feature_setting:
        logger.error(
            {
                'action': 'process_account_reactivation',
                'data': {'account_id': account_id},
                'response': 'the feature setting is not found or not activate',
            }
        )
        return

    parameters = feature_setting.parameters

    account = Account.objects.get(pk=account_id)
    account_status = (
        account.status_id if not previous_account_status_code else previous_account_status_code
    )
    if account_status not in (
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.suspended,
    ):
        return

    application = account.last_application
    if (
        application.is_eligible_for_collection()
        and account_status == AccountConstant.STATUS_CODE.suspended
    ):
        if AccountStatusHistory.objects.filter(
            account_id=account_id, change_reason=AccountChangeReason.EXCEED_DPD_THRESHOLD
        ).exists():
            logger.info(
                {
                    'action': 'process_account_reactivation',
                    'account_id': account_id,
                    'message': 'account already blocked permanently',
                }
            )
            return

        # account id from scheduler task is account id with dpd zero or less
        # because there's query to filter out if have loan status in range (220 - 250)
        # so no need to check is late or not
        if not is_from_scheduler:
            # validation is account need to permanent block or not
            if is_account_permanent_risk_block(account=account):
                logger.info(
                    {
                        'action': 'process_account_reactivation',
                        'account_id': account_id,
                        'message': 'block permanently due to exceed dpd threshold',
                    }
                )
                process_change_account_status(
                    account,
                    AccountConstant.STATUS_CODE.suspended,  # waiting decision from other squad
                    AccountChangeReason.EXCEED_DPD_THRESHOLD,
                )
                update_cashback_balance_status(account.customer, True)
                trigger_send_email_suspension(account)
                return

    period_day = parameters.get('special_criteria', {}).get('day', 90)

    post_cool_off_threshold = timezone.localtime(timezone.now()).date() - timedelta(days=period_day)
    activated_refinancing = (
        LoanRefinancingRequest.objects.filter(
            status=CovidRefinancingConst.STATUSES.activated,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            offer_activated_ts__date__gte=post_cool_off_threshold,
            account__status_id__in=AccountConstant.REACTIVATION_ACCOUNT_STATUS,
            account=account,
        )
        .exclude(
            waiverrequest__program_name=CovidRefinancingConst.PRODUCTS.gpw,
        )
        .distinct('account')
        .order_by('account', '-cdate')
        .exists()
    )
    if activated_refinancing:
        logger.error(
            {
                'action': 'process_account_reactivation',
                'data': {'account_id': account_id},
                'response': "can't reactivate account because have activated refinancing",
            }
        )
        return

    not_allowed_loan_status = account.loan_set.filter(
        Q(loan_status_id__gt=LoanStatusCodes.CURRENT)
        | Q(loan_status_id=LoanStatusCodes.CURRENT, is_restructured=True)
    ).exclude(loan_status_id=LoanStatusCodes.PAID_OFF)
    if not_allowed_loan_status:
        logger.error(
            {
                'action': 'process_account_reactivation',
                'data': {
                    'account_id': account_id,
                    'loan_ids_not_current': not_allowed_loan_status.values_list('id', flat=True),
                },
                'response': "can't reactivate account because loan status is not current",
            }
        )
        return

    if application.workflow.name in (WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER):
        last_activated_refinancing = (
            LoanRefinancingRequest.objects.filter(
                status=CovidRefinancingConst.STATUSES.activated,
                account__status_id__in=AccountConstant.REACTIVATION_ACCOUNT_STATUS,
                account=account,
            )
            .exclude(
                waiverrequest__program_name=CovidRefinancingConst.PRODUCTS.gpw,
            )
            .last()
        )
        account_payments_filter = Q(status_id__in=PaymentStatusCodes.payment_late())
        if last_activated_refinancing:
            refinancing_activated_ts = (
                last_activated_refinancing.offer_activated_ts
                or last_activated_refinancing.form_submitted_ts
                or last_activated_refinancing.cdate
            )
            account_payments_filter = account_payments_filter | Q(
                status_id__in=PaymentStatusCodes.payment_not_late(),
                cdate__lte=refinancing_activated_ts,
            )
        blocked_account_payments = account.accountpayment_set.normal().filter(
            account_payments_filter
        )
        if blocked_account_payments:
            logger.error(
                {
                    'action': 'process_account_reactivation',
                    'data': {
                        'account_id': account_id,
                        'blocked_account_payments': blocked_account_payments.values_list(
                            'id', flat=True
                        ),
                    },
                    'response': "can't reactivate account because of blocked payment",
                }
            )
            return

    today = timezone.localtime(timezone.now())
    first_criteria = parameters['criteria_1']
    second_criteria = parameters['criteria_2']
    max_month_criteria_1 = max(first_criteria, key=itemgetter('month'))['month']
    max_account_payment_cdate_date = today - relativedelta(
        months=max(second_criteria['month'], max_month_criteria_1)
    )
    account_payment_ids = (
        account.accountpayment_set.filter(due_date__gte=max_account_payment_cdate_date)
        .filter(
            Q(status_id__gte=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD) | Q(is_restructured=True)
        )
        .values_list('id', flat=True)
    )
    for criteria in first_criteria:
        x_month = today - relativedelta(months=criteria['month'])
        criteria_dpd = get_account_payment_status_based_on_dpd(criteria['dpd'])
        account_payment_history = AccountPaymentStatusHistory.objects.filter(
            cdate__date__range=[x_month.date(), today.date()],
            status_new_id__gte=criteria_dpd,
            status_new_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            account_payment_id__in=account_payment_ids,
        )
        if account_payment_history:
            # do nothing because dpd on x month gt dpd criteria
            logger.error(
                {
                    'action': 'process_account_reactivation',
                    'data': {
                        'account_id': account_id,
                        'criteria_dpd': criteria['dpd'],
                        'criteria_month': criteria['month'],
                    },
                    'response': "can't reactivate account because of first criteria is not met",
                }
            )
            return

    second_criteria_month = today - relativedelta(months=second_criteria['month'])
    second_criteria_dpd = get_account_payment_status_based_on_dpd(second_criteria['dpd_gte'])
    second_criteria_account_payment_history = (
        AccountPaymentStatusHistory.objects.filter(
            cdate__date__range=[second_criteria_month.date(), today.date()],
            status_new_id__gte=second_criteria_dpd,
            status_new_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            account_payment_id__in=account_payment_ids,
        )
        .values("account_payment_id")
        .annotate(total=Count("account_payment_id"))
        .count()
    )
    if second_criteria_account_payment_history > second_criteria['max_account']:
        # do nothing because dpd on x month gt dpd criteria
        logger.error(
            {
                'action': 'process_account_reactivation',
                'data': {
                    'account_id': account_id,
                    'second_criteria_count': second_criteria_account_payment_history,
                },
                'response': "can't reactivate account because of second criteria is not met",
            }
        )
        return

    process_change_account_status(
        account, AccountConstant.STATUS_CODE.active, 'revert account status back to 420'
    )
    update_cashback_balance_status(account.customer, False)
    if application.is_eligible_for_collection():
        trigger_send_email_reactivation(account_id)
        send_pn_reactivation_success.delay(account.customer.id)
    logger.info(
        {
            'action': 'process_account_reactivation',
            'account_id': account_id,
            'message': 'task finish',
        }
    )


@task(queue='collection_normal')
def scheduled_reactivation_account():
    fs = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.ACCOUNT_REACTIVATION_SETTING,
        is_active=True,
    )
    params = fs.parameters
    period_day = params.get('special_criteria', {}).get('day', 90)

    post_cool_off_threshold = timezone.localtime(timezone.now()).date() - timedelta(days=period_day)
    activated_refinancing_account_ids = (
        LoanRefinancingRequest.objects.filter(
            status=CovidRefinancingConst.STATUSES.activated,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            offer_activated_ts__date__gte=post_cool_off_threshold,
            account__status_id=AccountConstant.STATUS_CODE.suspended,
        )
        .distinct('account')
        .order_by('account', '-cdate')
        .values_list('account_id', flat=True)
    )

    account_ids = (
        Account.objects.exclude(
            loan__loan_status__in=(LoanStatusCodes.RENEGOTIATED, LoanStatusCodes.HALT)
        )
        .exclude(application__product_line_id=ProductLineCodes.JULOVER)
        .filter(
            status_id__in=AccountConstant.REACTIVATION_ACCOUNT_STATUS,
            loan__loan_status__gte=LoanStatusCodes.CURRENT,
        )
        .annotate(
            count_due_status=Count(
                Case(
                    When(
                        loan__loan_status__gt=LoanStatusCodes.CURRENT,
                        loan__loan_status__lt=LoanStatusCodes.PAID_OFF,
                        then=1,
                    ),
                    output_field=IntegerField(),
                )
            )
        )
        .filter(count_due_status=0)
        .exclude(id__in=list(activated_refinancing_account_ids))
        .values_list("id", flat=True)
        .distinct()
    )

    for account_id in account_ids:
        process_account_reactivation.delay(account_id, is_from_scheduler=True)


@task(queue='collection_high')
def process_execute_account_selloff():
    '''
    this task will running every 00 AM for trigger loan_selloff
    '''
    fn_name = 'process_execute_account_selloff'
    current_time = timezone.localtime(timezone.now())
    logger.info({'action': fn_name, 'state': "start", 'time': current_time})
    eod_time = current_time.replace(hour=23, minute=59, second=59)
    loan_selloff_batch_data = LoanSelloffBatch.objects.filter(
        execution_schedule__gte=current_time, execution_schedule__lte=eod_time
    )
    if not loan_selloff_batch_data:
        logger.info(
            {
                'action': fn_name,
                'state': "failed",
                'message': "Dont have any data loan_selloff_batch to execute",
            }
        )
        return

    logger.info(
        {
            'action': fn_name,
            'state': "processing",
        }
    )
    for loan_selloff_batch in loan_selloff_batch_data:
        process_execute_account_selloff_sub_task.apply_async(
            (loan_selloff_batch.id,),
            eta=timezone.localtime(loan_selloff_batch.execution_schedule),
        )

    logger.info(
        {
            'action': fn_name,
            'state': "finish",
        }
    )


@task(queue='collection_high')
def process_execute_account_selloff_sub_task(loan_selloff_batch_id: int):
    fn_name = 'process_execute_account_selloff_sub_task'
    identifier = "loan_selloff_batch_{}".format(loan_selloff_batch_id)
    current_time = timezone.localtime(timezone.now())
    logger.info(
        {'action': fn_name, 'state': "start", 'time': current_time, 'identifier': identifier}
    )
    loan_selloff_batch = LoanSelloffBatch.objects.get(pk=loan_selloff_batch_id)
    if not loan_selloff_batch:
        logger.info(
            {
                'action': fn_name,
                'state': "failed",
                'identifier': identifier,
                'message': "cannot found data on loan selloff batch",
            }
        )
        return

    account_selloff_data = (
        loan_selloff_batch.loanselloff_set.filter(account__isnull=False)
        .only('account_id')
        .distinct('account_id')
        .values_list('account_id', flat=True)
    )
    if not account_selloff_data:
        logger.info(
            {
                'action': fn_name,
                'state': "failed",
                'identifier': identifier,
                'message': "cannot found data on loanselloff",
            }
        )
        return

    for account_id in account_selloff_data:
        j1_selloff_process.delay(account_id=account_id, loan_selloff_batch_id=loan_selloff_batch_id)

    logger.info(
        {
            'action': fn_name,
            'state': "finish",
            'identifier': identifier,
        }
    )


@task(queue='collection_high')
def j1_selloff_process(account_id, loan_selloff_batch_id):
    fn_name = 'j1_selloff_process'
    identifier = "j1_selloff_process_account_{}".format(account_id)
    current_time = timezone.localtime(timezone.now())
    logger.info(
        {'action': fn_name, 'state': "start", 'time': current_time, 'identifier': identifier}
    )
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        logger.info(
            {
                'action': fn_name,
                'state': "failed",
                'identifier': identifier,
                'message': 'account not found',
            }
        )
        return

    loan_selloff_batch = LoanSelloffBatch.objects.get(pk=loan_selloff_batch_id)
    '''
        since 1 account can has multiple loan and loan status can be paid off
        we will send email to customer if account has active loan in loanselloff
    '''
    is_send_email = (
        loan_selloff_batch.loanselloff_set.filter(account_id=account_id)
        .exclude(loan__loan_status_id=LoanStatusCodes.PAID_OFF)
        .exists()
    )
    status, message = process_account_selloff_j1(
        account, loan_selloff_batch_id, is_send_email=is_send_email
    )
    if not status:
        logger.error(
            {'action': fn_name, 'state': "failed", 'identifier': identifier, 'message': message}
        )
        raise Exception(message)

    logger.info(
        {
            'action': fn_name,
            'state': "finish",
            'identifier': identifier,
        }
    )


@task(queue='collection_normal')
def update_cashback_counter_account_task(
    account_payment_id, is_reversal=False, paid_date=None, cashback_counter=0
):
    fn_name = 'update_cashback_counter_account_task'
    today = timezone.localtime(timezone.now()).date()
    logger.info({'action': fn_name, 'message': 'task begin'})
    account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
    if not account_payment:
        logger.warn(
            {
                'action': fn_name,
                'message': 'account payment id {} not found'.format(account_payment_id),
            }
        )
        return

    if account_payment.is_restructured:
        logger.warn(
            {
                'action': fn_name,
                'message': 'account payment id {} is restructured'.format(account_payment_id),
            }
        )
        return

    if not account_payment.account.is_eligible_for_cashback_new_scheme:
        logger.warn(
            {
                'action': fn_name,
                'message': 'account id {} not eligible for cashback new scheme'.format(
                    account_payment.account.id
                ),
            }
        )
        return

    due_date_cashback = get_due_date_for_cashback_new_scheme()
    paid_date_earlier_cashback_new_scheme = account_payment.due_date - timedelta(
        days=abs(due_date_cashback)
    )
    if paid_date_earlier_cashback_new_scheme >= today and not is_reversal:
        logger.info({'action': fn_name, 'message': 'before cashback terms'})
        account_payment.account.cashback_counter = cashback_counter
        account_payment.account.save()
        logger.info({'action': fn_name, 'message': 'task finish'})
        return
    elif is_reversal:
        logger.info({'action': fn_name, 'message': 'reversal processing'})
        last_counter_history = (
            CashbackCounterHistory.objects.filter(account_payment_id=account_payment.id)
            .values('counter')
            .last()
        )
        if not last_counter_history:
            logger.info({'action': fn_name, 'message': 'cashback history is none'})
            return

        account_payment.account.cashback_counter = last_counter_history.get('counter')
        account_payment.account.save()
        logger.info({'action': fn_name, 'message': 'task finish'})
        return
    else:
        # for handling customer do some paid above due date cashback
        # and scheduler not yet running
        logger.info({'action': fn_name, 'message': 'after cashback terms'})

        account_payment.account.cashback_counter = 0
        account_payment.account.save()
        logger.info({'action': fn_name, 'message': 'task finish'})
        return


@task(queue='collection_normal')
def update_user_timezone_async(account_id):
    if not account_id:
        return

    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return

    do_update_user_timezone(account)


@task(queue="collection_normal")
def send_pn_reactivation_success(customer_id):
    device = Device.objects.filter(customer_id=customer_id).last()
    if not have_pn_device(device):
        logger.warning(
            {
                "action": "juloserver.account.tasks." "account_tasks.send_pn_reactivation_success",
                "error": "transaction status is not settlement",
                "customer_id": customer_id,
            }
        )
        return False
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_reactivation_success(device.gcm_reg_id)
