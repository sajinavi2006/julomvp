import base64

from typing import Dict
from django.conf import settings

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization

from juloserver.dana.utils import create_string_to_sign


def is_valid_x_signature(signature: str, string_to_sign: str) -> bool:
    try:
        bytes_signature = signature.encode('utf-8')
        decode_signature = base64.b64decode(bytes_signature)

        public_key = serialization.load_pem_public_key(
            bytes(settings.DANA_X_SIGNATURE_PUBLIC_KEY_REQUEST, 'utf-8'),
            backend=default_backend(),
        )

        public_key.verify(
            decode_signature, string_to_sign.encode('utf-8'), padding.PKCS1v15(), hashes.SHA256()
        )
    except Exception:
        return False

    return True


def validation_signature(
    method: str, path: str, payload: Dict, timestamp: str, signature: str
) -> bool:

    string_to_sign = create_string_to_sign(method, path, payload, timestamp)

    if not is_valid_x_signature(signature, string_to_sign):
        return False

    return True
