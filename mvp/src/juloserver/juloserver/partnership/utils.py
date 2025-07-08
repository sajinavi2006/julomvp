import os
import re
import logging
import math
from types import SimpleNamespace

from typing import List, Optional, Union, Any

import requests
import time
import phonenumbers
from django.db.models import Model

from juloserver.julo.clients import get_julo_sentry_client
from datetime import timedelta, datetime

from juloserver.julo.models import (
    FeatureSetting,
    Loan,
    LoanDurationUnit,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services2 import get_redis_client
from juloserver.partnership.constants import (
    ErrorMessageConst,
    PartnershipFeatureNameConst,
    PhoneNumberFormat,
    PartnershipPIIMappingCustomerXid,
    MALICIOUS_PATTERN,
    MAP_PAYMENT_FREQUENCY,
)
from django.utils import timezone

from django.conf import settings
from django.core.urlresolvers import reverse
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from juloserver.julo.services2.encryption import Encryption
from juloserver.account.constants import AccountConstant
from io import BytesIO
from PIL import Image as Imagealias
from rest_framework.response import Response
from rest_framework import status
from email_validator import EmailNotValidError, validate_email
from nanoid import generate

from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.pii_vault.clients import PIIVaultClient
from juloserver.pii_vault.constants import (
    DetokenizeResourceType,
    PiiVaultDataType,
    PIIType,
    PiiSource,
)
from juloserver.pii_vault.models import PIIVaultQueryset
from juloserver.pii_vault.services import detokenize_pii_data
from juloserver.digisign.models import DigisignRegistration
from juloserver.digisign.constants import RegistrationStatus

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


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


def check_required_fields(field_data, fields_required):
    fields_none = []
    fields_empty = []
    for field_required in fields_required:
        field_value = field_data.get(field_required, None)
        if field_value is None:
            fields_none.append(field_required)
        elif field_value == '':
            fields_empty.append(field_required)

    return fields_none, fields_empty


def verify_phone_number(value):
    valid = True
    phone_number_regex = re.compile(r'^(08)(\d{8,12})$')

    if not phone_number_regex.match(value):
        valid = False
    return valid


def verify_company_phone_number(value):
    valid = True
    phone_number_regex = re.compile(r'^(?!08)(?!628)(?!8)(?!008)(?!6208)(\d{9,15}$)')

    if not phone_number_regex.match(value):
        valid = False
    return valid


def duplicate_list_value(list):
    return len(list) != len(set(list))


def custom_error_messages_for_required(
    message, length=None, type=None, raise_type=False, choices=()
):
    messages = {
        "blank": "{} tidak boleh kosong".format(message),
        "null": "{} tidak boleh kosong".format(message),
        "required": "{} harus diisi".format(message),
        "min_length": "{} minimal {} karakter".format(message, length),
        "invalid_choice": "{} pilihan tidak valid. Pilihan {}".format(message, choices),
    }
    if type in ["Float", "Integer", "Boolean", "Date"]:
        if raise_type:
            if type == 'Integer':
                messages['invalid'] = "{} Harus Integer".format(message)
            elif type == 'Float':
                messages['invalid'] = "{} Harus Float/Decimal".format(message)
            elif type == 'Boolean':
                messages['invalid'] = "{} boolean tidak valid".format(message)
            elif type == 'Date':
                messages['invalid'] = "{} tanggal tidak valid. Gunakan format YYYY-mm-dd".format(
                    message
                )
        else:
            messages['invalid'] = "{} data tidak valid".format(message)
    return messages


def check_contain_more_than_one_space(string):
    if re.findall(r'\s{2,}', str(string)):
        return True

    return False


def custom_required_error_messages_for_merchants(length=None):
    messages = {
        "blank": "tidak boleh kosong",
        "null": "tidak boleh kosong",
        "required": "harus diisi",
        "min_length": "minimal {} karakter".format(length),
        "invalid": ErrorMessageConst.INVALID_DATA
    }

    return messages


def custom_required_error_messages_for_whitelabel(length=None):
    messages = {
        "blank": "tidak boleh kosong",
        "null": "tidak boleh kosong",
        "required": "harus diisi",
        "min_length": "minimal {} karakter".format(length),
        "invalid": ErrorMessageConst.INVALID_DATA
    }

    return messages


def custom_required_error_messages_for_webview(message="", length=None):
    messages = {
        "blank": "{} tidak boleh kosong".format(message),
        "null": "{} tidak boleh kosong".format(message),
        "required": "{} harus diisi".format(message),
        "min_length": "{} minimal {} karakter".format(message, length),
        "invalid": "{} {}".format(message, ErrorMessageConst.INVALID_DATA)
    }

    return messages


def get_image_url_with_encrypted_image_id(image_id):
    encrypt = Encryption()
    encrypted_image_id = encrypt.encode_string(str(image_id))
    url = reverse('image_process',
                  kwargs={'encrypted_image_id': encrypted_image_id})

    return settings.BASE_URL + url


def verify_merchant_phone_number(value):
    valid = True
    phone_number_regex = re.compile(r'^(08|02)(\d{8,12})$')

    if not phone_number_regex.match(value):
        valid = False
    return valid


def transform_list_error_msg(msgs, exclude_key=False):
    result = []
    for msg in msgs:
        for key, value in list(msg.items()):
            prefix = key + ' '
            if exclude_key:
                prefix = ''

            result.append(prefix + value[0])

    return result


def custom_required_error_messages_for_decimals(
        length=None, max_value=1, min_value=0, max_decimal_places=2, max_digits=10,
        max_whole_digits=10):
    messages = {
        "blank": "tidak boleh kosong",
        "null": "tidak boleh kosong",
        "required": "harus diisi",
        "min_length": "minimal {} karakter".format(length),
        "max_value": "pastikan angka yang dimasukkan kurang dari atau "
                     "sama dengan {}.".format(max_value),
        "min_value": "pastikan angka yang dimasukkan lebih besar atau "
                     "sama dengan {}.".format(min_value),
        "max_decimal_places": "pastikan tidak boleh lebih dari {} angka "
                              "setelah koma.".format(max_decimal_places),
        'invalid': "mohon memasukkan angka yang benar",
        'max_digit': "pastikan angka yang dimasukan tidak lebih dari "
                     "{}.".format(max_digits),
        'max_whole_digits': "pastikan tidak boleh lebih dari {} "
                            "angka setelah koma".format(max_whole_digits),
        'max_string_length': "melebihi maksimal string yang ditentukan"
    }

    return messages


class AESCipher(object):
    """
    AES Encryption used for Whitelabel Partnership.
    This is used for encrypting and decrypting data for whitelabel for login less experience
    Since '\' and '/' are problem characters while opening webview
    we replace those characters after encryption and replace them before decryption

    This AES Cipher is used for encrypting data based on WHITELABEL_SECRET_KEY
    This has an encrypt() method which feeds in the string to be encoded
    There is a decrypt() method which feeds in the encoded string to get the original string.
    """
    def __init__(self, key):
        self.bs = 32
        self.key = hashlib.sha256(key.encode()).digest()
        self.backslash_replacement = '__-'
        self.common_replacement = '-__'

    def encrypt(self, raw):
        raw = self._pad(raw)
        nonce = os.urandom(32)
        cipher = AESGCM(self.key)
        enc = base64.b64encode(nonce + cipher.encrypt(
            nonce, raw.encode('utf-8'), settings.WHITELABEL_SECRET_KEY.encode('utf-8')
        )).decode('utf-8')
        enc = re.sub(r'/', self.backslash_replacement, enc)
        enc = re.sub(r'\\', self.common_replacement, enc)
        return enc

    def decrypt(self, enc):
        enc = re.sub(self.backslash_replacement, r'/', enc)
        enc = re.sub(self.backslash_replacement, r'\\', enc)
        enc = base64.b64decode(enc)
        iv = enc[:self.bs]
        cipher = AESGCM(self.key)
        return self._unpad(cipher.decrypt(
            iv, enc[self.bs:], settings.WHITELABEL_SECRET_KEY.encode('utf-8'))
        ).decode('utf-8')

    def _pad(self, s):
        return s + (self.bs - len(s) % self.bs) * chr(self.bs - len(s) % self.bs)

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s) - 1:])]


