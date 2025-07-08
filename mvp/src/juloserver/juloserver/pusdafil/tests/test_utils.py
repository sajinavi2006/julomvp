import base64

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.test.testcases import TestCase

from juloserver.pusdafil.utils import CommonUtils, PusdafilDataEncryptor


@pytest.mark.django_db
class TestObjectPusdafilEncryptor(TestCase):
    def setUp(self):
        self.pusdafil_encryptor = PusdafilDataEncryptor(
            settings.PUSDAFIL_ENCRYPTION_KEY, settings.PUSDAFIL_ENCRYPTION_IV, 16
        )

        self.text = "Hello world"

    def test_encrypt_data(self):
        encrypted_result = self.pusdafil_encryptor.encrypt(self.text)

        result_io = base64.b64decode(encrypted_result)
        res_encrypt, res_iv = result_io.split(b'::')
        res_encrypt = base64.b64decode(res_encrypt)
        cipher = Cipher(
            algorithms.AES(settings.PUSDAFIL_ENCRYPTION_KEY.encode("utf8")),
            modes.CBC(settings.PUSDAFIL_ENCRYPTION_IV.encode("utf8")),
            default_backend(),
        )
        decryptor = cipher.decryptor()
        res_decrypt = decryptor.update(res_encrypt)
        res_decrypt = res_decrypt.decode('UTF-8')

        padding = '\x05' * 5  # Because of the text is 'Hello world'
        self.assertEqual(self.text + padding, res_decrypt)
        self.assertEqual(settings.PUSDAFIL_ENCRYPTION_IV, res_iv.decode('UTF-8'))

    def test_replace(self):
        expected_text = "Error Message"

        error_text = "[[\"%s\"]]" % expected_text

        replace_result = CommonUtils.get_error_message(error_text)

        self.assertEqual(expected_text, replace_result)

        error_text = "[\"%s\"]" % expected_text

        replace_result = CommonUtils.get_error_message(error_text)

        self.assertEqual(expected_text, replace_result)
