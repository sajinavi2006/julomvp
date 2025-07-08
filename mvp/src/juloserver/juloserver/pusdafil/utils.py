import base64
from builtins import chr, object

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class PusdafilDataEncryptor(object):
    def __init__(self, key, iv, bs=16):
        self.bs = bs
        self.key = key
        self.iv = iv

    def __pad(self, data):
        return data + (self.bs - len(data) % self.bs) * chr(self.bs - len(data) % self.bs)

    def encrypt(self, data):
        raw = self.__pad(data)

        cipher = Cipher(
            algorithms.AES(self.key.encode("utf8")),
            modes.CBC(self.iv.encode("utf8")),
            default_backend(),
        )
        encryptor = cipher.encryptor()

        en = encryptor.update(raw.encode("utf8"))
        return base64.b64encode(base64.b64encode(en) + b'::' + self.iv.encode())


class CommonUtils(object):
    @staticmethod
    def get_error_message(message):
        return message.replace("[[\"", "").replace("\"]]", "").replace("[\"", "").replace("\"]", "")
