#!/usr/bin/python
import logging
import re

from itertools import chain
from django.db.models import F, Value, CharField
from juloserver.julo.models import ApplicationNote


logger = logging.getLogger(__name__)


def parse_loan_status(str_status):
    try:
        int_status = int(str_status)
    except Exception as e:
        logger.info({
                'parse_loan_status': str_status,
                'error': 'converting into int',
                'e': e
             })
        return None

    return int_status


def get_list_history(app_object, loan_object):
    app_histories = app_object.applicationhistory_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    loan_histories = loan_object.loanstatuschange_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    app_notes = ApplicationNote.objects.filter(application_id=app_object.id).annotate(
        type_data=Value('Notes', output_field=CharField()))

    return sorted(
        chain(app_histories, loan_histories, app_notes),
        key=lambda instance: instance.cdate, reverse=True)


def get_wallet_list_note(customer):
    wallet_notes = customer.customerwalletnote_set.all().annotate(
        type_data=Value('Notes', output_field=CharField()))

    return sorted(
        chain(wallet_notes),
        key=lambda instance: instance.cdate, reverse=True)


def loan_filter_search_field(keyword):
    from django.core.validators import validate_email
    from django.core.validators import ValidationError
    from juloserver.julo.models import Partner

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if not keyword.isdigit():
        try:
            validate_email(keyword)
            is_email_valid = True
        except ValidationError:
            is_email_valid = False
        if is_email_valid:
            return 'customer__application__email', keyword
        partner = Partner.objects.filter(name=keyword).only('name').first()
        if partner:
            return 'application__partner', partner
        return 'customer__application__fullname', keyword

    # check for search by ktp
    if len(keyword) == 16:
        return 'customer__application__ktp', keyword
    # check for search by pk or fk
    if len(keyword) == 10:
        if keyword[:1] == '2':
            return 'customer__application__id', keyword
        if keyword[:1] == '3':
            return 'id', keyword
        return None, keyword
    # check for search by loan status code
    if len(keyword) == 3:
        if keyword[:1] == '2':
            return 'loan_status__status_code', keyword
        return None, keyword
    # check for search by mobile phone number
    mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
    if mobile_phone_regex.match(keyword):
        return 'customer__application__mobile_phone_1', keyword
    return None, keyword
