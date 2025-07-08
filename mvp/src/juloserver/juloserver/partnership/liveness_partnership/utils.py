import os
import base64
import hashlib
from typing import Union, Dict

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from django.conf import settings
from rest_framework.response import Response
from rest_framework import status


def generate_api_key(data: str) -> str:
    # Get key and decode to b64encode
    encrypt_key = base64.b64decode(settings.PARTNERSHIP_LIVENESS_ENCRYPTION_KEY)
    # Hash the data
    hashed_data = hashlib.sha256(data.encode()).digest()

    # Generate a 12-byte iv for AES-GCM
    iv = os.urandom(12)

    # Create the AES-GCM cipher
    cipher = Cipher(algorithms.AES(encrypt_key), modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()

    # Encrypt the data
    encrypted_data = encryptor.update(data.encode()) + encryptor.finalize()

    # Combine the iv, tag, data hash, and encrypted_data
    encrypted_data_with_hash = iv + encryptor.tag + hashed_data + encrypted_data

    # Return the encrypted data as a base64 encoded string
    return base64.b64encode(encrypted_data_with_hash).decode('utf-8')


def decrypt_api_key(api_key: str) -> Union[str, str]:
    # Decode the base64-encoded AES key
    decrypt_key = base64.b64decode(settings.PARTNERSHIP_LIVENESS_ENCRYPTION_KEY)

    # Decode the base64-encoded API Key
    encrypted_api_key = base64.b64decode(api_key)

    # Extract the iv, tag, hash, and encrypted_data
    iv = encrypted_api_key[:12]
    tag = encrypted_api_key[12:28]
    hashed_data = encrypted_api_key[28:60]
    encrypted_data = encrypted_api_key[60:]

    # Create the AES-GCM cipher
    cipher = Cipher(algorithms.AES(decrypt_key), modes.GCM(iv, tag), backend=default_backend())
    decryptor = cipher.decryptor()

    # Decrypt the data
    decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()

    # Return the decrypted data and hashed_data
    return decrypted_data.decode('utf-8'), hashed_data


def liveness_success_response(status: int = status.HTTP_200_OK, data: Dict = {}, meta: Dict = {}):
    """
    Returns a JSON response with a success status.
    status: int = 2xx
    data: Dict = {'message': 'Data successfully created'}
    meta: Dict = {'description': 'Invalid JSON response'}
    """

    response_data = dict()

    if data:
        response_data['data'] = data

    if meta:
        response_data['meta'] = meta

    return Response(status=status, data=response_data)


def liveness_error_response(
    status: int = status.HTTP_400_BAD_REQUEST,
    errors: Dict = {},
    data: Dict = {},
    message: str = None,
):
    """
    Returns a JSON response with an error status.
    status: int = 4xx, 5xx
    errors: Dict = {'type': 'Jenis dokumen tidak diperbolehkan'}
    """
    response_data = dict()

    if errors:
        errors_data = dict()
        for field in errors:
            errors_data[field] = errors[field][0]

        response_data['errors'] = errors_data

    if message:
        response_data['message'] = message

    if data:
        response_data['data'] = data

    return Response(status=status, data=response_data)
