import logging

import time

from celery import task

from django.db import transaction

from juloserver.julo.models import (
    Loan,
)

from .services import (
    construct_loan_detail_data,
    construct_schedule_data,
    get_lendeast_loan_eligiblity,
    set_data_by_month
)

from .utils import get_first_day_in_month

from .models import LendeastReportMonthly


logger = logging.getLogger(__name__)


@task(queue='loan_low')
def construct_loans_information_data(loan_ids, current_month_year):
    logger.info({
        'action': 'construct_loans_information_data',
        'msg': 'log data',
        'data': {"loan_ids": loan_ids, 'month': current_month_year}
    })

    all_data = {}
    loans = Loan.objects.filter(
        pk__in=loan_ids
    ).prefetch_related(
        'payment_set'
    ).select_related(
        'lender', 'customer', 'account'
    )
    for loan in loans.iterator():
        data = construct_loan_detail_data(loan)
        data.update(construct_schedule_data(loan))
        all_data[loan.id] = data

    set_data_by_month(all_data, current_month_year)
    with transaction.atomic():
        last_report = LendeastReportMonthly.objects.select_for_update().last()
        last_report.page_done += 1
        last_report.save()


@task(queue='loan_normal')
def collect_loans_for_lendeast():
    current_month_year = get_first_day_in_month()
    loan_ids, total_osp, summary = get_lendeast_loan_eligiblity(current_month_year)
    number_of_loans = len(loan_ids)

    logger.info({
        'action': 'collect_loans_for_lendeast',
        'msg': 'success',
        'data': {"OSP": total_osp, "lenght": number_of_loans},
    })

    block_size = 100

    LendeastReportMonthly.objects.create(
        statement_month=current_month_year,
        outstanding_amount=total_osp,
        total_loan=number_of_loans,
        page_size=block_size,
        summary=summary
    )

    for index in range(0, number_of_loans, block_size):
        time.sleep(0.5)
        construct_loans_information_data.delay(
            loan_ids[index: index + block_size],
            current_month_year
        )
