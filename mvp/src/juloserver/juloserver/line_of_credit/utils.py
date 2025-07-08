from builtins import str
import hashlib
import logging
import pytz
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def response_template(content=None, success=True, error_code='', error_message=''):
    response_dict = {
        'success': success,
        'content': content,
        'error_code': error_code,
        'error_message': error_message}
    return response_dict


def success_template(content):
    return response_template(content)


def failure_template(error_code, error_message):
    return response_template(None, False, error_code, error_message)


def calculate_next_statement_date(statement_day, last_statement_date=None):
    today = timezone.now()
    year  = today.year
    month = today.month

    next_statement_date = datetime(year=year, month=month, day=statement_day, tzinfo=pytz.UTC)

    prev_statement_date = today
    if last_statement_date:
        prev_statement_date = last_statement_date

    diff = next_statement_date - prev_statement_date
    if diff.days < 10:
        next_statement_date = next_statement_date + relativedelta(months=1)

    return next_statement_date


def add_token_sepulsa_transaction(description, sepulsa_transaction):
    extra_description = '.<br> Token <b>%s</b>.' % (sepulsa_transaction.serial_number)
    return description.replace('.', extra_description)


def create_collection(fields, datas):
    coll_list = []
    for data in datas:
        collection = {}
        for idx, field in enumerate(fields):
            collection[field] = data[idx]
        coll_list.append(collection)

    return coll_list


def pin_format_validation(pin):
    """ pin validation, pin must be string number and 6 digit length
    """
    is_valid = re.match(r'^\d{6}$', pin)
    return is_valid


def generate_pin_email_key(loc_id, email):
    """
    Create a hash that will be concatinated in
    reset pin url to confirm reset pin.
    """
    salt = hashlib.sha1(str(loc_id)).hexdigest()
    if isinstance(email, str):
        email = email.encode('utf-8')
    resept_pin_key = hashlib.sha1(salt + email).hexdigest()
    logger.debug({
        'resept_pin_key': resept_pin_key,
        'email': email
    })
    return resept_pin_key
