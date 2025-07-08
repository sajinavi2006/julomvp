import logging

from babel.numbers import parse_number
from cuser.middleware import CuserMiddleware
from datetime import datetime
from django.db import transaction
import pytz

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.models import PaymentMethod
from juloserver.julo.utils import execute_after_transaction_safely

from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.moengage.tasks import update_moengage_for_payment_received_task

logger = logging.getLogger(__name__)


def process_account_manual_payment(user, account_payment, data):
    customer = account_payment.account.customer
    CuserMiddleware.set_user(user)

    paid_date = data['paid_date']
    notes = data['notes']
    payment_method_id = data['payment_method_id']
    payment_receipt = data['payment_receipt']
    use_credits = data['use_credits']
    amount = parse_number(data['partial_payment'], locale='id_ID')
    use_credits = True if use_credits == "true" else False
    payment_method = None
    if use_credits:
        cashback_available = customer.wallet_balance_available
        if amount > cashback_available:
            return False, "Cashback insufficient"

    if payment_method_id:
        payment_method = PaymentMethod.objects.get_or_none(pk=payment_method_id)
        if not payment_method:
            return False, "invalid payment method"
    logger.info({
        'action': 'process_event_type_payment',
        'account_payment_id': account_payment.id,
        'amount': amount,
        'paid_date': paid_date,
        'note': notes,
        'use_credit': use_credits,
    })
    local_timezone = pytz.timezone('Asia/Jakarta')
    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=customer,
            payback_service='manual',
            status_desc='manual process by agent',
            transaction_id='manual-%s' % payment_receipt,
            transaction_date=local_timezone.localize(datetime.strptime(paid_date, '%d-%m-%Y')),
            amount=amount,
            account=account_payment.account,
            payment_method=payment_method
        )
        account_payment = account_payment.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date)
        process_j1_waiver_before_payment(
            account_payment, amount, payback_transaction.transaction_date)

        payment_processed = process_repayment_trx(
            payback_transaction, note=notes, using_cashback=use_credits
        )
        if use_credits:
            payment = account_payment.payment_set.last()
            customer.change_wallet_balance(change_accruing=-amount,
                                           change_available=-amount,
                                           reason=CashbackChangeReason.USED_ON_PAYMENT,
                                           account_payment=account_payment,
                                           payment=payment
                                           )

    if payment_processed:
        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
        )
        return True, "payment event success"
    return False, "payment event not success"
