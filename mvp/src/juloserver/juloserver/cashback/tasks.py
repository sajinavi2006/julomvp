import logging
from datetime import timedelta, datetime, time
from dateutil.relativedelta import relativedelta

from celery import task
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from bulk_update.helper import bulk_update

from juloserver.account.constants import AccountConstant
from juloserver.cashback.constants import (
    CashbackChangeReason,
    ReferralCashbackEventType,
    ReferralCashbackAction,
    PRODUCT_LINES_FOR_PAYMENT_AND_EXPIRY_CASHBACK,
    PRODUCT_LINES_FOR_PAYMENT_DPD,
)
from juloserver.cashback.services import (
    update_customer_cashback_balance,
    get_referral_cashback_fs,
    get_referral_cashback_action,
    unfreeze_referrer_and_referree_cashback,
    check_and_inject_cashback_to_customer,
)
from juloserver.cashback.utils import chunker_iterables, chunker
from juloserver.customer_module.models import CashbackBalance
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, LoanStatusCodes
from juloserver.julo.models import (
    Customer,
    CustomerWalletHistory,
    Application,
    FeatureSetting,
    Payment,
    LoanHistory,
)
from juloserver.promo.models import PromoCodeUsage
from juloserver.promo.constants import PromoCodeTypeConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import get_expire_cashback_date_setting, log_cashback_task_dpd
from juloserver.julo.services2 import get_cashback_redemption_service
from juloserver.julo.services2.cashback import is_blocked_deduction_cashback
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes

from juloserver.cashback.management.commands.correcting_cashback_earned_and_cashback_balance import\
    get_wallet_histories_by_customer, \
    handling_cashback_deduction, \
    handling_for_other_cashback_reason, \
    handling_overpaid_verification_refund_reason, \
    handling_verification_cashback_overpaid_reason, \
    handling_verifying_overpaid_and_overpaid_void_reason

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

LOOP_COUNT_MAX = 50


@task(queue='loan_low')
def system_used_on_payment_dpd():
    cashback_dpd_pay_off = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CASHBACK_DPD_PAY_OFF, is_active=True
    ).exists()
    if not cashback_dpd_pay_off:
        return

    customer_ids_j1 = Application.objects.filter(
        account__status_id__gte=AccountConstant.STATUS_CODE.active,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        product_line_id=ProductLineCodes.J1,
        customer__wallet_history__wallet_balance_available__gt=0,
        customer__wallet_history__latest_flag=True
    ).distinct('customer_id').values_list('customer_id', flat=True)

    application_ids = Application.objects.values('customer_id').annotate(
        max_app_id=Max('id')
    ).values_list('max_app_id', flat=True)

    customer_ids_mtl = (
        Application.objects.filter(
            id__in=application_ids,
            account__isnull=True,
            application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            product_line_id__in=PRODUCT_LINES_FOR_PAYMENT_DPD,
            customer__wallet_history__wallet_balance_available__gt=0,
            customer__wallet_history__latest_flag=True,
        )
        .distinct('customer_id')
        .values_list('customer_id', flat=True)
    )

    for sub_customer_ids in chunker(customer_ids_j1.iterator(), size=1000):
        system_used_on_payment_dpd_j1_by_batch.delay(sub_customer_ids)

    for sub_customer_ids in chunker(customer_ids_mtl.iterator(), size=1000):
        system_used_on_payment_dpd_mtl_by_batch.delay(sub_customer_ids)


@task(queue='loan_low')
def system_used_on_payment_dpd_mtl_by_batch(customer_ids):
    cashback_dpd_pay_off_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.CASHBACK_DPD_PAY_OFF, is_active=True
    )
    days_past_due = cashback_dpd_pay_off_fs.parameters.get('days_past_due')
    logger.info(
        {
            'action': 'juloserver.cashback.tasks.use_cashback_pay_account_payment_dpd_mtl_by_batch',
            'customer_ids': customer_ids,
            'days_past_due': days_past_due,
        }
    )
    customers = Customer.objects.prefetch_related('account').filter(id__in=customer_ids)
    cashback_redemption_service = get_cashback_redemption_service()

    for customer in customers.iterator():
        try:
            cashback_redemption_service.pay_next_loan_payment(
                customer, CashbackChangeReason.SYSTEM_USED_ON_PAYMENT_DPD_7
            )
        except:
            sentry_client.capture_exceptions()


