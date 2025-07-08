from builtins import str
import logging
import json

from rest_framework.reverse import reverse
from celery import task
from django.db import transaction, models
from django.utils import timezone
from django.conf import settings
from datetime import date
from dateutil.relativedelta import relativedelta
from .models import (CustomerCreditLimit,
                     Statement,
                     TransactionOne,
                     DisbursementSummary,
                     StatementEvent)
from .constants import (PaylaterConst,
                        StatementEventConst)
from .services import get_paylater_credit_score, update_late_fee_amount
from .utils import get_interest_rate

from juloserver.julo.utils import (
    display_rupiah,
    chunk_array,
    format_e164_indo_phone_number)

from juloserver.julo.models import (Partner,
                                    Application,
                                    Customer,
                                    PaymentMethod
                                    )
from django.db.models import Q
from juloserver.julo.clients import get_bukalapak_client
from juloserver.julo.clients import get_julo_whatsapp_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.clients import get_julo_sms_client
from .services import StatementEventServices
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.services2.sms import create_sms_history

PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')

logger = logging.getLogger(__name__)

@task(name='call_bukalapak_endpoint')
def call_bukalapak_endpoint(app_id):
    app = Application.objects.get_or_none(pk=app_id)
    credit_score = get_paylater_credit_score(app_id)
    line = app.customer.customercreditlimit

    partner = Partner.objects.get(name=PaylaterConst.PARTNER_NAME)
    line_sub = line.accountcreditlimit_set.filter(partner=partner).last()

    interest_rate = get_interest_rate(line_sub.id)
    data = {
        "customer_xid": line.customer.customer_xid,
        "score": {
            "score": credit_score.score,
            "credit_limit": line.customer_credit_limit,
            "interest": "%s%%" % (interest_rate*100)
        }
    }
    logger.info({
        'task': 'call_bukalapak_endpoint(request)',
        'data': data,
    })

    dummy_url = 'api/paylater/v1/dummy-callback'
    dummy = True if dummy_url in line_sub.callback_url else False

    bukalapak_client = get_bukalapak_client(dummy)
    response = bukalapak_client.approve_paylater(line_sub.callback_url, data)
    logger.info({
        'task': 'call_bukalapak_endpoint(response)',
        'response': response.content,
        'status_code': response.status_code
    })
    dict_response = json.loads(response.content)
    dict_response["status"] = response.status_code
    line_sub.callback_response = dict_response
    line_sub.save(update_fields=['callback_response'])


@task(name='update_statement_late_fee')
def update_statement_late_fee():
    """
    Goes through every unpaid statement by comparing its due date and
    today's date, apply late fee as the rule
    """
    unpaid_statements = Statement.objects.filter(statement_status__lt=PaymentStatusCodes.PAID_ON_TIME)
    today = timezone.localtime(timezone.now()).date()
    # today = date(2019, 9, 01)
    if date(2019, 9, 1) <= today <= date(2019, 9, 15):
        unpaid_statements = unpaid_statements.exclude(statement_due_date__in=[date(2019, 5, 28), date(2019, 6, 28), date(2019, 7, 28)])
    for unpaid_statement in unpaid_statements:

        # double check to prevent race condition
        unpaid_statement.refresh_from_db()
        if unpaid_statement.statement_status.status_code in PaymentStatusCodes.paylater_paid_status_codes():
            continue

        update_late_fee_amount(unpaid_statement.id)


@task(name="count_disbursemet_summary_paylter")
def count_disbursemet_summary_paylter():
    partner = Partner.objects.get(name=PaylaterConst.PARTNER_NAME)
    today = timezone.localtime(timezone.now()).date()
    yesterday = today - relativedelta(days=1)
    transactions = TransactionOne.objects.filter(cdate__gte=yesterday,
                                                 cdate__lt=today,
                                                 transaction_type="debit",
                                                 account_credit_limit__partner=partner)
    if transactions:
        transactions_ids = transactions.values_list('id', flat=True)
        transactions_amount = transactions.aggregate(models.Sum('disbursement_amount'))
        transactions_debt = 0 if not transactions_amount['disbursement_amount__sum'] else transactions_amount[
            'disbursement_amount__sum']
        summary = DisbursementSummary.objects.filter(transaction_date=yesterday, partner=partner).first()

        disburse_xid = "{}{}{}".format(yesterday, partner.id, str(int(transactions_debt))[-3:])
        disburse_xid = disburse_xid.replace("-", "")

        if not summary:
            DisbursementSummary.objects.create(
                transaction_date=yesterday,
                transaction_count=len(transactions_ids),
                transaction_ids=list(transactions_ids),
                transaction_amount=transactions_debt,
                disburse_xid=int(disburse_xid),
                partner=partner
            )
        else:
            summary.transaction_date = yesterday
            summary.transaction_count = len(transactions_ids)
            summary.transaction_ids = list(transactions_ids)
            summary.transaction_amount = transactions_debt
            summary.partner = partner
            summary.save()


