import re

from django.db import connection

from juloserver.julo.models import (
    Loan,
    Partner,
    ProductLookup,
    FDCActiveLoanChecking
)

from juloserver.disbursement.models import Disbursement
from juloserver.loan.constants import QUERY_LIMIT


def sort_transaction_method_limit_params(method_params):
    # Sort transaction_method_limit parameters descending with respect to time.
    sorted_params = {}
    all_keys = list(method_params.keys())
    hr_keys = [re.sub('[^0-9]', '', key) for key in all_keys if 'hr' in key]
    sorted_hr_keys = sorted(hr_keys, key=int, reverse=True)
    min_keys = [re.sub('[^0-9]', '', key) for key in all_keys if 'min' in key]
    sorted_min_keys = sorted(min_keys, key=int, reverse=True)
    for hr_key in sorted_hr_keys:
        sorted_params[hr_key + ' hr'] = method_params[hr_key + ' hr']
    for min_key in sorted_min_keys:
        sorted_params[min_key + ' min'] = method_params[min_key + ' min']
    return sorted_params


def get_default_pdf_options(**kwargs):
    return {
        'page-size': 'A4',
        'margin-top': '0in',
        'margin-right': '0in',
        'margin-bottom': '0in',
        'margin-left': '0in',
        'encoding': "UTF-8",
        'no-outline': None,
        **kwargs
    }


def generate_query_for_get_loan_and_disbursement(batch_size: int, last_id: int,
                                                 loan_status: int, disburse_status: str,
                                                 disburse_reason: str,
                                                 method: str) -> str:
    '''this function will generate query to get loan & disbursement data'''
    query = None
    base_query = """
    select l.*, d.*
    from {} l join {} d on l.disbursement_id = d.disbursement_id
    where l.loan_status_code = '{}'
        and d.disburse_status = '{}'
        and d.reason = '{}'
        and d.method = '{}'
    """.format(
        Loan._meta.db_table,
        Disbursement._meta.db_table,
        loan_status,
        disburse_status,
        disburse_reason,
        method
    )

    order_query = "order by d.disbursement_id desc"

    if last_id > 0:
        query = "{} and d.disbursement_id < {} {} limit {}".format(base_query, last_id,
                                                                   order_query, batch_size)
    else:
        query = "{} {} limit {}".format(base_query, order_query, batch_size)

    return query


def get_table_fields(table_name):
    '''get columns from specific table'''
    with connection.cursor() as cursor:
        query = "SELECT column_name FROM information_schema.columns WHERE table_name = '{}'".\
            format(table_name)
        cursor.execute(query)
        return [row[0] for row in cursor.fetchall()]


def to_dict(row, fields) -> dict:
    temp = {}

    try:
        for index, field in enumerate(fields):
            temp[field] = row[index]
    except (KeyError, IndexError):
        return None

    return temp


def parse_loan(row, fields) -> Loan:
    temp_loan = to_dict(row, fields)
    if not temp_loan:
        return None

    rename_fields = {
        'loan_id': 'id',
        'loan_status_code': 'status_code',
        'status_code': 'status',
        'product_code': 'product'
    }

    try:
        for old_field, new_field in rename_fields.items():
            temp_loan[new_field] = temp_loan[old_field]
            del temp_loan[old_field]
    except KeyError:
        return None

    temp_loan['partner'] = Partner(temp_loan['partner'])
    temp_loan['product'] = ProductLookup(temp_loan['product'])

    try:
        if not temp_loan['application_id2']:
            temp_loan['application_id2'] = temp_loan['application_id']
    except KeyError:
        return None

    return Loan(**temp_loan)


def parse_disbursement(row, fields) -> Disbursement:
    temp_disbursement = to_dict(row, fields)
    if not temp_disbursement:
        return None

    try:
        temp_disbursement['id'] = temp_disbursement['disbursement_id']
        del temp_disbursement['disbursement_id']
    except KeyError:
        return None

    return Disbursement(**temp_disbursement)


def is_max_creditors_done_in_1_day(loan, customer_id):
    try:
        fdc_active_loan_checking = FDCActiveLoanChecking.objects.get(customer_id=customer_id)
    except FDCActiveLoanChecking.DoesNotExist:
        return True
    is_more_than_24_hours = fdc_active_loan_checking.udate - loan.cdate

    return is_more_than_24_hours.days <= 1


def chunker(iterable, size=QUERY_LIMIT):
    res = []
    for el in iterable:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res
