from typing import (
    Optional,
)

from datetime import datetime
from django.db import transaction

from juloserver.julo.models import (
    PaybackTransaction,
)
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.account.models import AccountTransaction
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.julo.services import get_oldest_payment_due


def process_cimb_repayment(
    payback_transaction_id: int,
    paid_datetime: datetime,
    paid_amount: float,
) -> Optional[AccountTransaction]:
    note = 'payment with cimb va'

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(
            pk=payback_transaction_id
        )
        if payback_transaction.is_processed:
            return
        loan = get_active_loan(payback_transaction.payment_method)
        payment = get_oldest_payment_due(loan)
        payback_transaction.update_safely(
            amount=paid_amount,
            transaction_date=paid_datetime,
            payment=payment,
            loan=loan,
        )
        account_payment = payback_transaction.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date
        )
        process_j1_waiver_before_payment(account_payment, payback_transaction.amount, paid_datetime)
        payment_processed = process_repayment_trx(payback_transaction, note=note)

    if payment_processed:
        update_moengage_for_payment_received_task.delay(payment_processed.id)

    return payment_processed