# Commented because change from whatsapp to SMS detail in this card AM-540
# @task(name='send_whatsapp_on_bukalapak')
# def send_whatsapp_on_bukalapak(statement_id):
#     statement = Statement.objects.get_or_none(pk=statement_id)
#     if statement.statement_status.status_code in PaymentStatusCodes.paylater_paid_status_codes():
#         return
#     wa_client = get_julo_whatsapp_client()
#     wa_client.send_bukalapak_wa_payment_reminder(statement)

@task(queue='collection_low')
def send_sms_replace_wa_for_bukalapak(statement_ids):
    statements = Statement.objects.filter(pk__in=statement_ids)\
        .exclude(statement_status__status_code__in=PaymentStatusCodes.paylater_paid_status_codes())
    today = timezone.localtime(timezone.now()).date()
    today_day = today.day
    template_code = 'sms_bukalapak_payment_reminder_'+str(today_day)
    for statement in statements:
        customer = statement.customer_credit_limit.customer
        get_julo_sms = get_julo_sms_client()
        txt_msg, response = get_julo_sms.sms_payment_reminder_replaced_wa_for_bukalapak(statement,
                                                                                        template_code,
                                                                                        customer)
        sms = create_sms_history(response=response,
                                 customer=customer,
                                 message_content=txt_msg,
                                 template_code=template_code,
                                 to_mobile_phone=customer.phone,
                                 phone_number_type='customer_phone'
                                 )

        logger.info({
            'status': 'sms_created',
            'sms_history_id': sms.id,
            'message_id': sms.message_id
        })


@task(queue='collection_low')
def send_all_sms_on_bukalapak():
    today_now = timezone.localtime(timezone.now())
    today = today_now.day
    today_date = today_now.date()
    today_month = today_now.month
    today_year = today_now.year
    # commented this because if the WA can back so just need to uncomment this
    # wa_send_dates =  [4, 6, 8, 20, 25, 28, 29, 31]
    sms_send_dates =  [4, 20, 25]
    statement_ids = []
    if today in sms_send_dates:
        if today == 25:
            due_date = today_date + relativedelta(days=3)
            statement_ids = list(Statement.objects.filter(
                statement_status__status_code=PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                statement_due_date=due_date).values_list('id',flat=True))
        # elif today == 28:
        #     due_date = today_date
        #     statement_ids = list(Statement.objects.filter(
        #         statement_status__status_code=PaymentStatusCodes.PAYMENT_DUE_TODAY,
        #         statement_due_date=due_date).values_list('id', flat=True))
        elif today in [4, 20]:
            first = today_date.replace(day=1)
            lastMonth = first - relativedelta(days=1)
            due_date = date(int(lastMonth.strftime("%Y")), int(lastMonth.strftime("%m")), 28)
            statement_ids = list(Statement.objects.filter(
                statement_status__status_code__gte=PaymentStatusCodes.PAYMENT_1DPD,
                statement_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME)
                                 .filter(statement_due_date=due_date).values_list('id', flat=True))
        # All API keys are set with 30 API request per second throughput restriction by default (nexmo)
        # because of that so send sms should send by 30 request per seconds
        statement_ids = chunk_array(statement_ids, 30)
        for index, chunk_statement_ids in enumerate(statement_ids):
            # use index for delay per chunk for prevent different worker work together
            # for prevent long response period from nexmo
            delay = index*2
            send_sms_replace_wa_for_bukalapak.apply_async((chunk_statement_ids,), countdown=delay)
            logger.info({
                'action': 'send_sms_replace_wa_for_bukalapak',
                'delay': index,
                'total_chunk': len(statement_ids)
            })


@task(queue="collection_high")
def statement_reminder_paylater():
    today_now = timezone.localtime(timezone.now())
    today = today_now.day
    today_date = today_now.date()
    sms_send_dates = [27, 28, 30, 2, 7, 10]
    if today in sms_send_dates:
        if today == 27:
            due_date = today_date + relativedelta(days=1)
            statement_ids = list(Statement.objects.filter(
                statement_status__status_code=PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                statement_due_date=due_date).values_list('id',flat=True))
        elif today in [30, 2, 7, 10]:
            if today == 30:
                due_date = today_date - relativedelta(days=2)
            else:
                first = today_date.replace(day=1)
                lastMonth = first - relativedelta(days=1)
                due_date = date(int(lastMonth.strftime("%Y")), int(lastMonth.strftime("%m")), 28)
            statement_ids = list(Statement.objects.filter(
            statement_status__status_code__gte=PaymentStatusCodes.PAYMENT_1DPD,
            statement_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME).filter(
            statement_due_date=due_date).values_list('id', flat=True))
        else:
            due_date = today_date
            statement_ids = list(Statement.objects.filter(
                statement_status__status_code=PaymentStatusCodes.PAYMENT_DUE_TODAY,
                statement_due_date=due_date).values_list('id', flat=True))
        for statement_id in statement_ids:
            sms_statement_reminder_paylater.delay(statement_id)