def get_aes_cypher():
    return AESCipher(settings.WHITELABEL_SECRET_KEY)


def generate_public_key_whitelabel(
    email,
    phone_number,
    partner_name,
    partner_reference_id,
    paylater_transaction_xid='',
    partner_customer_id='',
    email_phone_diff='',
    partner_origin_name='',
):

    """
    expiry token time for paylater = current timestamp +  24 hr
    """
    token_expiry_time = ''
    if paylater_transaction_xid:
        token_expiry_time = int(time.time()) + (3600 * 24)
    string_to_be_encryted = (str(email) + ':' + str(phone_number) + ':'
                             + str(partner_name) + ':' + str(partner_reference_id) + ':'
                             + settings.WHITELABEL_PUBLIC_KEY + ':'
                             + str(paylater_transaction_xid) + ':'
                             + str(token_expiry_time) + ':'
                             + str(partner_customer_id) + ':'
                             + str(email_phone_diff) + ':'
                             + str(partner_origin_name))
    aes_cypher = get_aes_cypher()
    encrypted_string = aes_cypher.encrypt(string_to_be_encryted)
    return encrypted_string


def verify_webview_pin(pin):
    if pin is None:
        return "Pin harus diisi"

    if not pin:
        return "Pin tidak boleh kosong"

    pin = str(pin)
    if len(str(pin)) != 6 or not str(pin).isdigit():
        return "PIN tidak memenuhi pattern yang dibutuhkan"

    return None


