from __future__ import division
from builtins import str
from past.utils import old_div
import json
import logging
import pytz

from itertools import chain
from datetime import datetime, timedelta, time
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from .models import (MintosResponseLog,
                    MintosLoanListStatus,
                    SbLenderLoanLedgerBackup,
                    SbLenderLoanLedger,
                    SbLenderWithdrawBatch,
                    SbLenderAccount,
                    ExchangeRate,
                    SbMintosPaymentSendin,
                    SbMintosBuybackSendin,
                    MintosPaymentSendin,
                    MintosReport,
                    MintosQueueStatus)
from .constants import (LENDER_ACCOUNT_PARTNER,
                        LOAN_SENDIN_LOG_TYPE,
                        LOAN_REBUY_LOG_TYPE,
                        LOAN_SENDIN_STATUS,
                        LOAN_SENDIN_TYPES,
                        MINTOS_REQUEST_LIMIT)
from juloserver.julo.models import Loan, FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julocore.python2.utils import py2round

logger = logging.getLogger(__name__)


def round_down(n, decimals=0):
    import math

    multiplier = 10 ** decimals
    return old_div(math.floor(n * multiplier), multiplier)

def idr_to_eur(amount, exchange_rate=None, rounding='round'):
    if not exchange_rate:
        exchange_rate = ExchangeRate.objects.all().last()

    round_func = eval(rounding)
    return round_func(amount * exchange_rate.rate, 2)

def convert_all_to_uer(items, value_to_convert, exchange_rate=None):
    for item in items:
        for key in list(item.keys()):
            if key in value_to_convert:
                item[key] = idr_to_eur(item[key], exchange_rate, rounding='round_down')

    return items

def recalculate_rounding(subtotal, items):
    import functools
    difference = py2round(subtotal - functools.reduce(lambda a, b: a + b['principal_amount'], items, 0), 2)
    indexes = []
    for index, item in enumerate(items):
        indexes.append({
            'index': index,
            'remainder': int(str(item['principal_amount'])[-1])
        })
    indexes.sort(key=lambda element: -element['remainder'])
    iterator = 0
    while difference > 0:
        items[indexes[iterator]['index']]['principal_amount'] = py2round(items[indexes[iterator]['index']]['principal_amount'] + 0.01, 2)
        difference = py2round(difference - 0.01, 2)
        iterator = (iterator + 1) % len(indexes)

    return items


def mintos_response_logger(request_type, request, response, error_message, application=None):
    return_response = response.json() if hasattr(response , 'json') else None
    status = 'success' if response.status_code in [200, 201] else 'failed'
    application_xid = None
    if application:
        application_xid = application.application_xid

    logger.info({
        'action': 'mintos_response_logger - {}'.format(request_type),
        'response_status': response.status_code,
        'application_xid': application_xid,
        'error': error_message,
        'request': response.request.__dict__,
        'response': return_response,
        'status': status,
    })

    MintosResponseLog.objects.create(
        application_xid=application_xid,
        api_type=request_type,
        http_status_code=response.status_code,
        response=return_response,
        request=request,
        error_message=error_message,
        status=status,
    )

def insert_mintos_loan_list_status(response):
    if response and 'data' in response:
        response = response['data']
        logger.info({
            'action': 'insert_mintos_loan_list_status',
            'mintos_loan_id': response['loan']['mintos_id'],
            'application_xid': response['client']['id'],
            'response': response,
        })
        exchange_rate = ExchangeRate.objects.all().last()
        interest = mintos_interest_rate()
        mintos_send_ts = timezone.localtime(timezone.now())
        MintosLoanListStatus.objects.create(
            mintos_loan_id=response['loan']['mintos_id'],
            application_xid=response['client']['id'],
            mintos_send_in_ts=mintos_send_ts,
            status=response['loan']['status'],
            exchange_rate=exchange_rate,
            interest_rate_percent=float(interest)
        )

def update_mintos_loan_list_status(response):
    if response and 'data' in response:
        response = response['data']
        logger.info({
            'action': 'update_mintos_loan_list_status',
            'response': response,
        })
        for key, data in list(response.items()):
            MintosLoanListStatus.objects.filter(
                mintos_loan_id=data['id']).update(
                    status=data['status'],
                )

def get_mintos_loan_id(loan_id):
    mintos_loan_id = None
    if loan_id:
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan:
            logger.info({
                'action': 'get_mintos_loan_id',
                'loan_id': loan_id,
                'message': "couldn't find loan"
            })

        application_xid = loan.application.application_xid
        mintos_loan_list = MintosLoanListStatus.objects.get_or_none(
            application_xid=application_xid)

        if mintos_loan_list:
            mintos_loan_id = mintos_loan_list.mintos_loan_id

    return mintos_loan_id

def get_mintos_loans(lender_loan_ledgers, queue_type):
    loans_sendin = []
    for lender_loan_ledger in lender_loan_ledgers:
        loans_sendin.append(
            MintosQueueStatus(
                loan_id=lender_loan_ledger.loan_id,
                queue_type=queue_type,
            )
        )

    return loans_sendin

def get_mintos_loans_sendin():
    yesterday = timezone.localtime(timezone.now()) - timedelta(1)
    # v2
    lender_account = SbLenderAccount.objects.filter(
        lender_account_partner=LENDER_ACCOUNT_PARTNER)
    # last 24hours withdraw_batches
    lender_withdraw_batches = SbLenderWithdrawBatch.objects.filter(
        lender_account=lender_account, cdate__gte=yesterday.replace(tzinfo=pytz.UTC))
    lender_withdraw_batch_ids = lender_withdraw_batches.values_list('id', flat=True)

    response_log_application_xids = MintosResponseLog.objects.filter(
        api_type=LOAN_SENDIN_LOG_TYPE).values_list('application_xid', flat=True)

    lender_loan_ledgers = SbLenderLoanLedger.objects.filter(
        lender_withdraw_batch_id__in=lender_withdraw_batch_ids,
        loan_status=LOAN_SENDIN_STATUS,
        tag_type__in=LOAN_SENDIN_TYPES).exclude(
            application_xid__in=response_log_application_xids
        )
    return get_mintos_loans(lender_loan_ledgers, 'loan_sendin')