@task(queue='loan_low')
def system_used_on_payment_dpd_j1_by_batch(customer_ids):
    cashback_dpd_pay_off_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.CASHBACK_DPD_PAY_OFF, is_active=True
    )
    days_past_due = cashback_dpd_pay_off_fs.parameters.get('days_past_due')
    logger.info(
        {
            'action': 'juloserver.cashback.tasks.use_cashback_pay_account_payment_dpd_j1_by_batch',
            'customer_ids': customer_ids,
            'days_past_due': days_past_due,
        }
    )
    customers = Customer.objects.prefetch_related('account').filter(id__in=customer_ids)
    cashback_redemption_service = get_cashback_redemption_service()
    today = timezone.localtime(timezone.now()).date()

    for customer in customers.iterator():
        loop_count = 0
        prev_cashback = customer.wallet_balance_available
        old_last_account_payment = customer.account.get_oldest_unpaid_account_payment()
        if not old_last_account_payment:
            continue
        is_due_date_gt_dpd = (today - old_last_account_payment.due_date).days >= days_past_due
        try:
            while is_due_date_gt_dpd and prev_cashback > 0:
                if loop_count >= LOOP_COUNT_MAX:
                    log_cashback_task_dpd(
                        'cannot_pay_loan', customer.id, {'exceeded_maximum_loop_count': True}
                    )
                    break
                loop_count += 1

                cashback_redemption_service.pay_next_loan_payment(
                    customer, CashbackChangeReason.SYSTEM_USED_ON_PAYMENT_DPD_7
                )

                new_last_account_payment = customer.account.get_oldest_unpaid_account_payment()
                new_cashback = customer.wallet_balance_available
                account_payment_compare = \
                    old_last_account_payment.id == new_last_account_payment.id and \
                    old_last_account_payment.due_amount == new_last_account_payment.due_amount
                if prev_cashback <= new_cashback or account_payment_compare:
                    log_cashback_task_dpd(
                        'cashback_account_payment',
                        customer.id,
                        {
                            'cashback_compare': prev_cashback <= new_cashback,
                            'account_payment_compare': account_payment_compare,
                        },
                    )
                    break
                prev_cashback = new_cashback
                old_last_account_payment = new_last_account_payment
        except:
            sentry_client.capture_exceptions()


@task(queue='loan_normal')
def use_cashback_payment_and_expiry_cashback():
    expiry_date = get_expire_cashback_date_setting()
    if not expiry_date:
        return

    qs = CustomerWalletHistory.objects.get_queryset().cashback_earned_available_to_date(expiry_date)
    customer_ids = qs.distinct('customer_id').values_list('customer_id', flat=True)
    qs = Application.objects.filter(
        customer_id__in=customer_ids,
        product_line__product_line_code__in=PRODUCT_LINES_FOR_PAYMENT_AND_EXPIRY_CASHBACK
    ).values_list('customer_id', flat=True)
    for sub_customer_ids in chunker_iterables([qs.iterator()]):
        use_cashback_payment_and_expiry_cashback_by_batch.delay(sub_customer_ids)


@task(queue='loan_low')
def use_cashback_payment_and_expiry_cashback_by_batch(customer_ids):
    logger.info({
        'action': 'juloserver.cashback.tasks.use_cashback_payment_and_expiry_cashback_by_batch',
        'customer_ids': customer_ids,
    })
    expiry_date = get_expire_cashback_date_setting()
    if not expiry_date:
        return

    cashback_redemption_service = get_cashback_redemption_service()
    customers = Customer.objects.filter(id__in=customer_ids)

    for customer in customers.iterator():
        is_cashback_blocked = is_blocked_deduction_cashback(customer)
        if is_cashback_blocked:
            continue

        previous_cashback = customer.wallet_history.get_queryset(). \
            total_cashback_earned_available_to_date(expiry_date)
        loop_count = 0
        try:
            while True:
                if loop_count >= LOOP_COUNT_MAX:
                    log_cashback_task_dpd(
                        'cannot_pay_loan', customer.id, {'exceeded_maximum_loop_count': True}
                    )
                    break
                loop_count += 1
                cashback_redemption_service.pay_next_loan_payment(
                    customer, CashbackChangeReason.SYSTEM_USED_ON_PAYMENT_EXPIRY_DATE,
                    is_cashback_blocked=is_cashback_blocked
                )
                new_cashback = customer.wallet_history.get_queryset(). \
                    total_cashback_earned_available_to_date(expiry_date)
                if new_cashback <= 0 or new_cashback >= previous_cashback:
                    break

                previous_cashback = new_cashback

            if new_cashback > 0:
                customer.change_wallet_balance(
                    -new_cashback, -new_cashback, CashbackChangeReason.CASHBACK_EXPIRED_END_OF_YEAR
                )
        except:
            sentry_client.capture_exceptions()