def is_allowed_account_status_for_loan_creation_and_loan_offer(account):
    if account.status_id not in {AccountConstant.STATUS_CODE.active,
                                 AccountConstant.STATUS_CODE.active_in_grace}:
        return False

    return True


def parse_phone_number_format(phone_number: str, phone_format: PhoneNumberFormat):
    parse_phone_number = phonenumbers.parse(
        number=phone_number, region='ID'
    )
    formatted_phone_number = phonenumbers.format_number(
        parse_phone_number, phone_format
    )
    return formatted_phone_number


def validate_image_url(url: str) -> bool:
    """
        First validating if the url from AWS Other thir party
        Usually they are using different content_type
        For public image just validating using headers
    """
    try:
        response = requests.get(url, stream=True)
        content_type = response.headers.get('Content-Type')

        if content_type == "application/octet-stream":
            try:
                image_data = BytesIO(response.content)
                Imagealias.open(image_data)
            except OSError:
                return False

        elif "image" not in content_type:
            return False

    except Exception:
        return False

    return True


def response_template(status=status.HTTP_200_OK, message=None, errors=None, data=None):
    response_dict = {}

    if message:
        response_dict['message'] = message
    if errors:
        response_dict['errors'] = errors
    if data:
        response_dict['data'] = data

    return Response(status=status, data=response_dict)


def partnership_check_email(email):
    if email.endswith("@julofinance.com") or email.endswith("@julo.co.id"):
        return True

    # verify the email format
    match = re.match(
        '^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$',  # noqa
        email
    )

    if match is None:
        return False

    # validate the domain using email_validator
    try:
        v = validate_email(email)

    except EmailNotValidError:
        return False

    if 'mx-fallback' in v and v['mx-fallback']:
        return False

    if 'unknown-deliverability' in v and v['unknown-deliverability'] == 'timeout':
        return False

    return True


def miniform_verify_nik(nik: str) -> Union[str, None]:
    err_invalid_format = 'NIK tidak sesuai format'
    if len(nik) != 16:
        return 'NIK minimum 16 karakter'
    if not nik.isdigit():
        return 'NIK harus menggunakan angka'
    birth_day = int(nik[6:8])
    if not (1 <= int(nik[0:2])) or not (1 <= int(nik[2:4])) or not (1 <= int(nik[4:6])):
        return err_invalid_format
    if not (1 <= birth_day <= 31 or 41 <= birth_day <= 71):
        return err_invalid_format
    if not (1 <= int(nik[8:10]) <= 12):
        return err_invalid_format
    if not (1 <= int(nik[12:])):
        return err_invalid_format
    return None


def miniform_verify_phone(phone: str) -> Union[str, None]:
    err_phone = 'Nomor HP tidak sesuai format'
    if len(phone) < 10:
        return err_phone
    elif len(phone) > 15:
        return err_phone

    phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
    if not (re.fullmatch(phone_number_regex, phone)):
        return err_phone

    return None


