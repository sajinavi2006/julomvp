import hashlib
import hmac
import base64
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from datetime import timedelta, datetime
from django.utils import timezone
import re


def generate_signature_hmac_sha512(secret_key: str, string_to_sign: str) -> str:
    hash = hmac.new(secret_key.encode(), string_to_sign.encode(), hashlib.sha512)
    hash.hexdigest()
    return base64.b64encode(hash.digest()).decode()


def generate_signature_asymmetric(private_key: str, string_to_sign: str) -> str:
    hashed = SHA256.new(bytes(string_to_sign, 'utf-8'))
    signature = PKCS1_v1_5.new(RSA.importKey(private_key)).sign(hashed)
    signature = base64.b64encode(signature).decode()
    return signature


def verify_asymmetric_signature(public_key: str, signature: str, string_to_sign: str) -> bool:
    signature_decode_b64 = base64.b64decode(signature)
    hashed = SHA256.new(bytes(string_to_sign, 'utf-8'))
    verifier = PKCS1_v1_5.new(RSA.importKey(public_key))
    return verifier.verify(hashed, signature_decode_b64)


# just to converto to snake_case for confinience
def convert_camel_to_snake(input_dict):
    if not isinstance(input_dict, dict):
        return input_dict

    def to_snake_case(key):
        return ''.join(['_' + i.lower() if i.isupper() else i for i in key]).lstrip('_')

    output_dict = {}
    for key, value in input_dict.items():
        if isinstance(value, dict):
            value = convert_camel_to_snake(value)
        elif isinstance(value, list):
            value = [convert_camel_to_snake(item) if isinstance(item, dict) \
                else item for item in value]
        output_dict[to_snake_case(key)] = value

    return output_dict


def is_contains_none_or_empty_string(lst: list) -> bool:
    return any(item is None or item == '' for item in lst)


def validate_datetime_within_10_minutes(date_string):
    try:
        input_datetime = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S%z")
        today = timezone.localtime(timezone.now())
        time_difference = today - input_datetime
        return abs(time_difference) <= timedelta(minutes=10)
    except ValueError:
        return False


def contains_word(string, word_list):
    pattern = re.compile(r'\b(' + '|'.join(re.escape(word) for word in word_list) + r')\b')
    return bool(pattern.search(string))
