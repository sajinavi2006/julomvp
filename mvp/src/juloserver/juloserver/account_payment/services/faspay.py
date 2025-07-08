from datetime import datetime
from django.db import transaction
from typing import Tuple, Dict
from django.conf import settings

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.account_payment.services.payment_flow import process_rentee_deposit_trx

from juloserver.julo.utils import (
    execute_after_transaction_safely,
    add_plus_62_mobile_phone,
)

from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation

from juloserver.rentee import services as rentee_service
from juloserver.moengage.tasks import update_moengage_for_payment_received_task

from juloserver.account.models import Account
from juloserver.julo.models import (
    PaymentMethod,
    PaybackTransaction,
)

from juloserver.integapiv1.constants import (
    FaspaySnapInquiryResponseCodeAndMessage,
)
from juloserver.julo.services2.payment_method import get_application_primary_phone


def faspay_snap_payment_inquiry_account(
    account: Account,
    payment_method: PaymentMethod,
    faspay_bill: dict,
) -> Tuple[dict, int]:
    """
    Get inquiry faspay snap account
    """
    account_payment = account.get_oldest_unpaid_account_payment()
    payment_deposit = rentee_service.get_payment_deposit_pending(account, latest=True)
    if not account_payment and not payment_deposit:
        faspay_bill['responseCode'] = FaspaySnapInquiryResponseCodeAndMessage.BILL_PAID.code
        faspay_bill['responseMessage'] = FaspaySnapInquiryResponseCodeAndMessage.BILL_PAID.message
        return faspay_bill, 0

    due_amount = payment_deposit.due_amount if payment_deposit else account_payment.due_amount

    if not payment_deposit and payment_method.payment_method_code in (
            settings.FASPAY_PREFIX_ALFAMART,
            settings.FASPAY_PREFIX_INDOMARET,
    ):
        total_due = account.get_total_outstanding_due_amount()
        due_amount = total_due if total_due else (account_payment.due_amount or 0)

    application = account.application_set.last()
    phone_number = get_application_primary_phone(application)
    faspay_bill['virtualAccountData']['virtualAccountName'] = application.fullname
    faspay_bill['virtualAccountData']['virtualAccountEmail'] = application.email
    faspay_bill['virtualAccountData']['virtualAccountPhone'] = add_plus_62_mobile_phone(
        phone_number
    )
    faspay_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(due_amount, '00')
    return faspay_bill, due_amount


def faspay_payment_inquiry_account(account, payment_method):
    """
    """
    account_payment = account.get_oldest_unpaid_account_payment()
    payment_deposit = rentee_service.get_payment_deposit_pending(account, latest=True)
    if not account_payment and not payment_deposit:
        data = {
            'response': 'Payment Notification',
            'response_code': '01',
            'response_desc': 'Payment not found'
        }
        return data

    due_amount = payment_deposit.due_amount if payment_deposit else account_payment.due_amount

    if not payment_deposit and payment_method.payment_method_code in (
            settings.FASPAY_PREFIX_ALFAMART,
            settings.FASPAY_PREFIX_INDOMARET,
    ):
        total_due = account.get_total_outstanding_due_amount()
        due_amount = total_due if total_due else (account_payment.due_amount or 0)

    virtual_account = int(payment_method.virtual_account)
    customer_name = account.application_set.last().fullname
    data = {
        'response': 'VA Static Response',
        'va_number': virtual_account,
        'amount': due_amount,
        'cust_name': customer_name,
        'response_code': '00'
    }
    return data


def faspay_payment_process_account(payback_trx, data, note):

    transaction_date = datetime.strptime(data['payment_date'], '%Y-%m-%d %H:%M:%S')

    with transaction.atomic():
        payback_trx = PaybackTransaction.objects.select_for_update().get(pk=payback_trx.id)
        if payback_trx.is_processed:
            return False
        payback_trx.update_safely(
            status_code=data['payment_status_code'],
            status_desc=data['payment_status_desc'],
            transaction_date=transaction_date)

        account_payment = payback_trx.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_trx, account_payment, payback_trx.transaction_date)
        process_j1_waiver_before_payment(account_payment, payback_trx.amount, transaction_date)
        payment_processed = process_rentee_deposit_trx(payback_trx)
        if not payment_processed:
            payment_processed = process_repayment_trx(payback_trx, note=note)
    if payment_processed:
        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(payment_processed.id)
        )
        return True
    return False


def faspay_snap_payment_process_account(
    payback_transaction: PaybackTransaction, data: Dict, note: str
) -> None:

    transaction_date = datetime.strptime(
        data.get('trxDateTime', data.get('transactionDate')), "%Y-%m-%dT%H:%M:%S%z"
    )

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(
            pk=payback_transaction.id
        )
        if payback_transaction.is_processed:
            return
        payback_transaction.update_safely(
            amount=float(data['paidAmount']['value']),
            transaction_date=transaction_date,
            transaction_id=data.get('referenceNo', None),
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