def idempotency_check_cron_job(task_name) -> bool:
    from juloserver.julo.services2 import get_redis_client

    redis_key = task_name
    redis_client = get_redis_client()

    current_time = timezone.localtime(timezone.now())

    cached_task = redis_client.get(redis_key)
    if cached_task:
        return True
    else:
        current_hour = current_time.hour
        current_minute = current_time.minute
        minutes_until_expire = (23 - current_hour) * 60 + (50 - current_minute)

        redis_client.set(redis_key, "executed", timedelta(minutes=minutes_until_expire))

        return False


def is_idempotency_check():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PARTNERSHIP_IDEMPOTENCY_CHECK, is_active=True
    )


def is_process_tracking():
    return PartnershipFeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_COLLECTION_TRACKING_PROCESS, is_active=True
    )


def is_use_new_function():
    return PartnershipFeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_COLLECTION_ON_OFF_REFACTOR_FUNCTION, is_active=True
    ).exists()


def generate_xid_from_unixtime(identifier: int) -> int:
    """
    Total Length: 18, unix_time = 10, identifer = 1, nano_id = 7
    Eg. 169356338912862851
    """
    unix_time = int(time.time())
    nano_id = generate('0123456789', 7)
    return int("{}{}{}".format(unix_time, identifier, nano_id))


def generate_xid_from_datetime(identifier: int) -> int:
    """
    Total Length: 18, now = 10, nano_id = 7, identifier = 1
    Eg. 230904113193500682
    """
    now = datetime.today().strftime('%y%m%d%H%M')
    nano_id = generate('0123456789', 7)
    return int("{}{}{}".format(now, identifier, nano_id))


def generate_xid_from_product_line(product_line: int) -> Union[None, int]:
    """
    Total Length: 18, now = 10, nano_id = 5, product_line = 3
    Eg. 202309041319350068
    """
    length_of_product_line = len(str(product_line))
    if length_of_product_line > 3:
        logger.info(
            {
                "action": "generate_xid_from_product_line",
                "message": "Failed to generate the XID, because product line length gt 3",
                "product_line": product_line,
            }
        )
        return None

    if length_of_product_line <= 2:
        product_line += 100

    now = datetime.today().strftime('%Y%m%d%H')
    nano_id = generate('0123456789', 5)
    return int("{}{}{}".format(now, product_line, nano_id))


def partnership_detokenize_sync_object_model(
    pii_source: str,
    object_model: Model,
    customer_xid: Optional[int] = None,
    fields_param: List = None,
    pii_type: str = PiiVaultDataType.PRIMARY,
) -> Union[SimpleNamespace, Model]:
    fn_name = 'partnership_detokenize_sync_object_model'
    feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DETOKENIZE,
        is_active=True,
    ).exists()
    if not feature_setting:
        logger.warning(
            {
                'action': fn_name,
                'message': 'Feature Config partnership detokenize is not active',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model_pk': object_model.pk,
            }
        )
        return object_model
    try:
        params = {'pii_data_type': PiiVaultDataType.PRIMARY}
        resources = {'object': object_model}
        if pii_type != PiiVaultDataType.PRIMARY:
            params = {'pii_data_type': PiiVaultDataType.KEY_VALUE}
        else:
            resources['customer_xid'] = customer_xid

        fields = None
        get_all = True
        if fields_param:
            fields = fields_param
            get_all = False
        result = detokenize_pii_data(
            pii_source,
            DetokenizeResourceType.OBJECT,
            [resources],
            fields=fields,
            get_all=get_all,
            run_async=False,
            **params,
        )
        logger.info(
            {
                'action': fn_name,
                'message': 'Detokenize primary object model',
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'result': result,
                'model_pk': object_model.pk,
            }
        )

        try:
            result_detokenized = result[0].get('detokenized_values')
        except (AttributeError, TypeError):
            result_detokenized = None

        return SimpleNamespace(**result_detokenized) if result_detokenized else object_model
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'customer_xid': customer_xid,
                'pii_source': pii_source,
                'model_pk': object_model.pk,
            }
        )
        return object_model


