import binascii
from django.conf import settings
from django.contrib.auth.models import User

from Crypto.Cipher import AES
from Crypto.Util.Padding import (
    pad,
    unpad,
)
from functools import wraps

from juloserver.standardized_api_response.utils import forbidden_error_response

from juloserver.portal.object.dashboard.constants import JuloUserRoles


class AESCipher(object):
    # \x00 meaning null/zero character, so this code below will generate 16 bytes null characters
    __iv = bytes((16 * '\x00'), 'utf-8')

    def __init__(self, credit_card_number: str):
        self.__key = bytes((credit_card_number[8:] + settings.BSS_CREDIT_CARD_HASHCODE), 'utf-8')

    def encrypt(self, value: str) -> str:
        value = bytes(value, 'utf-8')
        cipher = AES.new(self.__key, AES.MODE_CBC, iv=self.__iv)
        ciphertext = cipher.encrypt(pad(value, AES.block_size))
        return ciphertext.hex()

    def decrypt(self, encrypted_hex_value: str) -> str:
        ciphertext = binascii.unhexlify(encrypted_hex_value)
        cipher = AES.new(self.__key, AES.MODE_CBC, iv=self.__iv)
        decrypted_value = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return decrypted_value.decode('utf-8')


def role_allowed(user: User, set_groups: set) -> bool:
    return user.groups.filter(name__in=set_groups).exists()


def ccs_agent_group_required(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')

        if not role_allowed(user, {JuloUserRoles.CCS_AGENT}):
            return forbidden_error_response('user not allowed')

        return function(view, request, *args, **kwargs)

    return wrapper