@task(queue='loan_low')
def update_cashback_earned_and_cashback_balance(customer_ids, today):
    logger.info({
        'action': 'update_cashback_earned_and_cashback_balance by batch',
        'customer_ids': customer_ids,
    })
    customers = Customer.objects.filter(id__in=customer_ids)
    for customer in customers.iterator():
        is_looping = True
        with transaction.atomic():
            wallet_histories = get_wallet_histories_by_customer(customer)
            cashback_earned_list = []
            wallet_history_list = []
            previous_balance = 0
            for wallet_history in wallet_histories:
                try:
                    if wallet_history.wallet_balance_available < 0:
                        raise Exception('wallet_balance_available is < 0')
                except Exception:
                    sentry_client.captureMessage({
                        'error': 'wallet_balance_available is negative',
                        'task': 'update_cashback_earned_and_cashback_balance',
                        'customer_id': customer.id,
                        'customer_wallet_history_id': wallet_history.id
                    })
                    logger.warning({
                        'action': 'update_cashback_earned_and_cashback_balance',
                        'error': 'wallet_balance_available is negative',
                        'customer_id': customer.id,
                        'customer_wallet_history_id': wallet_history.id
                    })
                    is_looping = False
                    break
                cashback_amount = wallet_history.wallet_balance_available - previous_balance
                previous_balance = wallet_history.wallet_balance_available
                reason = wallet_history.change_reason
                if cashback_amount > 0:
                    # exception for cashback_over_paid change_reason
                    if reason == CashbackChangeReason.CASHBACK_OVER_PAID:
                        handling_verification_cashback_overpaid_reason(
                            wallet_history,
                            wallet_history_list,
                            cashback_earned_list,
                            cashback_amount,
                            today
                        )

                    elif reason == CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED:
                        try:
                            handling_overpaid_verification_refund_reason(
                                cashback_earned_list,
                                cashback_amount
                            )
                        except Exception:
                            sentry_client.captureMessage({
                                'error': 'cashback_overpaid case with the same amount is not found',
                                'task': 'update_cashback_earned_and_cashback_balance',
                                'change_reason': reason,
                                'customer_id': customer.id,
                                'customer_wallet_history_id': wallet_history.id
                            })
                            logger.warning({
                                'action': 'update_cashback_earned_and_cashback_balance',
                                'change_reason': reason,
                                'error': 'cashback_overpaid_case not found',
                                'customer_id': customer.id,
                                'customer_wallet_history_id': wallet_history.id
                            })
                            is_looping = False
                            break
                    else:
                        handling_for_other_cashback_reason(
                            wallet_history,
                            wallet_history_list,
                            cashback_earned_list,
                            cashback_amount,
                            today
                        )
                elif cashback_amount < 0:
                    if reason == CashbackChangeReason.VERIFYING_OVERPAID or \
                            reason == CashbackChangeReason.CASHBACK_OVER_PAID_VOID:
                        try:
                            handling_verifying_overpaid_and_overpaid_void_reason(
                                cashback_earned_list,
                                cashback_amount
                            )
                        except Exception:
                            sentry_client.captureMessage({
                                'error': 'cashback_overpaid case with the same amount is not found',
                                'task': 'update_cashback_earned_and_cashback_balance',
                                'change_reason': reason,
                                'customer_id': customer.id,
                                'customer_wallet_history_id': wallet_history.id
                            })
                            logger.warning({
                                'action': 'update_cashback_earned_and_cashback_balance',
                                'change_reason': reason,
                                'error': 'cashback_overpaid_case not found',
                                'customer_id': customer.id,
                                'customer_wallet_history_id': wallet_history.id
                            })
                            is_looping = False
                            break
                    else:
                        handling_cashback_deduction(
                            cashback_earned_list,
                            cashback_amount
                        )
            if not is_looping:
                continue

            cashback_earned_objs_for_updation = [cashback_earned[0] for cashback_earned in
                                                 cashback_earned_list]
            logger.info({
                'action': 'success update_cashback_earned_and_cashback_balance',
                'customer_id': customer.id,
            })
            bulk_update(cashback_earned_objs_for_updation)
            bulk_update(wallet_history_list, update_fields=['cashback_earned'])


@task(queue='loan_low')
def update_cashback_balance_by_batch(customer_ids):
    logger.info({
        'actions': 'update_cashback_balance_by_batch',
        'customer_ids': customer_ids
    })
    customers_with_cashback = CashbackBalance.objects.filter(customer_id__in=customer_ids)
    for customer_cashback in customers_with_cashback:
        new_balance_available = update_customer_cashback_balance(customer_cashback.customer)
        status = 'success' if new_balance_available >= 0 else 'failed'
        logger.info({
            'actions': 'update_cashback_balance_by_batch_one_user_completed',
            'status': status,
            'customer_id': customer_cashback.customer_id,
            'cashback_balance': new_balance_available
        })