@task(queue="collection_high")
def sms_statement_reminder_paylater(statement_id):
    statement = Statement.objects.get_or_none(pk=statement_id)

    if statement.statement_status.status_code in PaymentStatusCodes.paylater_paid_status_codes():
        return

    today = timezone.localtime(timezone.now()).date()
    wa_collection = "081931100452" # old number "087886904744"
    tel_number =  '02150718800'
    get_julo_sms = get_julo_sms_client()
    customer = statement.customer_credit_limit.customer

    fullname = customer.fullname
    if len(fullname) > 12:
        split_name = str(fullname).split(" ")
        fullname = split_name[0]
    due_amount = display_rupiah(statement.statement_due_amount)
    today_day = today.day
    template_name = 'sms_bukalapak_payment_reminder_' + str(today_day)
    if today_day in [30, 2]:
        sms_template = ("Yth {} tagihan BayarNanti Anda {} telah jatuh tempo. "
                        "Segera bayar utk hindari denda. "
                        "Cara bayar klik bl.id/BayarNanti / WA {}").format(fullname,
                                                                      due_amount,
                                                                      wa_collection)
    elif today_day in [7, 10]:
        sms_template = ("Yth {}, BayarNanti Anda telah menunggak {}. "
                        "Ditunggu pembayarannya  hari ini. "
                        "Cara bayar klik bl.id/BayarNanti / WA {}").format(fullname,
                                                                      due_amount,
                                                                      wa_collection)
    elif today_day == 27:
        sms_template = ("Yth {} tagihan BayarNanti Anda {} jth tempo 28/{}. "
                        "Bayar skrg yuk sebelum lupa! "
                        "Cara bayar klik bl.id/BayarNanti / WA {}").format(fullname,
                                                                      due_amount,
                                                                      today.month,
                                                                      wa_collection)

    elif today_day == 28:
        sms_template = ("Yth {} tagihan BayarNanti Anda {} jth tempo 28/{}. "
                        "Ditunggu pembayarannya hari ini :) "
                        "Klik bl.id/BayarNanti / Tel-{}").format(fullname,
                                                                      due_amount,
                                                                      today.month,
                                                                      tel_number)

    txt_msg, response = get_julo_sms.sms_custom_paylater_reminder(customer.phone, sms_template)
    sms = create_sms_history(response=response,
                       customer=customer,
                       message_content=txt_msg,
                       template_code=template_name,
                       to_mobile_phone=customer.phone,
                       phone_number_type='customer_phone'
                       )

    logger.info({
        'status': 'sms_created',
        'sms_history_id': sms.id,
        'message_id': sms.message_id
    })


@task(queue="collection_normal")
def reset_collection_called_status_for_unpaid_statement():
    statements = Statement.objects.filter(is_collection_called=True)

    for statement in statements:
        statement.update_safely(is_collection_called=False)


@task(name='statement_reverse_waive_late_fee_daily')
def statement_reverse_waive_late_fee_daily():
    statement_event_service = StatementEventServices()
    today = timezone.localtime(timezone.now()).date()
    note = 'reverse waive late fee daily by system.'
    statement_events = StatementEvent.objects.filter(event_type=StatementEventConst.WAIVE_LATE_FEE,
                                                     event_date=today,
                                                     can_reverse=True)

    for statement_event in statement_events:
        if statement_event.statement.statement_due_amount > 0:
            statement_event_service.reverse_waive_late_fee(statement_event, note)

@task(queue='collection_high')
def sms_activation_paylater(customer_id):
    get_julo_sms = get_julo_sms_client()
    customer = Customer.objects.get_or_none(pk=customer_id)

    if customer:
        url = reverse('paylater:approval', kwargs={'customer_xid': customer.customer_xid})
        link = shorten_url(PROJECT_URL + url)

        phone_number = customer.phone
        fullname = customer.fullname
        if len(fullname) > 12:
            split_name = str(fullname).split(" ")
            fullname = split_name[0]

        sms_template = ("Terima kasih Bpk/Ibu {}, Silahkan konfirmasi aktivasi fitur "
                        "Bukalapak BayarNanti Anda dengan klik link berikut {}").format(fullname, link)

        txt_msg, response = get_julo_sms.sms_custom_paylater_reminder(phone_number, sms_template)

        sms = create_sms_history(response=response,
                                 customer=customer,
                                 message_id=response['message-id'],
                                 message_content=txt_msg,
                                 to_mobile_phone=customer.phone,
                                 phone_number_type='customer_phone')

        logger.info({
            'status': 'sms_paylayter_activation_sent',
            'sms_history_id': sms.id,
            'customer': customer.id,
            'message_id': sms.message_id
        })

