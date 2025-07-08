import jwt
import re
import logging

from hashids import Hashids
from typing import Dict, Union
from dateutil import tz
from django.conf import settings

from juloserver.partnership.constants import (
    PartnershipTokenType,
    HTTPGeneralErrorMessage,
    HashidsConstant,
)
from juloserver.partnership.models import PartnershipJSONWebToken
from juloserver.partnership.exceptions import APIUnauthorizedError

logger = logging.getLogger(__name__)


def decode_jwt_token(token: str) -> Union[bool, Dict]:
    try:
        decode_jwt = jwt.decode(token, settings.PARTNERSHIP_JWT_SECRET_KEY, "HS256")
    except Exception:
        logger.info({"token_title": "leadgen_token_expired_invalid", "token": token})
        return False

    return decode_jwt


def get_active_token_data(token):
    if not token:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    decoded_token = decode_jwt_token(token)

    if not decoded_token:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    token_type = decoded_token.get("type", "")
    user_id = decoded_token.get("user", "")
    partner_name = decoded_token.get("partner", "")

    is_invalid_request = (
        token_type
        not in {
            PartnershipTokenType.RESET_PIN_TOKEN.lower(),
            PartnershipTokenType.CHANGE_PIN.lower(),
        }
        or not user_id
        or not partner_name
    )

    if is_invalid_request:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    hashids = Hashids(min_length=HashidsConstant.MIN_LENGTH, salt=settings.PARTNERSHIP_HASH_ID_SALT)

    user_id = hashids.decode(user_id)
    if not user_id:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    user_id = user_id[0]

    active_token = PartnershipJSONWebToken.objects.filter(
        user_id=user_id,
        is_active=True,
        partner_name=partner_name.lower(),
        token_type=token_type,
    ).last()

    if not active_token:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    if active_token.token != token:
        raise APIUnauthorizedError(HTTPGeneralErrorMessage.UNAUTHORIZED)

    return active_token


def leadgen_utc_to_localtime(datetime_obj):
    from_zone = tz.gettz('UTC')
    to_zone = tz.gettz(settings.TIME_ZONE)
    utc = datetime_obj.replace(tzinfo=from_zone)
    return utc.astimezone(to_zone)


def leadgen_verify_phone_number(phone: str) -> Union[str, None]:
    err_phone = 'Harap diisi dengan format yang sesuai'
    min_digit_err_mobile = 'Min. 10 digit'
    min_digit_err_phone = 'Min. 9 digit'
    max_digit_err = 'Maks. 14 digit'
    if not phone.isnumeric():
        return err_phone

    # Mobile numbers: must start with "08" and have at least 10 digits
    if phone.startswith("08"):
        if len(phone) < 10:
            return min_digit_err_mobile
    # validate Landline phone number
    elif re.match(r'^0[2-9]\d{1,2}', phone):
        if len(phone) < 9:
            return min_digit_err_phone
    else:
        # Invalid format if it doesn’t match known Indonesian prefixes
        return err_phone

    # Validate maximum length
    if len(phone) > 14:
        return max_digit_err

    # Checks for 7 or more consecutive identical digits
    if re.search(r'(\d)\1{6,}', phone):
        return "Nomor HP tidak valid. Harap masukkan nomor HP lain."

    return None


def leadgen_custom_error_messages_for_required(
    message, length=None, type=None, raise_type=False, choices=()
):
    messages = {
        "blank": "{} tidak boleh kosong".format(message),
        "null": "{} tidak boleh kosong".format(message),
        "required": "{} tidak boleh kosong".format(message),
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
