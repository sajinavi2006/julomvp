from __future__ import absolute_import
from __future__ import division

from builtins import str
from past.utils import old_div
import logging
import requests
import pytz

from celery import task
from bs4 import BeautifulSoup
from django.utils import timezone
from itertools import chain
from datetime import timedelta, date
from dateutil.parser import parse
from juloserver.julocore.python2.utils import py2round

from .models import (ExchangeRate,
                    MintosLoanListStatus,
                    SbMintosPaymentList,
                    SbMintosPaymentSendin,
                    SbMintosBuybackSendin,
                    MintosPaymentSendin,
                    MintosQueueStatus,
                    MintosReportDetail)
from .services import (get_mintos_loan_id,
                        update_mintos_loan_list_status,
                        insert_mintos_loan_list_status,
                        get_mintos_loans_sendin,
                        get_mintos_payment_sendin,
                        get_mintos_rebuy_loans,
                        get_mintos_payment_sendin2,
                        idr_to_eur,
                        get_mintos_queue_data)
from .constants import MintosExchangeScrape as scrape_const

from juloserver.julo.models import Loan
from juloserver.julo.clients import get_julo_mintos_client

logger = logging.getLogger(__name__)
mintos_client = get_julo_mintos_client()

@task(queue="loan_low")
def get_forex_rate_idr_to_eur():
    # get response from website www.bi.go.id to get rate
    url = scrape_const.URL
    response = requests.get(url)
    html_content = response.content

    soup = BeautifulSoup(html_content, 'html.parser')
    # get data forex data EUR currency
    table = soup.find(id="ctl00_PlaceHolderMain_biWebKursTransaksiBI_GridView2")
    value_list = list()
    for tr in table.find_all('tr'):
        currency = tr.findChildren()[0].get_text()
        if currency.strip() == scrape_const.CURRENCY:
            for td in tr.find_all('td'):
                value_list.append(str(td.get_text()).strip())

    currency = value_list[0]
    sell = float(value_list[2].replace(',', ''))
    buy = float(value_list[3].replace(',', ''))
    rate = old_div(1, (old_div((sell + buy), 2)))

    ExchangeRate.objects.create(
        currency=currency,
        sell=sell,
        buy=buy,
        rate=py2round(rate, 6),
        source=url
    )

@task(queue="loan_low")
def loan_sendin_tasks(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'loan_sendin_tasks',
            'loan_id': loan_id,
            'message': "couldn't find loan"
        })
        return

    response = mintos_client.loan_sendin(loan)
    insert_mintos_loan_list_status(response)

@task(queue="loan_low")
def get_loans_tasks(loan_id=None):
    mintos_loan_id = get_mintos_loan_id(loan_id)
    response = mintos_client.get_loans(mintos_loan_id)
    update_mintos_loan_list_status(response)

@task(queue="loan_low")
def payment_sendin_tasks(loan_id, payment_number):
    today = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'payment_sendin_tasks',
            'loan_id': loan_id,
            'message': "couldn't find loan"
        })
        return

    mintos_loan_id = get_mintos_loan_id(loan.id)
    if not mintos_loan_id:
        logger.info({
            'action': 'payment_sendin_tasks',
            'loan_id': loan.id,
            'message': "couldn't find mintos loan id"
        })
        return

    # handle if there partail multi payment time a days
    sb_payments = SbMintosPaymentSendin.objects.filter(
        loan_id=loan_id, payment_schedule_number=payment_number, cdate__gte=today.replace(tzinfo=pytz.UTC)
        )
    if not sb_payments:
        logger.info({
            'action': 'payment_sendin_tasks',
            'loan_id': loan_id,
            'message': "couldn't find sb payment send in"
        })
        return

    for sb_payment in sb_payments:
        response, sendin_data = mintos_client.payment_sendin(mintos_loan_id, sb_payment, loan)
        # save date to ops payment send in
        if response:
            MintosPaymentSendin.objects.create(**sendin_data)

@task(queue="loan_low")
def rebuy_loan_tasks(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'rebuy_loan_tasks',
            'loan_id': loan_id,
            'message': "couldn't find loan"
        })
        return

    mintos_loan_id = get_mintos_loan_id(loan_id)
    if not mintos_loan_id:
        logger.info({
            'action': 'rebuy_loan_tasks',
            'loan_id': loan_id,
            'message': "couldn't find mintos loan id"
        })
        return

    sb_mintos_buyback = SbMintosBuybackSendin.objects.filter(
        application_xid=loan.application.application_xid
    ).first()

    purpose = sb_mintos_buyback.purpose if sb_mintos_buyback and sb_mintos_buyback.purpose == "early_repayment" else "other"
    if mintos_loan_id:
        response = mintos_client.get_loans(mintos_loan_id)
        if response['data']['loan']['status'] != 'finished':
            mintos_client.rebuy_loan(mintos_loan_id, purpose, loan)

@task(queue="loan_low")
def send_all_data_loan_to_mintos():
    mintos_queue = get_mintos_queue_data()

    for queue in mintos_queue:
        loan_id = queue['loan_id']
        payment_number = queue['payment_number']
        if queue['queue_type'] == 'loan_sendin':
            loan_sendin_tasks.delay(loan_id)
        elif queue['queue_type'] == 'payment_sendin':
            payment_sendin_tasks.delay(loan_id, payment_number)
        elif queue['queue_type'] == 'rebuy_loan':
            rebuy_loan_tasks.delay(loan_id)

        MintosQueueStatus.objects.get_or_none(pk=queue['id']).update_safely(
            loan_id=loan_id,
            queue_status=True
        )

@task(queue="loan_low")
def update_mintos_loan_from_report(data, mintos_report_id):
    mintos_loan_list = MintosLoanListStatus.objects.filter(
        mintos_loan_id=data['mintos_id'])

    data["mintos_report_id"] = mintos_report_id
    if "finished_at" in data:
        data["finished_at"] = parse(data["finished_at"])
    MintosReportDetail.objects.create(**data)

    if not mintos_loan_list:
        logger.info({
            'action': 'update_mintos_loan_from_report',
            'mintos_id': data['mintos_id'],
            'data': data,
            'message': "couldn't find mintos loan id"
        })
        return

    mintos_loan_list.update(status=data['loan_status'])
