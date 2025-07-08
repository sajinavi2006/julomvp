import logging
from typing import List, Union

from celery import task
from datetime import timedelta

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from juloserver.account.models import Account, AccountGTL, AccountGTLHistory
from juloserver.account_payment.services.earning_cashback import (
    make_cashback_available,
)
from juloserver.account_payment.services.collection_related import get_cashback_claim_experiment
from juloserver.account_payment.models import CashbackClaimPayment
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.julo.constants import RedisLockKeyName
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.julo.exceptions import DuplicateRequests, JuloException
from juloserver.julo.models import Loan, Payment
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan.constants import GTLChangeReason
from juloserver.loan.exceptions import GTLException
from juloserver.loan.services.loan_related import (
    get_parameters_fs_check_gtl,
    is_apply_gtl_inside,
    create_or_update_is_maybe_gtl_inside_and_send_to_moengage,
    update_loan_status_and_loan_history,
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.services.use_cases import send_gtl_event_to_moengage_bulk

logger = logging.getLogger(__name__)


def update_gtl_status_bulk(
    gtl_ids: Union[QuerySet, List[int]], field_name: str, old_value: bool, new_value: bool
):
    """
    update gtl status in bulk
    gtl_ids can be QuerySet or List of ids
    """
    if field_name == 'is_gtl_outside':
        moengage_event_type = MoengageEventType.GTL_OUTSIDE
        change_reason = GTLChangeReason.GTL_OUTSIDE_TIME_EXPIRES
    elif field_name == 'is_gtl_inside':
        moengage_event_type = MoengageEventType.GTL_INSIDE
        change_reason = GTLChangeReason.GTL_MANUAL_UNBLOCK_INSIDE
    else:
        raise GTLException('missing field_name')

    current_value = {field_name: old_value}
    gtl_ids = AccountGTL.objects.filter(
        pk__in=gtl_ids,
        **current_value,
    ).values_list('id', 'account_id')

    # extract ids
    account_gtl_ids = [x[0] for x in gtl_ids]
    account_ids = [x[1] for x in gtl_ids]

    # customers ids for moengage
    customer_ids = (
        Account.objects.filter(
            id__in=account_ids,
        )
        .distinct('customer_id')
        .values_list('customer_id', flat=True)
    )

    account_gtl_histories = []
    update_dict = {field_name: new_value}
    with transaction.atomic():
        # update accounts
        AccountGTL.objects.filter(
            id__in=account_gtl_ids,
        ).update(**update_dict)

        # create history records
        for account_gtl_id in account_gtl_ids:
            history = AccountGTLHistory(
                account_gtl_id=account_gtl_id,
                field_name=field_name,
                value_old=old_value,
                value_new=new_value,
                change_reason=change_reason,
            )
            account_gtl_histories.append(history)

        AccountGTLHistory.objects.bulk_create(account_gtl_histories)

        execute_after_transaction_safely(
            lambda: send_gtl_event_to_moengage_bulk.delay(
                customer_ids=customer_ids,
                event_type=moengage_event_type,
                event_attributes={field_name: new_value},
            )
        )


@task(queue='loan_normal')
def expire_gtl_outside() -> None:
    """
    Unset GTL Outside if expiry date hits
    """
    today = timezone.localtime(timezone.now()).date()

    old_value = True
    new_value = False

    # find gtl ids
    gtl_ids = AccountGTL.objects.filter(
        last_gtl_outside_blocked__date__lte=today,
        is_gtl_outside=old_value,
    ).values_list('id', flat=True)

    update_gtl_status_bulk(
        gtl_ids=gtl_ids,
        field_name='is_gtl_outside',
        old_value=old_value,
        new_value=new_value,
    )


@task(queue="loan_normal")
def adjust_is_maybe_gtl_inside(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if loan and is_apply_gtl_inside(
        transaction_method_code=loan.transaction_method_id, application=loan.get_application
    ):
        last_payment = Payment.objects.filter(loan=loan).order_by('-payment_number').first()
        if last_payment.payment_status_id in PaymentStatusCodes.paid_dpd_plus_one():
            try:
                with redis_lock_for_update(
                    key_name=RedisLockKeyName.HANDLE_MAYBE_GTL_INSIDE_STATUS_AND_NOTIFY,
                    unique_value=loan.account_id,
                    no_wait=True,
                ):
                    create_or_update_is_maybe_gtl_inside_and_send_to_moengage(
                        customer_id=loan.customer_id,
                        account_id=loan.account_id,
                        new_value_is_maybe_gtl_inside=True,
                    )
            except DuplicateRequests:
                logger.info(
                    {
                        'action': 'adjust_is_maybe_gtl_inside',
                        'account_id': loan.account_id,
                        'loan_id': loan_id,
                        'message': 'User paid off an account payment has multiple DPD+1 loans '
                        '-> only handle once',
                    }
                )


@task(queue="loan_normal")
def update_is_maybe_gtl_inside_to_false():
    """
    When user paid off a loan late, is_maybe_gtl_inside become True, udate will be updated
    Then, user continue to make new loan, is_maybe_gtl_inside will be updated to False
    But if user doesn't make new loan, is_maybe_gtl_inside is still True forever
    => This cron job will update is_maybe_gtl_inside to False after threshold_loan_within_hours
    Can use udate to check when the last time is_maybe_gtl_inside was updated
    because no other fields is updated when user doesn't make new loan, lead to udate is not updated
    """
    logger.info(
        {
            'action': 'update_is_maybe_gtl_inside_to_false',
            'message': 'start job',
        }
    )

    params = get_parameters_fs_check_gtl()
    if not params:
        return

    now = timezone.localtime(timezone.now())

    account_gtls = (
        AccountGTL.objects.select_related('account')
        .filter(
            is_maybe_gtl_inside=True,
            udate__lt=now - timedelta(hours=params['threshold_loan_within_hours']),
        )
        .all()
    )
    if not account_gtls:
        return

    customer_ids = [account_gtl.account.customer_id for account_gtl in account_gtls]

    with transaction.atomic():
        AccountGTL.objects.filter(id__in=account_gtls).update(is_maybe_gtl_inside=False)

        AccountGTLHistory.objects.bulk_create(
            [
                AccountGTLHistory(
                    account_gtl=account_gtl,
                    field_name='is_maybe_gtl_inside',
                    value_old=True,
                    value_new=False,
                )
                for account_gtl in account_gtls
            ]
        )

        execute_after_transaction_safely(
            lambda: send_gtl_event_to_moengage_bulk.delay(
                customer_ids=customer_ids,
                event_type=MoengageEventType.MAYBE_GTL_INSIDE,
                event_attributes={'is_maybe_gtl_inside': False},
            )
        )

    logger.info(
        {
            'action': 'update_is_maybe_gtl_inside_to_false',
            'length': len(customer_ids),
            'customer_ids': customer_ids,
            'message': 'updated is_maybe_gtl_inside to False successfully',
        }
    )


@task(queue='repayment_high')
def repayment_update_loan_status(
    loan_id,
    new_status_code,
    change_by_id=None,
    change_reason="system triggered",
    force=False,
    times_retried=0,
):
    """
    Update Loan Status for repayment case ONLY.

    Args:
        loan_id (int): The ID of the loan.
        new_status_code (int): To specify the new new loan status,
                               have to be lower than the current.
        change_by_id (int, optional): To identify the user who did the change.
        change_reason (str, optional): To specify the reason for the status update.
        force (boolean, optional): To allow force status update.
        times_retried (int, optional): To specify current retry attempt.

    Returns:
        None

    Retry Mechanism:
    - The task will be retried if it fails and the maximum number of retries has not been reached.
    - Each retry will be scheduled with an increasing countdown time.
    - The countdown time is calculated as 30 seconds multiplied by the number of retries.
    - The maximum number of retries is set to 3.
    """
    logger.info(
        {
            'action': 'repayment_update_loan',
            'loan_id': loan_id,
        }
    )
    kwargs = {
        'loan_id': loan_id,
        'new_status_code': new_status_code,
        'change_by_id': change_by_id,
        'change_reason': change_reason,
        'force': force,
    }
    try:
        with transaction.atomic():
            # Validation to check whether the loan status is allowed to be changed.
            # If old status is not paid off and new status have lower than old status,
            # or new status is paid off.
            loan = Loan.objects.select_for_update().get(id=loan_id)
            if force or (
                loan.loan_status_id != LoanStatusCodes.PAID_OFF
                and (
                    new_status_code == LoanStatusCodes.PAID_OFF
                    or LoanStatusCodes.LoanStatusesDPD.get(new_status_code)
                    < LoanStatusCodes.LoanStatusesDPD.get(loan.loan_status_id)
                )
            ):
                # To handle when payment got reverted before task is running.
                if (
                    new_status_code == LoanStatusCodes.PAID_OFF
                    and len(loan.payment_set.select_for_update().not_paid()) != 0
                ):
                    logger.info(
                        {
                            'action': 'repayment_update_loan',
                            'loan_id': loan_id,
                            'message': 'unable to change unpaid loan to %s' % (new_status_code),
                        }
                    )
                    return

                update_loan_status_and_loan_history(**kwargs)
                loan.refresh_from_db()

                if loan.product.has_cashback and loan.loan_status_id == LoanStatusCodes.PAID_OFF:
                    _, is_cashback_experiment = get_cashback_claim_experiment(account=loan.account)

                    if not is_cashback_experiment:
                        make_cashback_available(loan)
                    else:
                        payment_ids = list(
                            Payment.objects.paid().filter(loan=loan).values_list('id', flat=True)
                        )
                        pending_cashback_exists = CashbackClaimPayment.objects.filter(
                            payment_id__in=payment_ids,
                            status__in=[
                                CashbackClaimConst.STATUS_PENDING,
                                CashbackClaimConst.STATUS_ELIGIBLE,
                            ],
                        ).exists()
                        # Case when customer already claim cashback before loan status updated
                        if not pending_cashback_exists:
                            make_cashback_available(loan)

            else:
                logger.info(
                    {
                        'action': 'repayment_update_loan',
                        'loan_id': loan_id,
                        'message': 'status change %s to %s is not allowed'
                        % (loan.loan_status_id, new_status_code),
                    }
                )
    except JuloException as e:
        # Not doing retry on excepted error.
        logger.error(
            {
                'action': 'repayment_update_loan',
                'loan_id': loan_id,
                'message': str(e),
            }
        )
    except Exception as e:
        logger.error(
            {
                'action': 'repayment_update_loan',
                'loan_id': loan_id,
                'message': str(e),
            }
        )
        if times_retried >= 3:
            raise Exception("Maximum retries reached")
        kwargs.update(times_retried=times_retried + 1)
        repayment_update_loan_status.apply_async(
            kwargs=kwargs,
            countdown=30 * (times_retried + 1),
        )
