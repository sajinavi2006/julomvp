import logging

from django.db import transaction
from django.utils import timezone

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.models import (
    PaybackTransaction,
    Payment
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.services import (
    get_paid_amount_and_wallet_amount,
    get_used_wallet_customer_for_paid_checkout_experience
)
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.account_payment.models import AccountPayment

logger = logging.getLogger(__name__)


def cashback_payment_process_account(account, note, change_reason):
    account_payment = account.get_oldest_unpaid_account_payment()
    # handle paid off on level loan, but not on account_payment level
    if not account_payment:
        return False

    _, _, _, used_wallet_amount = get_paid_amount_and_wallet_amount(
        None, account.customer, 0, use_wallet=True,
        account_payment=account_payment, change_reason=change_reason
    )
    if used_wallet_amount <= 0:
        return False
    transaction_date = timezone.localtime(timezone.now())
    customer = account.customer

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=customer,
            payback_service='cashback',
            status_desc='payment using cashback wallet',
            transaction_date=transaction_date,
            amount=used_wallet_amount,
            account=account
        )
        payment_processed = process_repayment_trx(
            payback_transaction, note=note, using_cashback=True)
        payment = account_payment.payment_set.last()
        customer.change_wallet_balance(change_accruing=-used_wallet_amount,
                                       change_available=-used_wallet_amount,
                                       reason=change_reason,
                                       account_payment=account_payment,
                                       payment=payment
                                       )

    if payment_processed:
        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
        )
        return True
    return False


def cashback_payment_process_checkout_experience(account, note, account_payment_ids):
    logger.info({
        "function": "cashback_payment_process_checkout_experience",
        "info": "function begin"
    })
    account_payments = AccountPayment.objects.only('due_amount') \
        .filter(pk__in=account_payment_ids)
    payment = Payment.objects.filter(
        account_payment_id__in=account_payment_ids).last()
    used_wallet_amount = get_used_wallet_customer_for_paid_checkout_experience(
        account.customer, account_payments)
    logger.info({
        "function": "get_used_wallet_customer_for_paid_checkout_experience",
        "info": "used wallet amount %s" % used_wallet_amount
    })
    if used_wallet_amount <= 0:
        return False

    transaction_date = timezone.localtime(timezone.now())
    customer = account.customer

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=customer,
            payback_service='cashback',
            status_desc='payment using cashback wallet',
            transaction_date=transaction_date,
            amount=used_wallet_amount,
            account=account
        )
        payment_processed = process_repayment_trx(
            payback_transaction, note=note, using_cashback=True)

    logger.info({
        "function": "process_repayment_trx",
        "status": "is processed %s" % payment_processed
    })

    if payment_processed:
        customer.change_wallet_balance(
            change_accruing=-payback_transaction.amount,
            change_available=-payback_transaction.amount,
            reason='used_on_payment',
            account_payment=payment.account_payment,
            payment=payment,
            loan=payment.loan,
        )

        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
        )
        return True

    return False
