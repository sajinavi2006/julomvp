import json
from copy import copy

from cryptography.fernet import Fernet
from django.conf import settings


class BaseApiCrypto:
    def encrypt(self, payload: str) -> str:
        return self.fernet.encrypt(payload.encode()).decode()

    def decrypt(self, key: str) -> dict:
        data = self.fernet.decrypt(key.encode()).decode()
        return json.loads(data)

    def generate(self, payload: dict) -> str:
        data = copy(payload)
        data["_exp"] = None if not data['_exp'] else data['_exp']

        api_key = self.encrypt(json.dumps(data))
        return api_key

    def assign_user_token(self, obj) -> str:
        data = {
            "_api_key": obj["api_key"],
            "_identifier": obj["identifier"],
            "_exp": obj["user_exp"],
        }
        key = self.generate(data)

        return data, key


class ApiCrypto(BaseApiCrypto):
    def __init__(self):
        fernet_key = settings.CX_FERNET_SECRET_KEY

        if fernet_key is None or fernet_key == "":
            raise KeyError("A CX Fernet Secret is not defined.")

        self.fernet = Fernet(fernet_key)


def get_crypto():
    return ApiCrypto()
