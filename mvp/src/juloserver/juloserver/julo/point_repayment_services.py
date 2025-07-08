from django.db import transaction
from django.utils import timezone
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.moengage.tasks import update_moengage_for_payment_received_task


def point_payment_process_account(account, note, amount_deduct):
    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        return False, None, None

    used_wallet_amount = get_paid_amount_and_point_amount(amount_deduct, account_payment)
    if used_wallet_amount <= 0:
        return False, None, 0

    transaction_date = timezone.localtime(timezone.now())
    customer = account.customer

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=customer,
            payback_service='loyalty_point',
            status_desc='payment using loyalty point',
            transaction_date=transaction_date,
            amount=used_wallet_amount,
            account=account
        )
        payment_processed = process_repayment_trx(payback_transaction, note=note)
        if payment_processed:
            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
            )
            return True, payback_transaction, used_wallet_amount
    return False, None, None


def get_paid_amount_and_point_amount(amount_deduct, account_payment):
    due_amount = account_payment.due_amount
    return min(amount_deduct, due_amount)
