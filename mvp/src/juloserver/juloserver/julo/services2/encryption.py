from builtins import str
from builtins import object
from cryptography.fernet import Fernet
import base64
from django.conf import settings
import hashlib
from Crypto import Random
from Crypto.Cipher import AES
from base64 import b64encode, b64decode


class Encryption(object):

    def decode_string(self, input_string):
        cipher_suite = Fernet(settings.CRYPTOGRAPHY_KEY)
        try:
            decoded_input_string = base64.b64decode(input_string)
            return cipher_suite.decrypt(decoded_input_string).decode()
        except:
            return False


    def encode_string(self, input_string):
        cipher_suite = Fernet(settings.CRYPTOGRAPHY_KEY)
        return base64.b64encode(cipher_suite.encrypt(input_string.encode())).decode()


class AESCipher(object):
    def __init__(self, key):
        self.block_size = AES.block_size
        self.key = hashlib.sha256(key.encode()).digest()

    def encrypt(self, plain_text):
        plain_text = self.__pad(plain_text)
        iv = Random.new().read(self.block_size)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        encrypted_text = cipher.encrypt(plain_text.encode())
        return b64encode(iv + encrypted_text).decode("utf-8")

    def decrypt(self, encrypted_text):
        encrypted_text = b64decode(encrypted_text)
        iv = encrypted_text[:self.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        plain_text = cipher.decrypt(encrypted_text[self.block_size:]).decode("utf-8")
        return self.__unpad(plain_text)

    def __pad(self, plain_text):
        number_of_bytes_to_pad = self.block_size - len(plain_text) % self.block_size
        ascii_string = chr(number_of_bytes_to_pad)
        padding_str = number_of_bytes_to_pad * ascii_string
        padded_plain_text = plain_text + padding_str
        return padded_plain_text

    @staticmethod
    def __unpad(plain_text):
        last_character = plain_text[len(plain_text) - 1:]
        return plain_text[:-ord(last_character)]
