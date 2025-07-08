import base64
import hmac
import hashlib
import json
from itertools import groupby
import re
import time
import logging
import math

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization

from datetime import datetime
from django.conf import settings
from django.utils import timezone

from juloserver.dana.constants import (
    AccountInfoResponseCode,
    BindingResponseCode,
    DanaBasePath,
    PaymentResponseCodeMessage,
    RepaymentResponseCodeMessage,
    LoanStatusResponseCodeMessage,
    ErrorType,
    DANA_PREFIX_IDENTIFIER,
    DANA_SUFFIX_EMAIL,
    ErrorDetail,
    RefundResponseCodeMessage,
    AccountUpdateResponseCode,
    AccountInquiryResponseCode,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import trim_name
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.partnership.constants import SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF
from nanoid import generate

from typing import Any, Dict, Tuple, Iterable, Union, List


logger = logging.getLogger(__name__)


def get_redis_key(key: str) -> Any:
    """
    Handle if redis down
    """
    try:
        redis_client = get_redis_client()
        value = redis_client.get(key)
    except Exception as e:
        logger.exception(
            {
                "action": "dana_get_redis_error",
                "message": "error redis {}".format(str(e)),
                "key": key,
            }
        )
        value = None
    return value


def set_redis_key(key: str, value: Any, expiry: int = 3_600) -> Any:
    """
    Default expiry is 1 Hours
    Handle if redis down
    """
    try:
        redis_client = get_redis_client()
        redis_client.set(key, value, expiry)
    except Exception as e:
        logger.exception(
            {
                "action": "dana_set_redis_error",
                "message": "error redis {}".format(str(e)),
                "key": key,
            }
        )
        pass
    return value


def delete_redis_key(key: str) -> None:
    redis_client = get_redis_client()
    redis_client.delete_key(key)


def create_sha256_signature(private_key: str, string_to_sign: str) -> str:
    message = bytes(string_to_sign, 'utf-8')
    key = bytes(private_key, 'utf-8')

    signature = hmac.new(key, message, digestmod=hashlib.sha256).hexdigest()

    return signature


def hash_body(data: Dict, is_use_ascii_only: bool = False) -> str:
    minify_body = json.dumps(data, separators=(',', ':'), ensure_ascii=is_use_ascii_only)
    hashed_body = hashlib.sha256()
    hashed_body.update(minify_body.encode('utf-8'))
    hex_body = hashed_body.hexdigest()
    return hex_body.lower()


def create_string_to_sign(
    method: str, path: str, body: Dict, timestamp: str, is_use_ascii_only: bool = False
) -> str:
    hashed_body = hash_body(body, is_use_ascii_only)
    string_to_sign = method + ":" + path + ":" + hashed_body + ":" + str(timestamp)
    return string_to_sign


def get_error_message(
    base_path: str = DanaBasePath.onboarding, type: str = ErrorType.GENERAL_ERROR
) -> Tuple[int, str]:
    """
    Return general error as default,
    and default base_path is onboarding
    """
    if base_path == DanaBasePath.repayment:
        if type == ErrorType.BAD_REQUEST:
            response_code = RepaymentResponseCodeMessage.BAD_REQUEST.code
            response_message = RepaymentResponseCodeMessage.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code
            response_message = RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = RepaymentResponseCodeMessage.INVALID_SIGNATURE.code
            response_message = RepaymentResponseCodeMessage.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = RepaymentResponseCodeMessage.GENERAL_ERROR.code
            response_message = RepaymentResponseCodeMessage.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code
            response_message = RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.loan:
        if type == ErrorType.BAD_REQUEST:
            response_code = PaymentResponseCodeMessage.BAD_REQUEST.code
            response_message = PaymentResponseCodeMessage.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code
            response_message = PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = PaymentResponseCodeMessage.INVALID_SIGNATURE.code
            response_message = PaymentResponseCodeMessage.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = PaymentResponseCodeMessage.GENERAL_ERROR.code
            response_message = PaymentResponseCodeMessage.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code
            response_message = PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.onboarding:
        if type == ErrorType.BAD_REQUEST:
            response_code = BindingResponseCode.BAD_REQUEST.code
            response_message = BindingResponseCode.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = BindingResponseCode.INVALID_FIELD_FORMAT.code
            response_message = BindingResponseCode.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = BindingResponseCode.INVALID_SIGNATURE.code
            response_message = BindingResponseCode.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = BindingResponseCode.GENERAL_ERROR.code
            response_message = BindingResponseCode.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = BindingResponseCode.INVALID_MANDATORY_FIELD.code
            response_message = BindingResponseCode.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.loan_status:
        if type == ErrorType.BAD_REQUEST:
            response_code = LoanStatusResponseCodeMessage.BAD_REQUEST.code
            response_message = LoanStatusResponseCodeMessage.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = LoanStatusResponseCodeMessage.INVALID_FIELD_FORMAT.code
            response_message = LoanStatusResponseCodeMessage.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = LoanStatusResponseCodeMessage.INVALID_SIGNATURE.code
            response_message = LoanStatusResponseCodeMessage.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = LoanStatusResponseCodeMessage.GENERAL_ERROR.code
            response_message = LoanStatusResponseCodeMessage.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = LoanStatusResponseCodeMessage.INVALID_MANDATORY_FIELD.code
            response_message = LoanStatusResponseCodeMessage.INVALID_MANDATORY_FIELD.message
    elif base_path == DanaBasePath.refund:
        if type == ErrorType.BAD_REQUEST:
            response_code = RefundResponseCodeMessage.BAD_REQUEST.code
            response_message = RefundResponseCodeMessage.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = RefundResponseCodeMessage.INVALID_FIELD_FORMAT.code
            response_message = RefundResponseCodeMessage.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = RefundResponseCodeMessage.INVALID_SIGNATURE.code
            response_message = RefundResponseCodeMessage.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = RefundResponseCodeMessage.GENERAL_ERROR.code
            response_message = RefundResponseCodeMessage.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = RefundResponseCodeMessage.INVALID_MANDATORY_FIELD.code
            response_message = RefundResponseCodeMessage.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.account:
        if type == ErrorType.BAD_REQUEST:
            response_code = AccountUpdateResponseCode.BAD_REQUEST.code
            response_message = AccountUpdateResponseCode.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = AccountUpdateResponseCode.INVALID_FIELD_FORMAT.code
            response_message = AccountUpdateResponseCode.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = AccountUpdateResponseCode.INVALID_SIGNATURE.code
            response_message = AccountUpdateResponseCode.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = AccountUpdateResponseCode.GENERAL_ERROR.code
            response_message = AccountUpdateResponseCode.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
            response_message = AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.account_inquiry:
        if type == ErrorType.BAD_REQUEST:
            response_code = AccountInquiryResponseCode.BAD_REQUEST.code
            response_message = AccountInquiryResponseCode.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = AccountInquiryResponseCode.INVALID_FIELD_FORMAT.code
            response_message = AccountInquiryResponseCode.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = AccountInquiryResponseCode.INVALID_SIGNATURE.code
            response_message = AccountInquiryResponseCode.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = AccountInquiryResponseCode.GENERAL_ERROR.code
            response_message = AccountInquiryResponseCode.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = AccountInquiryResponseCode.INVALID_MANDATORY_FIELD.code
            response_message = AccountInquiryResponseCode.INVALID_MANDATORY_FIELD.message

    elif base_path == DanaBasePath.account_info:
        if type == ErrorType.BAD_REQUEST:
            response_code = AccountInfoResponseCode.BAD_REQUEST.code
            response_message = AccountInfoResponseCode.BAD_REQUEST.message
        elif type == ErrorType.INVALID_FIELD_FORMAT:
            response_code = AccountInfoResponseCode.INVALID_FIELD_FORMAT.code
            response_message = AccountInfoResponseCode.INVALID_FIELD_FORMAT.message
        elif type == ErrorType.INVALID_SIGNATURE:
            response_code = AccountInfoResponseCode.INVALID_SIGNATURE.code
            response_message = AccountInfoResponseCode.INVALID_SIGNATURE.message
        elif type == ErrorType.GENERAL_ERROR:
            response_code = AccountInfoResponseCode.GENERAL_ERROR.code
            response_message = AccountInfoResponseCode.GENERAL_ERROR.message
        elif type == ErrorType.INVALID_MANDATORY_FIELD:
            response_code = AccountInfoResponseCode.INVALID_MANDATORY_FIELD.code
            response_message = AccountInfoResponseCode.INVALID_MANDATORY_FIELD.message

    return response_code, response_message


def create_dana_nik(application_id: int, product_code: str = ProductLineCodes.DANA) -> str:
    """
    eg: 9997002000016081
    """
    prefix = DANA_PREFIX_IDENTIFIER

    return '{}{}{}'.format(prefix, product_code, application_id)


def create_dana_phone(origin_phone_number: str, product_code: str = ProductLineCodes.DANA) -> str:
    """
    eg: 700082289129312
    """
    return '{}{}'.format(product_code, origin_phone_number)


def create_dana_email(name: str, phone_number: str, suffix_email: str = DANA_SUFFIX_EMAIL) -> str:
    """
    eg: user_087781540796+dana@julopartner.com
    """
    email = trim_name(name)
    return '{}_{}{}'.format(email, phone_number, suffix_email)


def create_temporary_user_nik(nik: str, product_code: str = ProductLineCodes.DANA) -> str:
    """
    eg: 9997003106026502202123
    """
    prefix = DANA_PREFIX_IDENTIFIER

    return '{}{}{}'.format(prefix, product_code, nik)


def is_valid_signature(signature: str, string_to_sign: str) -> bool:
    try:
        bytes_signature = signature.encode('utf-8')
        decode_signature = base64.b64decode(bytes_signature)

        public_key = serialization.load_pem_public_key(
            bytes(settings.DANA_SIGNATURE_KEY, 'utf-8'), backend=default_backend()
        )

        public_key.verify(
            decode_signature, string_to_sign.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256()
        )
    except Exception as e:
        logger.exception(
            {
                'action_view': 'dana_invalid_signature',
                'errors': str(e),
                'signature': signature,
                'payload': string_to_sign,
            }
        )
        return False

    return True


def all_equal(iterable: Iterable) -> bool:
    """
    Returns True if all the elements are equal to each other
    """
    grouped_elements = groupby(iterable)
    return next(grouped_elements, True) and not next(grouped_elements, False)


def get_error_type(error_detail: str) -> str:
    error_type = ErrorType.BAD_REQUEST
    if error_detail in {
        ErrorDetail.NULL,
        ErrorDetail.BLANK,
        ErrorDetail.REQUIRED,
        ErrorDetail.BLANK_LIST,
    }:
        error_type = ErrorType.INVALID_MANDATORY_FIELD
    elif (
        any(regex.match(error_detail) for regex in map(re.compile, ErrorDetail.invalid_format()))
        or ErrorDetail.INVALID_BOOLEAN in error_detail
    ):
        error_type = ErrorType.INVALID_FIELD_FORMAT

    return error_type


def get_list_unique_values_without_distinct(
    data: list, unique_key_field: str, value_field: str
) -> list:
    unique_data = {}
    for item in data:
        unique_data[item.get(unique_key_field)] = item.get(value_field)
    return list(unique_data.values())


def round_half_up(n, decimals=0):
    multiplier = 10**decimals
    return math.floor(n * multiplier + 0.5) / multiplier


def send_to_slack_notification(message: str) -> None:
    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
        text=message,
    )


