import logging
from celery import task

from juloserver.account.services.credit_limit import update_account_limit
from juloserver.early_limit_release.constants import (
    EarlyLimitReleaseMoengageStatus,
    ReleaseTrackingType
)
from juloserver.early_limit_release.exceptions import (
    InvalidLoanPaymentInput,
    PaymentNotMatchException,
    InvalidReleaseTracking,
    DuplicateRequestReleaseTracking,
    LoanPaidOffException,
    InvalidLoanStatusRollback,
    LoanMappingIsManualException,
)
from juloserver.early_limit_release.models import (
    ReleaseTracking,
    ReleaseTrackingHistory,
    EarlyReleaseLoanMapping,
)
from juloserver.early_limit_release.services import (
    EarlyLimitReleaseService,
    get_early_release_tracking,
    get_last_release_tracking,
    check_early_limit_fs
)
from juloserver.julo.clients import (
    get_julo_sentry_client
)
from juloserver.julo.models import Payment, Loan, PaymentStatusCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic

from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_early_limit_release

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='loan_normal')
def check_and_release_early_limit(loan_payments_list):
    """
    This function will run the check and calculate limit to release

    Args:
        loan_payment_list (list): list of dictionary contain loan and payments
            loan_payment_list = [{
                loan_id: 1,
                payment_ids: [1,2,3,4]
            }, {
                loan_id: 2,
                payment_ids: [5, 6]
            }]
    """

    action_name = 'early_limit_release.tasks.check_and_release_early_limit'
    logger.info({
        'action': action_name,
        'data': {'loan_payments_list': loan_payments_list}
    })

    if not check_early_limit_fs():
        logger.info({
            'action': action_name,
            "message": "early limit release is disabled in feature setting"
        })
        return

    for loan_payments in loan_payments_list:
        check_and_release_early_limit_per_loan.delay(loan_payments)


@task(queue='loan_normal')
def check_and_release_early_limit_per_loan(loan_payments):
    action_name = 'early_limit_release.tasks.check_and_release_early_limit_per_loan'

    try:
        loan, payments = validate_and_extract_loan_payments_input(
            loan_payments=loan_payments, check_loan_paid_off=True
        )
    except LoanMappingIsManualException:
        logger.info({
            'action': action_name,
            'message': 'The loan already released manually',
            'data': {'loan_payments': loan_payments}
        })
        return
    except LoanPaidOffException:
        logger.info({
            'action': action_name,
            'message': 'No action, because the customer paid all payments',
            'data': {'loan_payments': loan_payments}
        })
        return

    total_release_amount = 0
    for payment in payments:
        service = EarlyLimitReleaseService(account=loan.account, loan=loan, payment=payment)
        tracking = ReleaseTracking.objects.filter(
            payment_id=payment.id, type=ReleaseTrackingType.EARLY_RELEASE
        ).last()
        if tracking and tracking.limit_release_amount != 0:
            raise InvalidReleaseTracking
        if service.check_all_rules():
            limit_release_amount = service.release()
            total_release_amount += limit_release_amount

    if total_release_amount == 0:
        return

    send_user_attributes_to_moengage_for_early_limit_release.delay(
        customer_id=loan.customer_id,
        limit_release_amount=total_release_amount,
        status=EarlyLimitReleaseMoengageStatus.SUCCESS
    )


def validate_and_extract_loan_payments_input(loan_payments, check_loan_paid_off=False):
    """
    Validate loan_payments input

    return is_valid, (loan, payments)
    """
    loan_id = loan_payments.get('loan_id')
    payment_ids = loan_payments.get('payment_ids')
    if not loan_id or not payment_ids:
        raise InvalidLoanPaymentInput()

    if EarlyReleaseLoanMapping.objects.filter(loan_id=loan_id, is_auto=False).exists():
        raise LoanMappingIsManualException()

    loan = Loan.objects.get(pk=loan_id)
    if check_loan_paid_off and loan.status == LoanStatusCodes.PAID_OFF:
        raise LoanPaidOffException()

    payments = Payment.objects.filter(
        pk__in=payment_ids,
        loan=loan,
        payment_status__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
    ).order_by('payment_number')
    payments = list(payments)
    if len(payment_ids) != len(payments):
        raise PaymentNotMatchException()

    return loan, payments


