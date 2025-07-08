from typing import Dict

from datetime import datetime
from django.db import transaction
from django.utils import timezone

from juloserver.julo.models import PaybackTransaction
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.account_payment.services.payment_flow import process_rentee_deposit_trx
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.julo.services import get_oldest_payment_due


def doku_snap_payment_process_account(
    payback_transaction: PaybackTransaction, data: Dict, note: str
) -> None:

    transaction_date_str = data.get('trxDateTime', data.get('transactionDate'))
    if transaction_date_str is None:
        transaction_date = timezone.localtime(timezone.now())
    else:
        transaction_date = datetime.strptime(transaction_date_str, '%Y-%m-%dT%H:%M:%S%z')

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(
            pk=payback_transaction.id
        )
        if payback_transaction.is_processed:
            return

        loan = get_active_loan(payback_transaction.payment_method)
        if not loan:
            return

        payment = get_oldest_payment_due(loan)
        payback_transaction.update_safely(
            amount=float(data['paidAmount']['value']),
            transaction_date=transaction_date,
            payment=payment,
            loan=loan,
        )

        account_payment = payback_transaction.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date
        )
        process_j1_waiver_before_payment(
            account_payment, payback_transaction.amount, transaction_date
        )
        payment_processed = process_rentee_deposit_trx(payback_transaction)
        if not payment_processed:
            payment_processed = process_repayment_trx(payback_transaction, note=note)
    if payment_processed:
        update_moengage_for_payment_received_task.delay(payment_processed.id)