def generate_pii_filter_query_partnership(model: Any = None, filter_dict: Optional[dict] = None):
    fn_name = 'generate_pii_filter_query_partnership'
    if filter_dict is None:
        filter_dict = {}

    constructed_filter_dict = {}
    if not model or not filter_dict or not getattr(model, 'PII_FIELDS', []):
        return filter_dict

    model_pii_fields = model.PII_FIELDS
    model_pii_fields_with_in = ["{}__in".format(item) for item in model_pii_fields]
    model_pii_type = getattr(model, 'PII_TYPE', PIIType.CUSTOMER)
    is_customer_type = True if model_pii_type != PIIType.KV else False
    pii_vault_client = PIIVaultClient(
        authentication=settings.PII_VAULT_PARTNERSHIP_ONBOARDING_TOKEN
    )
    pii_query_function = (
        pii_vault_client.exact_lookup if is_customer_type else pii_vault_client.general_exact_lookup
    )
    pii_detokenize_fs = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DETOKENIZE,
        is_active=True,
    ).last()
    if not pii_detokenize_fs:
        logger.warning(
            {'action': fn_name, 'message': 'Feature partnership detokenize is not active'}
        )
        return filter_dict

    timeout = pii_detokenize_fs.parameters.get('query_lookup_timeout', 10)

    try:
        for key, value in filter_dict.items():
            if key in model_pii_fields:
                pii_tokenized = pii_query_function(value, timeout)
                constructed_filter_dict.update(
                    {key: value}
                    if any(item is None or item == '' for item in pii_tokenized)
                    else {'{}_{}__in'.format(key, 'tokenized'): pii_tokenized}
                )
            elif key in model_pii_fields_with_in:
                pii_tokenize_items = []
                items = []
                for item in value:
                    pii_tokenized = pii_query_function(item, timeout)
                    if not pii_tokenized:
                        items.append(item)
                    pii_tokenize_items.extend(pii_tokenized)
                if items:
                    constructed_filter_dict.update({key: items})
                parts = key.split('__')
                filter_updated = "{}_tokenized__{}".format(parts[0], parts[1])
                constructed_filter_dict.update({filter_updated: pii_tokenize_items})
            else:
                constructed_filter_dict.update({key: value})

    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': "Error generate PII filter query",
                'error': str(e),
                'model': model,
                'filter_dict': filter_dict,
            }
        )
        return filter_dict

    return constructed_filter_dict


def partnership_detokenize_sync_primary_object_model_in_bulk(
    pii_source: str, object_models: List[Model], fields_param: List = None
) -> dict:
    fn_name = 'partnership_detokenize_sync_primary_object_model_in_bulk'
    is_from_pii_result = False
    object_results = object_models
    payloads = []
    try:
        # Construct payload to send for detokenize
        customer_xid_function = PartnershipPIIMappingCustomerXid.TABLE.get(pii_source)
        for object in object_models:
            payloads.append(
                dict(
                    customer_xid=eval(customer_xid_function),
                    object=object,
                )
            )

        feature_setting = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': fn_name,
                    'message': 'Feature partnership detokenize is not active',
                    'pii_source': pii_source,
                }
            )

        else:
            fields = None
            get_all = True
            if fields_param:
                fields = fields_param
                get_all = False

            # Start detokenize object
            start_time = timezone.localtime(timezone.now())
            result = detokenize_pii_data(
                pii_source,
                DetokenizeResourceType.OBJECT,
                payloads,
                fields=fields,
                get_all=get_all,
                run_async=False,
            )
            end_time = timezone.localtime(timezone.now())
            execution_time = (end_time - start_time).total_seconds()
            logger.info(
                {
                    'action': fn_name,
                    'message': 'Detokenize primary object model',
                    'pii_source': pii_source,
                    'result': result,
                    'start_time': str(start_time),
                    'end_time': str(end_time),
                    'execution_time': '{} Seconds'.format(int(execution_time)),
                }
            )
            is_from_pii_result = True
            object_results = result

    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize primary object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )

    finally:
        # construct detokenize data
        result = dict()
        if not is_from_pii_result or not object_results:
            for payload in payloads:
                result.update({payload.get('customer_xid'): payload.get('object')})
            return result
        else:
            for object_result in object_results:
                result.update(
                    {
                        object_result.get('customer_xid'): SimpleNamespace(
                            **object_result.get('detokenized_values', {})
                        )
                        if object_result.get('detokenized_values')
                        else object_result.get('object')
                    }
                )
            return result


