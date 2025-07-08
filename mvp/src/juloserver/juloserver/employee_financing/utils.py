import logging
import phonenumbers
import re
import datetime
import jwt

from datetime import date

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from juloserver.employee_financing.models import (
    Company,
    EmFinancingWFAccessToken
)
from juloserver.employee_financing.constants import (
    EF_PILOT_UPLOAD_MAPPING_FIELDS,
    EF_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS,
    EMPLOYEE_FINANCING_DISBURSEMENT,
    EF_PRE_APPROVAL_UPLOAD_MAPPING_FIELDS,
    WEB_FORM_ALGORITHM_JWT_TYPE
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.partnership.utils import check_contain_more_than_one_space
from rest_framework import status
from rest_framework.response import Response
from typing import Dict, Union

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def employee_financing_format_data(raw_data, action=None):
    formated_data = {}

    if action == EMPLOYEE_FINANCING_DISBURSEMENT:
        for raw_field, formated_field in EF_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS:
            formated_data[formated_field] = raw_data[raw_field]
        formated_data['loan_xid'] = ''
        formated_data['errors'] = ''
    else:
        for raw_field, formated_field in EF_PILOT_UPLOAD_MAPPING_FIELDS:
            formated_data[formated_field] = raw_data[raw_field]

    return formated_data


def format_phone_number(phone_number):
    try:
        if not phone_number:
            logger.debug({
                'phone_number': phone_number,
                'error': 'invalid_phone_number'
            })
            return phone_number
    except JuloException as err:
        return phone_number

    try:
        splitted_phone_number = list(phone_number)
        if splitted_phone_number[0] == '+' and splitted_phone_number[1] == '6' and splitted_phone_number[2] == '2':
            splitted_phone_number[0] = '0'
            splitted_phone_number.pop(1)
            splitted_phone_number.pop(1)
        elif splitted_phone_number[0] == '6' and splitted_phone_number[1] == '2':
            splitted_phone_number[0] = '0'
            splitted_phone_number.pop(1)
        elif splitted_phone_number[0] == '8':
            splitted_phone_number.insert(0, '0')
        formatted_phone_number = "".join(splitted_phone_number)
    except Exception as err:
        logger.exception('format_e164_indo_phone_number_raise_exception|error={}'.format(err))
        return phone_number
    logger.debug({
        'phone_number': phone_number,
        'formatted_ef_phone_number': formatted_phone_number
    })
    return formatted_phone_number


def verify_indo_phone_number(phone_number):
    if not phone_number.isdigit():
        return False
    phone_number = phonenumbers.parse(phone_number, "ID")
    return phonenumbers.is_valid_number(phone_number)


def verify_number(param):
    # check whether a string contains only digits, comma or dot.
    return bool(re.match('[\d,.]+$', param))


def ef_pre_approval_format_data(raw_data):
    formatted_data = {}
    for raw_field, formatted_field in EF_PRE_APPROVAL_UPLOAD_MAPPING_FIELDS:
        formatted_data[formatted_field] = raw_data[raw_field]

    return formatted_data


def calculate_age(birthdate: datetime.date) -> int:
    """calculate age by birthdate"""
    today = timezone.localtime(timezone.now()).date()
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    return age


def validate_date_format(date_str: str):
    """validate date format, must be with format yyyy-mm-dd"""
    is_valid = True
    try:
        datetime_formatted = timezone.localtime(datetime.datetime.strptime(date_str, '%Y-%m-%d'))
        return is_valid, datetime_formatted
    except ValueError:
        is_valid = False
    return is_valid, None


def create_or_update_token(email: str, company: Company,
                           expired_at: date, form_type: str,
                           token: str = None, name: str = None) -> EmFinancingWFAccessToken:
    """
        Email: Customer email
        Company: Company email
        Name: Customer name
        Expired at: new date to expired access token
        Form Type: Type of form for now there is 2 application & disbursement
        Token: User Access Token
    """
    payload = {
        'email': email,
        'name': name,
        'form_type': form_type,
        'company_id': company.id,
        'exp': expired_at  # Expired the token without stored a data in redis
    }

    user_access_tokens = EmFinancingWFAccessToken.objects.filter(
        email=email,
        company=company,
        form_type=form_type,
        is_used=False,
        limit_token_creation__gt=0
    )

    if token:
        user_access_token = user_access_tokens.filter(token=token).last()
    else:
        user_access_token = user_access_tokens.last()

    new_token = encode_jwt_token(payload)
    if not user_access_token:
        user_access_token = EmFinancingWFAccessToken.objects.create(
            form_type=form_type, expired_at=expired_at,
            company=company,
            name=name,
            email=email,
            token=new_token
        )
    else:
        # if key is not expired still using same token
        is_token_not_expired = decode_jwt_token(user_access_token.token)
        if is_token_not_expired:
            return user_access_token

        user_access_token.token = new_token
        user_access_token.expired_at = expired_at
        user_access_token.limit_token_creation = F('limit_token_creation') - 1
        user_access_token.save(update_fields=['token', 'expired_at', 'limit_token_creation'])
        user_access_token.refresh_from_db()

    return user_access_token


def encode_jwt_token(payload: Dict) -> str:
    encode_jwt = jwt.encode(payload, settings.WEB_FORM_JWT_SECRET_KEY, WEB_FORM_ALGORITHM_JWT_TYPE).decode('utf-8')

    return encode_jwt


def decode_jwt_token(token: str) -> Union[bool, Dict]:
    try:
        decode_jwt = jwt.decode(token, settings.WEB_FORM_JWT_SECRET_KEY, WEB_FORM_ALGORITHM_JWT_TYPE)
    except Exception:
        logger.info({
            'token_title': 'employee_financing_web_form_token_expired_invalid',
            'token': token
        })
        return False

    return decode_jwt


def response_template(data: Dict = {}, status: int = status.HTTP_200_OK,
                      success: bool = True, errors: Dict = {},
                      is_exception = False) -> Response:
    response = {
        'success': success,
        'data': data,
        'errors': errors
    }
    return Response(status=status, data=response, exception=is_exception)


def custom_error_messages_for_required(message: str,
                                       min_length: int = None,
                                       max_length: int = None,
                                       type: str = None,
                                       raise_type: bool = False) -> Dict:

    messages = {
        "blank": "{} tidak boleh kosong".format(message),
        "null": "{} tidak boleh kosong".format(message),
        "required": "{} harus diisi".format(message),
        "min_length": "{} minimal {} karakter".format(message, min_length),
        "max_length": "{} maksimal {} karakter".format(message, max_length)
    }
    if type in ["Float", "Integer", "Boolean"]:
        if raise_type:
            if type == 'Integer':
                messages['invalid'] = "{} Harus Integer".format(message)
            elif type == 'Float':
                messages['invalid'] = "{} Harus Float/Decimal".format(message)
            elif type == 'Boolean':
                messages['invalid'] = "{} boolean tidak valid".format(message)
        else:
            messages['invalid'] = "{} data tidak valid".format(message)
    return messages


def verify_nik(nik: str) -> bool:
    """
    Check or Validate NIK:
    - make sure NIK have 16 digit not more or less
    - have a standard indonesian format

    Param:
        - nik (str): nik

    Returns:
        - true for valid nik
    """
    if len(nik) != 16 or not nik.isdigit():
        return False

    birth_day = int(nik[6:8])
    if not (1 <= int(nik[0:2])) or not (1 <= int(nik[2:4])) or not (1 <= int(nik[4:6])):
        return False
    if not (1 <= birth_day <= 31 or 41 <= birth_day <= 71):
        return False
    if not (1 <= int(nik[8:10]) <= 12):
        return False
    if not (1 <= int(nik[12:])):
        return False
    return True


def verify_phone_number(value: str) -> bool:
    valid = True
    phone_number_regex = re.compile(r'^((08)|(628))(\d{8,12})$')

    if not phone_number_regex.match(value):
        valid = False

    # Check if invalid repeated number eg: 081111111111
    sliced_value = value[3:-1]
    if re.match(r'\b(\d)\1+\b$', sliced_value):
        valid = False

    return valid


def is_valid_name(value: str) -> bool:
    """
        Check if name not using first character as number
        Not containing more than one space
    """
    valid = True

    # Regex: Disable first character as number
    if not re.match(r'^([A-Za-z]{1})([A-Za-z0-9./,@ -])*$', value):
        valid = False

    if value and check_contain_more_than_one_space(value):
        valid = False

    return valid
