import logging
from celery import task

from datetime import datetime, timedelta
from django.db import transaction
from redis.exceptions import LockError

from juloserver.account.models import AccountTransaction
from juloserver.account_payment.models import (
    CashbackClaim,
    CashbackClaimPayment,
)
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.account_payment.services.collection_related import get_cashback_claim_experiment
from juloserver.account_payment.services.earning_cashback import make_cashback_available

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Payment,
    Loan,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.services2 import get_redis_client


logger = logging.getLogger(__name__)


@task(queue='collection_high')
def create_eligible_cashback(account_transaction_id, paid_off_account_payment_ids):
    fn = 'create_eligible_cashback'
    logger.info(
        {
            'action': fn,
            'message': 'starting task',
            'account_transaction_id': account_transaction_id,
            'paid_off_account_payment_ids': paid_off_account_payment_ids,
        }
    )
    retries = create_eligible_cashback.request.retries
    current_date = datetime.now().date()

    account_transaction = AccountTransaction.objects.filter(pk=account_transaction_id).last()
    if not account_transaction:
        logger.warning(
            {
                'action': fn,
                'message': 'account_transaction not found',
                'account_transaction_id': account_transaction_id,
                'paid_off_account_payment_ids': paid_off_account_payment_ids,
            }
        )
        return

    account = account_transaction.account
    cashback_experiment, is_cashback_experiment = get_cashback_claim_experiment(
        date=current_date, account=account
    )
    if not cashback_experiment:
        logger.warning(
            {
                'action': fn,
                'message': 'feature setting is turned off',
                'account_transaction_id': account_transaction_id,
                'paid_off_account_payment_ids': paid_off_account_payment_ids,
            }
        )
        return

    if not is_cashback_experiment:
        logger.warning(
            {
                'action': fn,
                'message': 'account is not experiment group',
                'account_transaction_id': account_transaction_id,
                'paid_off_account_payment_ids': paid_off_account_payment_ids,
            }
        )
        return
    cashback_claim_duration = cashback_experiment.criteria.get('claim_duration', 8)

    redis_client = get_redis_client()
    lock = redis_client.lock(
        CashbackClaimConst.CASHBACK_CLAIM_LOCK.format(str(account.id)),
        timeout=30 * (retries + 1),  # The maximum time to hold the lock
        sleep=3,  # Sleep time between each retry
    )
    try:
        with lock:
            payment_ids = list(
                Payment.objects.paid()
                .filter(
                    account_payment_id__in=paid_off_account_payment_ids,
                )
                .values_list('id', flat=True)
            )

            with transaction.atomic(using='collection_db'):
                cashback_claim_payments = CashbackClaimPayment.objects.select_for_update().filter(
                    payment_id__in=payment_ids,
                    status=CashbackClaimConst.STATUS_PENDING,
                )
                if not cashback_claim_payments:
                    logger.info(
                        {
                            'action': fn,
                            'message': 'no pending cashback',
                            'account_transaction_id': account_transaction_id,
                            'paid_off_account_payment_ids': paid_off_account_payment_ids,
                        }
                    )
                    return

                cashback_claim, _ = CashbackClaim.objects.get_or_create(
                    status=CashbackClaimConst.STATUS_ELIGIBLE,
                    account_id=account.id,
                    defaults={'account_transaction_id': account_transaction_id},
                )
                total_cashback_amount = cashback_claim.total_cashback_amount or 0
                for cashback_claim_payment in cashback_claim_payments:
                    total_cashback_amount += cashback_claim_payment.cashback_amount

                cashback_claim.update_safely(total_cashback_amount=total_cashback_amount)
                cashback_claim_payments.update(
                    cashback_claim=cashback_claim,
                    status=CashbackClaimConst.STATUS_ELIGIBLE,
                    max_claim_date=current_date + timedelta(days=cashback_claim_duration),
                )

    except LockError as exc:
        if retries >= create_eligible_cashback.max_retries:
            logger.error(
                {
                    'action': fn,
                    'message': 'maximum retries reached',
                    'account_transaction_id': account_transaction_id,
                    'paid_off_account_payment_ids': paid_off_account_payment_ids,
                }
            )
            get_julo_sentry_client().captureException()
            return

        logger.warning(
            {
                'action': fn,
                'message': 'lock error attempting retry {}'.format(str(retries)),
                'account_transaction_id': account_transaction_id,
                'paid_off_account_payment_ids': paid_off_account_payment_ids,
            }
        )
        create_eligible_cashback.retry(
            countdown=300,
            exc=exc,
            max_retries=3,
            args=(account_transaction_id, paid_off_account_payment_ids),
        )
    except Exception as exc:
        logger.error(
            {
                'action': fn,
                'message': str(exc),
                'account_transaction_id': account_transaction_id,
                'paid_off_account_payment_ids': paid_off_account_payment_ids,
            }
        )
        get_julo_sentry_client().captureException()

    logger.info(
        {
            'action': fn,
            'message': 'task finished',
            'account_transaction_id': account_transaction_id,
            'paid_off_account_payment_ids': paid_off_account_payment_ids,
        }
    )


