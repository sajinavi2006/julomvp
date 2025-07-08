import logging
from datetime import date

from celery import task

from django.db import transaction

from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.clients import get_julo_va_bca_client, get_julo_bca_snap_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import PaybackTransaction, FeatureSetting
from juloserver.monitors.notifications import notify_failure
from django.utils import timezone
from dateutil.parser import parse

from ..services import bca_process_payment
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource

LOGGER = logging.getLogger(__name__)


@task(queue='repayment_high', name='bca_inquiry_subtask')
def bca_inquiry_subtask(payback_id):
    """separate parent task"""
    is_snap = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.BCA_INQUIRY_SNAP,
        is_active=True
    )

    if is_snap:
        return

    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if not payback_transaction:
        return
    elif payback_transaction.is_processed:
        return

    bca_client = get_julo_va_bca_client()
    transaction_status_list = bca_client.inquiry_status(payback_transaction.transaction_id)

    if not transaction_status_list:
        return

    LOGGER.info({
        'action':'bca_inquiry_subtask',
        'transaction_id': payback_transaction.transaction_id,
        'response': transaction_status_list
    })

    transaction_status = transaction_status_list[0]

    if transaction_status.get('PaymentFlagStatus') != 'Success':
        return

    #standardize datetime format
    trans_date = transaction_status['TransactionDate']
    transaction_status['TransactionDate'] = parse(trans_date).strftime('%d/%m/%Y %H:%M:%S')

    bca_process_payment(
        payback_transaction.payment_method,
        payback_transaction,
        transaction_status)


@task(name='bca_snap_inquiry_subtask', queue='bank_inquiry')
def bca_snap_inquiry_subtask(payback_id):
    is_snap = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.BCA_INQUIRY_SNAP,
        is_active=True
    )

    if not is_snap:
        return

    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if not payback_transaction:
        return
    elif payback_transaction.is_processed:
        return

    bca_client = get_julo_bca_snap_client(
        customer_id=payback_transaction.customer.id if payback_transaction.customer else None,
        loan_id=payback_transaction.loan.id if payback_transaction.loan else None,
        payback_transaction_id=payback_transaction.id,
    )
    detokenized_payback_transaction = detokenize_sync_primary_object_model(
        PiiSource.PAYBACK_TRANSACTION,
        payback_transaction,
        payback_transaction.customer.customer_xid,
        ['virtual_account'],
    )
    transaction_status_list, error = bca_client.inquiry_status_snap(
        detokenized_payback_transaction.virtual_account, payback_transaction.transaction_id
    )

    if error:
        return

    LOGGER.info(
        {
            'action': 'bca_inquiry_subtask',
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status_list,
        }
    )

    transaction_status = transaction_status_list

    if transaction_status.get('PaymentFlagStatus') != '00':
        return

    # standardize datetime format
    trans_date = transaction_status['transactionDate']
    transaction_status['transactionDate'] = parse(trans_date).strftime('%d/%m/%Y %H:%M:%S')

    bca_process_payment(payback_transaction.payment_method, payback_transaction, transaction_status)


@task(queue='bank_inquiry', name='bca_inquiry_transaction')
def bca_inquiry_transaction():
    """update bca transaction manually"""
    start_dt = timezone.localtime(timezone.now()).date()
    end_dt = timezone.localtime(timezone.now())

    with transaction.atomic():
        payback_transaction_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt,end_dt),
                transaction_id__isnull=False,
                payment_method__isnull=False,
                payback_service='bca',
                payment__isnull=False,
                account__isnull=True,
                payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            )
            .values_list('id', flat=True)
        )

        account_payback_trx_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt,end_dt),
                transaction_id__isnull=False,
                payment_method__isnull=False,
                payback_service='bca',
                account__isnull=False,
            )
            .values_list('id', flat=True)
        )

        for payback_id in list(payback_transaction_ids) + list(account_payback_trx_ids):
            bca_inquiry_subtask.delay(payback_id)


@task(queue='bank_inquiry')
def bca_snap_inquiry_transaction():
    """update bca transaction manually"""
    start_dt = timezone.localtime(timezone.now()).date()
    end_dt = timezone.localtime(timezone.now())

    with transaction.atomic():
        account_payback_trx_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt, end_dt),
                transaction_id__isnull=False,
                payment_method__isnull=False,
                payback_service='bca',
                account__isnull=False,
            )
            .values_list('id', flat=True)
        )

        for payback_id in account_payback_trx_ids:
            bca_snap_inquiry_subtask.delay(payback_id)