@task(queue='loan_low')
def unfreeze_referral_cashback():
    action = get_referral_cashback_action(event_type=ReferralCashbackEventType.CRONJOB)
    if action == ReferralCashbackAction.DO_NOTHING:
        return

    fs = get_referral_cashback_fs()
    params = fs.parameters or {}
    period_logic = params['period_logic']
    freeze_period = period_logic['freeze_period']
    unfreeze_threshold = timezone.localtime(timezone.now() - timedelta(days=freeze_period)).date()

    customer_wallet_histories = CustomerWalletHistory.objects.select_related(
        'customer'
    ).filter(
        change_reason=CashbackChangeReason.PROMO_REFERRAL_FRIEND,
        cashback_earned__verified=False,
        cashback_earned__cdate__date__lte=unfreeze_threshold
    )

    for history in customer_wallet_histories:
        referee = history.customer
        if action == ReferralCashbackAction.UNFREEZE_FIRST_REPAYMENT:
            if not Payment.objects.filter(
                loan__customer=referee,
                payment_number=1,
                payment_status__gte=PaymentStatusCodes.PAID_ON_TIME
            ).exists():
                continue
        unfreeze_referrer_and_referree_cashback(referee)


@task(queue='loan_normal')
def unfreeze_referrer_and_referree_cashback_task(referee_id):
    referee = Customer.objects.get_or_none(pk=referee_id)
    if not referee:
        return

    unfreeze_referrer_and_referree_cashback(referee)


@task(queue='loan_low')
def inject_cashback_promo_task():
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PROMO_CODE_FOR_CASHBACK_INJECTION, is_active=True
    )
    if not fs:
        return

    promo_code_string_list_parameters = fs.parameters.get('promo_code_list')
    promo_code_string_list = [
        promo_code.strip() for promo_code in promo_code_string_list_parameters
    ]

    """
    Handle if task does not run at exactly 00:00
    Convert to midnight_today
    datetime.datetime(2024, 5, 25, 0, 0, tzinfo=<DstTzInfo 'Asia/Jakarta' WIB+7:00:00 STD>)
    """
    midnight_today = timezone.localtime(
        datetime.combine(timezone.localtime(timezone.now()).date(), time())
    )
    end_time = midnight_today.replace(day=21)
    start_time = end_time - relativedelta(months=1)

    for promo_code_string in promo_code_string_list:
        # 1 promo string can have multiple promo code ids
        # Get all loan x250 that applied promo code string
        loan_ids_with_promo_code = list(
            PromoCodeUsage.objects.filter(
                promo_code__promo_code__iexact=promo_code_string,
                promo_code__type=PromoCodeTypeConst.LOAN,
                applied_at__isnull=False,
            ).values_list('loan_id', flat=True)
        )

        # Filter loan x250 between 21th of previous month and 20th of current month
        loan_paid_off_ids_in_time_range = list(
            LoanHistory.objects.filter(
                loan_id__in=loan_ids_with_promo_code,
                status_new=LoanStatusCodes.PAID_OFF,
                cdate__gte=start_time,
                cdate__lt=end_time,
            ).values_list('loan_id', flat=True)
        )

        if not loan_paid_off_ids_in_time_range:
            logger.error(
                {
                    'action': 'inject_cashback_promo_task',
                    'message': 'Does not have any loan paid off with promo code string',
                    'promo_code_string': promo_code_string,
                }
            )
            return

        promo_code_usage_queryset = PromoCodeUsage.objects.filter(
            loan_id__in=loan_paid_off_ids_in_time_range
        )

        for promo_code_usage in promo_code_usage_queryset.iterator():
            customer_id = promo_code_usage.customer_id
            loan_id = promo_code_usage.loan_id
            promo_code_id = promo_code_usage.promo_code_id
            inject_cashback_promo_subtask.delay(
                customer_id, loan_id, promo_code_string, promo_code_id
            )


@task(queue='loan_low')
def inject_cashback_promo_subtask(customer_id, loan_id, promo_code_string, promo_code_id):
    check_and_inject_cashback_to_customer(customer_id, loan_id, promo_code_string, promo_code_id)
    logger.info(
        {
            'action': 'inject_cashback_promo_task',
            'promo_code': promo_code_string,
            'customer_id': customer_id,
            'loan_id': loan_id,
        }
    )