@task(queue='collection_normal')
def expiry_cashback_claim_experiment():
    fn = 'expiry_cashback_claim_experiment'
    logger.info(
        {
            'action': fn,
            'message': 'starting task',
        }
    )

    current_date = datetime.now().date()
    cashback_experiment, _ = get_cashback_claim_experiment(date=current_date)
    if not cashback_experiment:
        logger.warning(
            {
                'action': fn,
                'message': 'feature setting is turned off',
            }
        )
        return

    cashback_claim_payment_ids = CashbackClaimPayment.objects.filter(
        status=CashbackClaimConst.STATUS_ELIGIBLE,
        max_claim_date__lt=current_date,
    ).values_list('id', flat=True)
    for cashback_claim_payment_id in cashback_claim_payment_ids:
        expiry_cashback_claim_experiment_subtask.delay(cashback_claim_payment_id)

    logger.info(
        {
            'action': fn,
            'message': 'task finished',
        }
    )


@task(queue='collection_normal')
def expiry_cashback_claim_experiment_subtask(cashback_claim_payment_id):
    fn = 'expiry_cashback_claim_experiment_subtask'
    logger.info(
        {
            'action': fn,
            'message': 'starting task',
            'cashback_claim_payment_id': cashback_claim_payment_id,
        }
    )

    with transaction.atomic(), transaction.atomic(using='collection_db'):
        cashback_claim_payment = (
            CashbackClaimPayment.objects.select_for_update()
            .filter(id=cashback_claim_payment_id, status=CashbackClaimConst.STATUS_ELIGIBLE)
            .last()
        )
        if not cashback_claim_payment:
            logger.error(
                {
                    'action': fn,
                    'message': 'pending cashback claim payment not found',
                    'cashback_claim_payment_id': cashback_claim_payment_id,
                }
            )
            return

        current_date = datetime.now().date()
        if not current_date > cashback_claim_payment.max_claim_date:
            logger.error(
                {
                    'action': fn,
                    'message': 'current date is lesser than max claim date',
                    'cashback_claim_payment_id': cashback_claim_payment_id,
                }
            )
            return

        cashback_claim = (
            CashbackClaim.objects.select_for_update()
            .filter(id=cashback_claim_payment.cashback_claim_id)
            .last()
        )
        cashback_claim_payment.update_safely(status=CashbackClaimConst.STATUS_EXPIRED)
        if cashback_claim:
            pending_cashback_payments = cashback_claim.cashbackclaimpayment_set.filter(
                status__in=[CashbackClaimConst.STATUS_PENDING, CashbackClaimConst.STATUS_ELIGIBLE],
            )
            if not pending_cashback_payments.exists():
                cashback_claim.update_safely(
                    status=CashbackClaimConst.STATUS_EXPIRED,
                    total_cashback_amount=cashback_claim.total_cashback_amount
                    - cashback_claim_payment.cashback_amount,
                )
                cashback_payment_ids = list(
                    cashback_claim.cashbackclaimpayment_set.values_list('payment_id', flat=True)
                )
                loans = Loan.objects.select_for_update().filter(
                    id__in=Payment.objects.paid()
                    .filter(id__in=cashback_payment_ids)
                    .values_list('loan_id', flat=True)
                    .distinct(),
                    loan_status_id=LoanStatusCodes.PAID_OFF,
                )
                for loan in loans:
                    make_cashback_available(loan)
            else:
                cashback_claim.update_safely(
                    total_cashback_amount=cashback_claim.total_cashback_amount
                    - cashback_claim_payment.cashback_amount
                )

        logger.info(
            {
                'action': fn,
                'message': 'task finished',
                'cashback_claim_payment_id': cashback_claim_payment_id,
            }
        )