def partnership_detokenize_sync_kv_in_bulk(
    pii_source: str, object_models: PIIVaultQueryset, fields_param: List = None
) -> dict:
    fn_name = 'partnership_detokenize_sync_kv_in_bulk'
    is_from_pii_result = False
    object_results = object_models
    payloads = []
    try:
        for object_model in object_models.iterator():
            payloads.append({'object': object_model})

        feature_setting = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DETOKENIZE,
            is_active=True,
        ).exists()
        if not feature_setting:
            logger.warning(
                {
                    'action': fn_name,
                    'message': 'Feature partnership detokenize is not active',
                    'pii_source': pii_source,
                }
            )
        else:
            fields = None
            get_all = True
            if fields_param:
                fields = fields_param
                get_all = False
            start_time = timezone.localtime(timezone.now())
            result = detokenize_pii_data(
                pii_source,
                DetokenizeResourceType.OBJECT,
                payloads,
                fields=fields,
                get_all=get_all,
                run_async=False,
                pii_data_type=PiiVaultDataType.KEY_VALUE,
            )
            end_time = timezone.localtime(timezone.now())
            execution_time = (end_time - start_time).total_seconds()
            logger.info(
                {
                    'action': fn_name,
                    'message': 'Detokenize kv object model',
                    'pii_source': pii_source,
                    'result': result,
                    'start_time': str(start_time),
                    'end_time': str(end_time),
                    'execution_time': '{} Seconds'.format(int(execution_time)),
                }
            )
            is_from_pii_result = True
            object_results = result
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error(
            {
                'action': fn_name,
                'message': 'Error detokenize kv object model',
                'error': str(e),
                'pii_source': pii_source,
            }
        )
    finally:
        result = dict()
        if not is_from_pii_result or not object_results:
            for payload in payloads:
                result.update(
                    {
                        payload.get('object').id
                        if not pii_source == PiiSource.PAYMENT_METHOD
                        else payload.get('object').payment_method_name: payload.get('object')
                    }
                )

            return result
        else:
            for object in object_results:
                result.update(
                    {
                        object.get('object').id
                        if not pii_source == PiiSource.PAYMENT_METHOD
                        else object.get('object').payment_method_name: SimpleNamespace(
                            **object.get('detokenized_values')
                        )
                        if object.get('detokenized_values')
                        else object.get('object')
                    }
                )
            return result


def verify_auth_token_skrtp(b64_string):
    if not b64_string:
        return "Token required", None
    try:
        base64_bytes = b64_string.encode("ascii")
        token_bytes = base64.b64decode(base64_bytes)
        token = token_bytes.decode("ascii")
    except Exception:
        return "Token invalid", None

    token_str = token.split('_')
    if len(token_str) != 2:
        return "Token invalid separator", None
    loan_xid = token_str[0]
    date_str = token_str[1]

    try:
        datetime.strptime(date_str, "%Y%m%d%H%M%S")
    except ValueError:
        return "Token invalid format timestamp", None

    date_dt = datetime.strptime(date_str, "%Y%m%d%H%M%S")
    day_after = date_dt + timedelta(hours=24)
    now = datetime.now()

    if now > day_after:
        return "Token expired", None

    loan = Loan.objects.get_or_none(loan_xid=loan_xid)

    if not loan:
        return "Loan not found", None

    sphp_sent_ts = timezone.localtime(loan.sphp_sent_ts)
    sphp_sent_str = sphp_sent_ts.strftime("%Y%m%d%H%M%S")
    if sphp_sent_str != date_str:
        return "Token invalid timestamp", None

    return "", loan


def partnership_digisign_registration_status(customer_id: int) -> bool:
    digisign = DigisignRegistration.objects.filter(
        customer_id=customer_id,
        registration_status__in={
            RegistrationStatus.REGISTERED,
            RegistrationStatus.VERIFIED,
        },
    ).last()
    is_registered = False
    if digisign:
        is_registered = True
    return is_registered


def is_malicious(input_string):
    """
    Detects if the input string contains malicious content based on defined patterns.
    :param input_string: The string to validate
    :return: List of detected issues (empty if no issues found)
    """
    for attack_type, pattern in MALICIOUS_PATTERN.items():
        if re.search(pattern, input_string, re.IGNORECASE):
            return True
    return False


def valid_name(name):
    pattern = r'^[A-Za-z]+(\s[A-Za-z]+)*$'

    # Check if the name matches the pattern
    return bool(re.match(pattern, name))


