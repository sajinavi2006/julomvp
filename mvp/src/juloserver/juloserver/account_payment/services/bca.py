from builtins import str
import logging
from babel.dates import format_date
from django.utils import timezone
from dateutil.parser import parse
from django.db import transaction

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.account_payment.services.payment_flow import process_rentee_deposit_trx
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.monitors.notifications import notify_payment_failure_with_severity_alert

from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.refinancing.services import j1_refinancing_activation

from juloserver.rentee import services as rentee_service
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.monitors.services import get_channel_name_slack_for_payment_problem
from datetime import datetime

from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


def get_bca_account_payment_bill(account, payment_method, data, bca_bill):
    from juloserver.integapiv1.services import generate_description

    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        inquiry_status = '01'
        inquiry_reason = generate_description('transaksi tidak ditemukan',
                                              'customer has no transaction')
        bca_bill['InquiryStatus'] = inquiry_status
        bca_bill['InquiryReason'] = inquiry_reason
        return bca_bill

    # get or create payback transaction object
    payback_transaction, _ = PaybackTransaction.objects.get_or_create(
        transaction_id=data.get('RequestID'),
        is_processed=False,
        virtual_account=payment_method.virtual_account,
        customer=account.customer,
        payment_method=payment_method,
        payback_service='bca',
        account=account
    )
    # to fill updated amount of bill
    payback_transaction.amount = account_payment.due_amount
    payback_transaction.save(update_fields=['amount'])

    inquiry_status = '00'
    inquiry_reason = generate_description('sukses', 'success')
    today = timezone.localtime(timezone.now()).date()
    free_text = generate_description(
        'Pembayaran Pinjaman JULO bulan %s' % format_date(today, "MMM yyyy", locale='id'),
        'JULO loan payment for %s' % format_date(today, "MMM yyyy", locale='en')
    )
    bca_bill['InquiryStatus'] = inquiry_status
    bca_bill['InquiryReason'] = inquiry_reason
    bca_bill['CustomerName'] = account.application_set.last().fullname
    bca_bill['TotalAmount'] = '{}.{}'.format(account_payment.due_amount, '00')
    bca_bill['FreeTexts'] = [free_text]

    return bca_bill


def bca_process_account_payment(payment_method, payback_trx, data):
    account = payback_trx.account
    payment_deposit = rentee_service.get_payment_deposit_pending(account, latest=True)
    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment and not payment_deposit:
        logger.debug({
            'action': bca_process_account_payment,
            'status': 'failed',
            'virtual_account': payment_method.virtual_account,
            'account_id': account.id,
            'message': 'customer has no unpaid account payment'
        })
        raise JuloException('tidak ada transaksi, no transaction')

    paid_amount = float(data.get('PaidAmount')) if float(data.get('PaidAmount')) else float(
        data.get('paidAmount')['value'])
    paid_date = None
    if 'trxDateTime' in data:
        paid_date = datetime.strptime(data['trxDateTime'], "%Y-%m-%dT%H:%M:%S%z")
    elif 'TransactionDate' in data or 'transactionDate' in data:
        paid_date_str = data.get('TransactionDate', data.get('transactionDate'))
        paid_date = parse(paid_date_str, dayfirst=True) if paid_date_str else None
    note = 'payment with va {} {} amount {}'.format(payment_method.virtual_account,
                                                    payment_method.payment_method_name,
                                                    paid_amount)
    try:
        with transaction.atomic():
            payback_transaction = PaybackTransaction.objects.select_for_update().get(
                pk=payback_trx.id)
            if payback_transaction.is_processed:
                return False
            payback_transaction.update_safely(amount=paid_amount, transaction_date=paid_date)

            if payment_deposit:
                process_rentee_deposit_trx(payback_transaction)
            else:
                j1_refinancing_activation(
                    payback_transaction, account_payment, payback_transaction.transaction_date)
                process_j1_waiver_before_payment(account_payment, paid_amount, paid_date)

                account_trx = process_repayment_trx(payback_transaction, note=note)

        if account_trx:
            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
            )

    except Exception as e:
        error_message = 'payment with va {} {} amount {} account_payment id {} failed due to {}' \
            .format(payment_method.virtual_account,
                    payment_method.payment_method_name,
                    paid_amount,
                    account_payment.id,
                    str(e))
        channel_name = get_channel_name_slack_for_payment_problem()
        notify_payment_failure_with_severity_alert(
            error_message, "#FF0000", channel_name
        )
        raise


def get_bca_rentee_deposit_bill(account, payment_method, data, bca_bill):
    from juloserver.integapiv1.services import generate_description

    payment_deposit = rentee_service.get_payment_deposit_pending(account, latest=True)
    if not payment_deposit:
        return None

    # get or create payback transaction object
    payback_transaction, _ = PaybackTransaction.objects.get_or_create(
        transaction_id=data.get('RequestID'),
        is_processed=False,
        virtual_account=payment_method.virtual_account,
        customer=account.customer,
        payment_method=payment_method,
        payback_service='bca',
        account=account
    )
    # to fill updated amount of bill
    payback_transaction.amount = payment_deposit.due_amount
    payback_transaction.save(update_fields=['amount'])

    inquiry_status = '00'
    inquiry_reason = generate_description('sukses', 'success')
    today = timezone.localtime(timezone.now()).date()
    free_text = generate_description(
        'Pembayaran Pinjaman JULO bulan %s' % format_date(today, "MMM yyyy", locale='id'),
        'JULO loan payment for %s' % format_date(today, "MMM yyyy", locale='en')
    )
    bca_bill['InquiryStatus'] = inquiry_status
    bca_bill['InquiryReason'] = inquiry_reason
    bca_bill['CustomerName'] = account.application_set.last().fullname
    bca_bill['TotalAmount'] = '{}.{}'.format(payment_deposit.due_amount, '00')
    bca_bill['FreeTexts'] = [free_text]

    return bca_bill


def get_snap_bca_rentee_deposit_bill(account, payment_method, data, bca_bill):
    payment_deposit = rentee_service.get_payment_deposit_pending(account, latest=True)
    if not payment_deposit:
        return None
    detokenized_payment_method = detokenize_sync_primary_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        required_fields=['virtual_account'],
    )
    # get or create payback transaction object
    payback_transaction, _ = PaybackTransaction.objects.get_or_create(
        transaction_id=data.get('inquiryRequestId'),
        is_processed=False,
        virtual_account=detokenized_payment_method.virtual_account,
        customer=account.customer,
        payment_method=payment_method,
        payback_service='bca',
        account=account
    )
    # to fill updated amount of bill
    payback_transaction.amount = payment_deposit.due_amount
    payback_transaction.save(update_fields=['amount'])

    detokenized_customer = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER,
        account.customer,
        account.customer.customer_xid,
        ['fullname'],
    )
    today = timezone.localtime(timezone.now()).date()
    bca_bill['virtualAccountData']['virtualAccountName'] = detokenized_customer.fullname
    bca_bill['virtualAccountData']['totalAmount']['value'] = '{}.{}'.format(
        payment_deposit.due_amount, '00'
    )
    bca_bill['virtualAccountData']['freeTexts'] = [{
        "english": 'JULO loan payment for {}'.format(
            format_date(today, "MMM yyyy", locale='en')
        ),
        "indonesia": 'Pembayaran Pinjaman JULO bulan {}'.format(
            format_date(today, "MMM yyyy", locale='id')
        ),
    }]

    return bca_bill