def get_mintos_payment_sendin():
    yesterday = datetime.combine(timezone.now().date(), time(0, 0)) + timedelta(1)

    # v2
    lender_withdraw_batches = SbLenderWithdrawBatch.objects.filter(
        lenderaccount__lender_acount_partner=LENDER_ACCOUNT_PARTNER
    )
    lender_withdraw_batch = lender_withdraw_batches.last()
    lender_withdraw_batch_ids = lender_withdraw_batches.values_list('id', flat=True)

    lender_loan_ledger_backups = SbLenderLoanLedgerBackup.objects.filter(
        lender_withdraw_batch_id__in=lender_withdraw_batch_ids,
        backup_ts__gte=yesterday)
    lender_loan_ledger_backup_application_xids = lender_loan_ledger_backups.values_list(
        'application_xid', flat=True)
    lender_loan_ledger_backup_osp_application_xids = []
    for lender_loan_ledger_backup in lender_loan_ledger_backups:
        append_dict = {}
        append_dict[lender_loan_ledger_backup.application_xid] = lender_loan_ledger_backup.osp
        lender_loan_ledger_backup_osp_application_xids.append(append_dict)

    lender_loan_ledgers = SbLenderLoanLedger.objects.filter(
        lender_withdraw_batch=lender_withdraw_batch).exclude(
            application_xid__in=lender_loan_ledger_backup_application_xids
        )
    return get_mintos_loans(lender_loan_ledgers, 'payment_sendin')

def get_mintos_payment_sendin2():
    today = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)

    ops_payments = MintosPaymentSendin.objects.filter(
        cdate__gte=today
    ).values_list('payment_id', flat=True)

    sb_payments = SbMintosPaymentSendin.objects.filter(
        cdate__gte=today.replace(tzinfo=pytz.UTC)).exclude(
            payment_id__in=ops_payments
        )

    queue_type = 'payment_sendin'
    payment_sendin = []
    for sb_payment in sb_payments:
        data_queue = dict(
            loan_id=sb_payment.loan_id,
            payment_number=sb_payment.payment_schedule_number,
            queue_type=queue_type,
        )
        if data_queue not in payment_sendin:
            payment_sendin.append(data_queue)

    return [MintosQueueStatus(**val) for val in payment_sendin]

def get_mintos_rebuy_loans():
    today = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)

    exlucude_application_xids = MintosResponseLog.objects.filter(
        api_type__contains=LOAN_REBUY_LOG_TYPE
    ).values_list(
        'application_xid', flat=True)

    all_rebuy_loan = SbMintosBuybackSendin.objects.filter(
        cdate__gte=today.replace(tzinfo=pytz.UTC)
    ).exclude(
        application_xid__in=exlucude_application_xids
    ).values_list('loan_id', flat=True)

    queue_type = 'rebuy_loan'
    rebuy_loan = []
    for loan_id in all_rebuy_loan:
        rebuy_loan.append(
            MintosQueueStatus(
                loan_id=loan_id,
                queue_type=queue_type,
            )
        )
    return rebuy_loan


def mintos_interest_rate():
    feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.MINTOS_INTEREST_RATE).last()

    mintos_interest_rate = feature_setting.parameters['interest_rate_percent'] or 15

    return mintos_interest_rate

def upsert_mintos_report(filename, date, data):
    mintos_report = MintosReport.objects.get_or_none(filename=filename)
    if mintos_report:
        return {
            "id": mintos_report.id,
            "exists": True
        }

    mintos_report = MintosReport.objects.create(
        filename=filename,
        email_date=date
    )
    return {
        "id": mintos_report.id,
        "exists": False
    }


def get_mintos_queue_data():
    limit = MINTOS_REQUEST_LIMIT
    mintos_queue = MintosQueueStatus.objects.filter(
        queue_status=False)

    if not mintos_queue:
        with transaction.atomic():
            # save per categories for avoid race condition when send data to mintos
            # rules is 1. loan send_in, 2. payment, 3. buyback

            mintos_loans_sendin = get_mintos_loans_sendin()
            if mintos_loans_sendin:
                MintosQueueStatus.objects.bulk_create(mintos_loans_sendin)

            mintos_payments_sendin = get_mintos_payment_sendin2()
            if mintos_payments_sendin:
                MintosQueueStatus.objects.bulk_create(mintos_payments_sendin)

            mintos_rebuy_loans = get_mintos_rebuy_loans()
            if mintos_rebuy_loans:
                MintosQueueStatus.objects.bulk_create(mintos_rebuy_loans)

            mintos_all_data = list(chain(mintos_loans_sendin,
                mintos_payments_sendin, mintos_rebuy_loans))

        if mintos_all_data:
            # requery cause bulk not return object
            mintos_queue = MintosQueueStatus.objects.filter(
                queue_status=False
            )
    # send loan_sendin first
    fixed_mintos_queue = mintos_queue.filter(queue_type='loan_sendin')

    if not fixed_mintos_queue:
        fixed_mintos_queue = mintos_queue.filter(queue_type='payment_sendin')

    if not fixed_mintos_queue:
        fixed_mintos_queue = mintos_queue.filter(queue_type='rebuy_loan')

    return fixed_mintos_queue.order_by('payment_number', 'cdate').values('id', 'loan_id', 'payment_number', 'queue_type')[:limit]