def get_fs_send_email_disbursement_notification(partner_name: str):
    email = None
    send_to_partner = False
    send_to_borrower = False
    feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.SEND_EMAIL_DISBURSEMENT_NOTIFICATION,
        is_active=True,
    ).first()
    if feature_setting:
        fs_param = feature_setting.parameters
        fs_val = fs_param.get(partner_name)
        if fs_val:
            email = fs_val.get("partner_email")
            send_to_partner = fs_val.get("send_to_partner")
            send_to_borrower = fs_val.get("send_to_borrower")
            if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                return "Invalid partner's email on feature setting", None, None, None

    return None, email, send_to_partner, send_to_borrower


def get_redis_key(key):
    redis_client = get_redis_client()
    value = redis_client.get(key)
    return value


# expiry time within 1 week for the default
def set_redis_key(key, value, expire_time=60 * 24 * 7):
    redis_client = get_redis_client()
    redis_client.set(key, value, expire_time=expire_time)
    return value


class PartnershipJobDropDown(object):
    LIST_JOB_TYPE = [
        "Pegawai swasta",
        "Pegawai negeri",
        "Pengusaha",
        "Freelance",
        "Staf rumah tangga",
        "Ibu rumah tangga",
        "Mahasiswa",
        "Tidak bekerja",
    ]

    MAPPED_JOB_POSITION = {
        'Admin / Finance / HR': [
            "Admin",
            "Akuntan / Finance",
            "HR",
            "Office Boy",
            "Sekretaris",
        ],
        'Design / Seni': [
            "Design Grafis",
            "Pelukis",
            "Photographer",
        ],
        "Entertainment / Event": [
            "DJ / Musisi",
            "Event Organizer",
            "Kameraman",
            "Penyanyi / Penari / Model",
            "Produser / Sutradara",
        ],
        "Hukum / Security / Politik": [
            "Anggota Pemerintahan",
            "Hakim / Jaksa / Pengacara",
            "Notaris",
            "Ormas",
            "Pemuka Agama",
            "Satpam",
            "TNI / Polisi",
        ],
        "Kesehatan": [
            "Apoteker",
            "Dokter",
            "Perawat",
            "Teknisi Laboratorium",
        ],
        "Konstruksi / Real Estate": [
            "Arsitek / Tehnik Sipil",
            "Interior Designer",
            "Mandor",
            "Pemborong",
            "Proyek Manager / Surveyor",
            "Real Estate Broker",
            "Tukang Bangunan",
        ],
        "Media": [
            "Kameraman",
            "Penulis / Editor",
            "Wartawan",
        ],
        "Pabrik / Gudang": [
            "Buruh Pabrik / Gudang",
            "Kepala Pabrik / Gudang",
            "Teknisi Mesin",
        ],
        "Pendidikan": [
            "Dosen",
            "Guru",
            "Instruktur / Pembimbing Kursus",
            "Kepala Sekolah",
            "Tata Usaha",
        ],
        "Perawatan Tubuh": [
            "Fashion Designer",
            "Gym / Fitness",
            "Pelatih / Trainer",
            "Salon / Spa / Panti Pijat",
        ],
        "Perbankan": [
            "Back-office",
            "Bank Teller",
            "CS Bank",
            "Credit Analyst",
            "Kolektor",
            "Resepsionis",
        ],
        "Sales / Marketing": [
            "Account Executive / Manager",
            "Salesman",
            "SPG",
            "Telemarketing",
        ],
        "Service": [
            "Customer Service",
            "Kasir",
            "Kebersihan",
            "Koki",
            "Pelayan / Pramuniaga",
        ],
        "Tehnik / Computer": [
            "Engineer / Ahli Tehnik",
            "Penulis Teknikal",
            "Programmer / Developer",
            "R&D / Ilmuwan / Peneliti",
            "Warnet",
            "Otomotif",
        ],
        "Transportasi": [
            "Supir / Ojek",
            "Agen Perjalanan",
            "Kurir / Ekspedisi",
            "Pelaut / Staff Kapal / Nahkoda Kapal",
            "Pilot / Staff Penerbangan",
            "Sewa Kendaraan",
            "Masinis / Kereta Api",
        ],
        "Perhotelan": [
            "Customer Service",
            "Kebersihan",
            "Koki",
            "Room Service / Pelayan",
        ],
        "Staf Rumah Tangga": [
            "Babysitter / Perawat",
            "Pembantu Rumah Tangga",
            "Supir",
            "Tukang Kebun",
        ],
        'Pekerja Rumah Tangga': [
            "Babysitter / Perawat",
            "Pembantu Rumah Tangga",
            "Supir",
            "Tukang Kebun",
        ],
    }

    def get_list_job_industry(self, job_type):
        if job_type in {"Pegawai swasta", "Pegawai negeri", "Pengusaha", "Freelance"}:
            return [
                "Admin / Finance / HR",
                "Design / Seni",
                "Entertainment / Event",
                "Hukum / Security / Politik",
                "Kesehatan",
                "Konstruksi / Real Estate",
                "Media",
                "Pabrik / Gudang",
                "Pendidikan",
                "Perawatan Tubuh",
                "Perbankan",
                "Sales / Marketing",
                "Service",
                "Tehnik / Computer",
                "Transportasi",
                "Perhotelan",
            ]

        elif job_type == 'Staf rumah tangga':
            return ['Staf Rumah Tangga', 'Pekerja Rumah Tangga']
        else:
            return []

    def get_list_job_position(self, job_industry):
        get_mapped_job_position = self.MAPPED_JOB_POSITION.get(job_industry, [])
        if get_mapped_job_position:
            get_mapped_job_position.append('Lainnya')

        return get_mapped_job_position