def validate_and_extract_loan_payments_input_for_rollback(loan_payments):
    """
    Validate loan_payments input

    return is_valid, (loan, payments)
    """
    loan_id = loan_payments.get('loan_id')
    payment_ids = loan_payments.get('payment_ids')
    if not loan_id or not payment_ids:
        raise InvalidLoanPaymentInput()

    loan = Loan.objects.get(pk=loan_id)
    payments = Payment.objects.filter(
        pk__in=payment_ids,
        loan=loan,
        payment_status__lt=PaymentStatusCodes.PAID_ON_TIME
    ).order_by('payment_number')
    payments = list(payments)
    if len(payment_ids) != len(payments):
        raise PaymentNotMatchException()

    return loan, payments


@task(queue='loan_normal')
def rollback_early_limit_release(loan_payments_list):
    """
    This function will run the check and calculate limit to release
    Args:
        loan_payments_list (list): list of dictionary contain loan and payments
            loan_payment_list = [{
                loan_id: 1,
                payment_ids: [1,2,3,4]
            }, {
                loan_id: 2,
                payment_ids: [5, 6]
            }]
    """
    logger.info({
        'action': 'early_limit_release.tasks.rollback_early_limit_release',
        'data': {'loan_payments_list': loan_payments_list}
    })
    for loan_payments in loan_payments_list:
        rollback_early_limit_release_per_loan.delay(loan_payments)


@task(queue='loan_normal')
def rollback_early_limit_release_per_loan(loan_payments):
    loan, payments = validate_and_extract_loan_payments_input_for_rollback(
        loan_payments=loan_payments
    )

    account = loan.account
    last_loan_history = loan.loanhistory_set.last()
    loan_status_old = last_loan_history.status_old
    if not (LoanStatusCodes.CURRENT <= loan.status < LoanStatusCodes.PAID_OFF):
        raise InvalidLoanStatusRollback

    account_limit_rollback = 0
    tracking_ids = []
    tracking_histories = []
    for payment in payments:
        early_tracking = get_early_release_tracking(payment)
        if early_tracking:
            tracking_ids.append(early_tracking.id)
            tracking_histories.append(ReleaseTrackingHistory(
                release_tracking=early_tracking,
                value_old=early_tracking.limit_release_amount,
                value_new=0,
                field_name='limit_release_amount'
            ))
            account_limit_rollback += early_tracking.limit_release_amount

    if loan_status_old == LoanStatusCodes.PAID_OFF:
        last_tracking = get_last_release_tracking(loan)
        if last_tracking:
            tracking_ids.append(last_tracking.id)
            tracking_histories.append(ReleaseTrackingHistory(
                release_tracking=last_tracking,
                value_old=last_tracking.limit_release_amount,
                value_new=0,
                field_name='limit_release_amount'
            ))
            account_limit_rollback += last_tracking.limit_release_amount
        else:
            logger.info({
                "action": "rollback_early_limit_release_per_loan",
                "loan": loan,
                "message": "early release doesn't existed last release"
            })
            total_limit_release = ReleaseTracking.objects.get_queryset().total_limit_release(
                loan.id, tracking_type=ReleaseTrackingType.EARLY_RELEASE
            )
            account_limit_rollback += loan.loan_amount - total_limit_release

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        if tracking_ids:
            affected_count = ReleaseTracking.objects.filter(
                pk__in=tracking_ids
            ).exclude(limit_release_amount=0).update(limit_release_amount=0)
            if affected_count != len(tracking_ids):
                raise DuplicateRequestReleaseTracking
            ReleaseTrackingHistory.objects.bulk_create(tracking_histories)
        if account_limit_rollback:
            update_account_limit(-account_limit_rollback, account.id)

    if account_limit_rollback == 0:
        return

    send_user_attributes_to_moengage_for_early_limit_release.delay(
        customer_id=loan.customer_id,
        limit_release_amount=account_limit_rollback,
        status=EarlyLimitReleaseMoengageStatus.ROLLBACK
    )