@task(name='statement_waive_late_fee_september_campaign_prep')
def statement_waive_late_fee_september_campaign_prep():
    if timezone.now().year == 2019:
        statement_event_service = StatementEventServices()
        statement_group_1 = Statement.objects.filter(Q(statement_due_date=date(2019, 5, 28)) |
                                                     Q(statement_due_date=date(2019, 6, 28)))
        statement_group_2 = Statement.objects.filter(statement_due_date=date(2019, 7, 28))
        for statement in statement_group_1:
            for event_type in [StatementEventConst.WAIVE_LATE_FEE_GROUP_1, StatementEventConst.WAIVE_SUBSCRIPTION_FEE]:
                if event_type == StatementEventConst.WAIVE_LATE_FEE_GROUP_1:
                    waive_data = {
                        'waive_late_fee_amount_parsed': statement.statement_late_fee_amount,
                        'note': 'created from background task BLBN September Campaign prep',
                        'event_type': event_type
                    }
                    agent = None
                    status = statement_event_service.process_waive_late_fee(statement, waive_data, agent)
                else:
                    waive_data = {
                        'interest_amount': statement.statement_interest_amount,
                        'note': 'created from background task BLBN September Campaign prep',
                        'event_type': event_type
                    }
                    status = statement_event_service.process_waive_interest_fee(statement, waive_data)
        for statement in statement_group_2:
            waive_data = {
                'waive_late_fee_amount_parsed': statement.statement_late_fee_amount,
                'note': 'created from background task BLBN September Campaign prep',
                'event_type': StatementEventConst.WAIVE_LATE_FEE_GROUP_2
            }
            agent = None
            status = statement_event_service.process_waive_late_fee(statement, waive_data, agent)

@task(name='statement_reverse_waive_late_fee_september_campaign_prep')
def statement_reverse_waive_late_fee_september_campaign_prep():
    if timezone.now().year == 2019:
        statement_event_service = StatementEventServices()
        statement_events = StatementEvent.objects.filter(event_type__in=[StatementEventConst.WAIVE_LATE_FEE_GROUP_1,
                                                                         StatementEventConst.WAIVE_LATE_FEE_GROUP_2,
                                                                         StatementEventConst.WAIVE_SUBSCRIPTION_FEE],
                                                         can_reverse=True)
        note = 'reverse waive late fee after the contest on 16th September'
        for statement_event in statement_events:
            if statement_event.statement.statement_due_amount > 0 and \
                    statement_event.statement.statement_status.status_code < PaymentStatusCodes.PAID_ON_TIME:
                if statement_event.event_type in [StatementEventConst.WAIVE_LATE_FEE_GROUP_1,
                                                  StatementEventConst.WAIVE_LATE_FEE_GROUP_2]:
                    statement_event_service.reverse_waive_late_fee(statement_event, note)
                else:
                    statement_event_service.reverse_waive_interest_fee(statement_event, note)


@task(queue='collection_low')
def send_sms_bukalapak_notify_va_created(statement_id):
    statement = Statement.objects.filter(pk=statement_id).last()

    if statement is None:
        logger.info({
            'status': 'sms_not_send',
            'error': 'statement not found',
            'method': 'send_sms_bukalapak_notify_va_created'
        })

        return

    customer_credit_limit = statement.customer_credit_limit
    due_amount = statement.statement_due_amount
    today = timezone.localtime(timezone.now()).date()
    dpd = (today - statement.statement_due_date).days
    customer = customer_credit_limit.customer
    template_code = 'sms_bukalapak_notify_va_created'
    payment_method = PaymentMethod.objects.filter(
        customer_credit_limit=customer_credit_limit
    ).last()

    if not payment_method:
        return

    get_julo_sms = get_julo_sms_client()
    txt_msg, response = get_julo_sms.sms_notify_bukalapak_customer_va_generated(
        template_code,
        customer,
        payment_method.virtual_account,
        dpd,
        due_amount
    )

    sms = create_sms_history(
        response=response,
        customer=customer,
        message_content=txt_msg,
        template_code=template_code,
        to_mobile_phone=format_e164_indo_phone_number(customer.phone),
        phone_number_type='customer_phone'
    )

    logger.info({
        'status': 'sms_created',
        'sms_history_id': sms.id,
        'message_id': sms.message_id
    })