def masked_email_character(email, showed_characters: int = 2):
    email_prefix, domain = email.split('@')
    masked_emailprefix = email_prefix[:showed_characters] + '*' * (
        len(email_prefix) - showed_characters
    )
    result = masked_emailprefix + '@' + domain

    return result


def custom_error_messages_for_required_leadgen(
    message, length=None, type=None, raise_type=False, choices=()
):
    messages = {
        "blank": "{} harus diisi dengan benar".format(message),
        "null": "{} harus diisi dengan benar".format(message),
        "required": "{} harus diisi dengan benar".format(message),
        "min_length": "{} minimal {} karakter".format(message, length),
        "invalid_choice": "{} pilihan tidak valid. Pilihan {}".format(message, choices),
    }
    if type in ["Float", "Integer", "Boolean", "Date"]:
        if raise_type:
            if type == 'Integer':
                messages['invalid'] = "{} Harus Integer".format(message)
            elif type == 'Float':
                messages['invalid'] = "{} Harus Float/Decimal".format(message)
            elif type == 'Boolean':
                messages['invalid'] = "{} boolean tidak valid".format(message)
            elif type == 'Date':
                messages['invalid'] = "{} tanggal tidak valid. Gunakan format YYYY-mm-dd".format(
                    message
                )
        else:
            messages['invalid'] = "{} data tidak valid".format(message)
    return messages


def date_format_to_localtime(date, date_format):
    return timezone.localtime(date).strftime(date_format)


def reformat_date(date, date_format):
    return date.strftime(date_format)


def ceil_with_decimal(number, decimals=0):
    if decimals == 0:
        return math.ceil(number)

    factor = 10**decimals
    return math.ceil(number * factor) / factor


def get_loan_duration_unit_id(duration_unit, financing_tenure, installment_number):
    try:
        days_payment_frequency = ceil_with_decimal(financing_tenure / installment_number, 1)
        payment_frequency = MAP_PAYMENT_FREQUENCY.get(days_payment_frequency)
        if not payment_frequency:
            payment_frequency = "every {:g} {}".format(days_payment_frequency, duration_unit)

        loan_duration_unit_id = (
            LoanDurationUnit.objects.filter(
                duration_unit=duration_unit, payment_frequency=payment_frequency
            )
            .values_list('id', flat=True)
            .first()
        )
        if not loan_duration_unit_id:
            loan_duration_unit = LoanDurationUnit.objects.create(
                duration_unit=duration_unit,
                payment_frequency=payment_frequency,
                description="duration is in {} and paid {}".format(
                    duration_unit, payment_frequency
                ),
            )
            return loan_duration_unit.id, None

        return loan_duration_unit_id, None

    except Exception as e:
        return None, "Error Exception - get_loan_duration_unit_id - {}".format(str(e))
