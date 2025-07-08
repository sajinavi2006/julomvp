import logging
import datetime

from celery import task
from django.utils import timezone
from django.db import transaction

from juloserver.julo.models import PaybackTransaction
from juloserver.payback.constants import CimbVAResponseCodeConst
from juloserver.payback.client.cimb_va import get_cimb_snap_client
from juloserver.payback.services.cimb_va import process_cimb_repayment

LOGGER = logging.getLogger(__name__)

@task(queue='repayment_high')
def cimb_payment_status_process(payback_id):
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()
    if not payback_transaction:
        return
    elif payback_transaction.is_processed:
        return
    elif not payback_transaction.virtual_account:
        return

    # GET Status from CIMB Client
    va_number = payback_transaction.virtual_account
    inquiry_request_id = payback_transaction.transaction_id

    cimb_client = get_cimb_snap_client(payback_transaction.account)
    response, error_message = cimb_client.get_payment_status(va_number, inquiry_request_id)
    if error_message:
        return

    transaction_status = response["responseCode"]
    if transaction_status != CimbVAResponseCodeConst.PAYMENT_SUCCESS:
        return

    transaction_date = response["virtualAccountData"]["trxDateTime"]
    transaction_date_parsed = datetime.datetime.strptime(transaction_date, "%Y-%m-%dT%H:%M:%S%z")
    transaction_paid_amount = float(response["virtualAccountData"]["paidAmount"]["value"])

    LOGGER.info(
        {
            'action': 'cimb_payment_status_process',
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status,
        }
    )

    process_cimb_repayment(payback_transaction.id, transaction_date_parsed, transaction_paid_amount)

    return


@task(queue='repayment_high')
def cimb_payment_status_transaction():
    # CIMB API payment status is only available for transactions at most 2 days ago
    start_date = timezone.localtime(timezone.now() - datetime.timedelta(days=2))
    end_date = timezone.localtime(timezone.now() - datetime.timedelta(minutes=15))

    with transaction.atomic():
        account_payback_trx_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_date, end_date),
                transaction_id__isnull=False,
                payment_method__isnull=False,
                payback_service='cimb',
                account__isnull=False,
            )
            .values_list('id', flat=True)
        )

        for payback_id in account_payback_trx_ids:
            cimb_payment_status_process.delay(payback_id)

        return
