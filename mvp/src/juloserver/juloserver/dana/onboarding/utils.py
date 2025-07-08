import base64
import re
import json

from Crypto.Cipher import AES
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from django.conf import settings

from juloserver.dana.constants import ENCRYPT_BLOCK_SIZE

from typing import Dict


def pad(byte_array: bytearray) -> bytes:
    """
    pkcs5 padding
    """

    pad_len = ENCRYPT_BLOCK_SIZE - len(byte_array) % ENCRYPT_BLOCK_SIZE
    return byte_array + (bytes([pad_len]) * pad_len)


def unpad(byte_array: bytearray) -> bytes:
    """
    pkcs5 unpadding
    """
    return byte_array[: -ord(byte_array[-1:])]


def decrypt_personal_information(encrypted_str: str) -> Dict:
    julo_private_key = serialization.load_pem_private_key(
        bytes(settings.JULO_PEM_PRIVATE_KEY, 'utf-8'), password=None, backend=default_backend()
    )

    dana_public_key = serialization.load_pem_public_key(
        bytes(settings.DANA_PEM_PUBLIC_KEY, 'utf-8'), backend=default_backend()
    )

    decrypt_shared_key = julo_private_key.exchange(ec.ECDH(), dana_public_key)
    decode_encrypted_msg = base64.b64decode(encrypted_str)
    decipher = AES.new(decrypt_shared_key, AES.MODE_ECB)  # NOSONAR
    msg_dec = decipher.decrypt(decode_encrypted_msg)
    decrypted_msg = unpad(msg_dec).decode('utf-8')
    final_decrypt = json.loads(decrypted_msg)
    return final_decrypt


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