def construct_massive_logger(start_execution_time, start_execution_datetime) -> Dict:
    end_execution_time = time.time()
    end_execution_datetime = timezone.localtime(timezone.now())

    format_start_datetime = start_execution_datetime.strftime("%Y-%m-%dT%H:%M:%S:%f")

    format_end_datetime = end_execution_datetime.strftime("%Y-%m-%dT%H:%M:%S:%f")

    exec_time = end_execution_time - start_execution_time

    if exec_time < 0:
        time_exec_format = "{} ms".format((exec_time * 1000))
    else:
        time_exec_format = "{} s".format(exec_time)

    data = {
        'start_datetime': format_start_datetime,
        'end_datetime': format_end_datetime,
        'execution_time': time_exec_format,
    }

    return data


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


def create_x_signature(payload: Dict, timestamp: str, method: str, endpoint: str) -> str:

    hashed_data = hash_body(payload)
    string_to_sign = method + ":" + endpoint + ":" + hashed_data + ":" + timestamp
    private_key = serialization.load_pem_private_key(
        bytes(settings.DANA_X_SIGNATURE_PRIVATE_KEY_REQUEST, 'utf-8'),
        password=None,
        backend=default_backend(),
    )

    data = string_to_sign.encode('utf-8')

    signature = private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())
    signature = base64.b64encode(signature).decode('utf-8')
    return signature


def cursor_dictfetchall(cursor: Any) -> List:
    """
    Return all rows from a cursor as a dict.
    Assume the column names are unique.
    """
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def convert_str_to_abs_int(str_value):
    try:
        return abs(int(str_value))
    except (TypeError, ValueError):
        return 0
