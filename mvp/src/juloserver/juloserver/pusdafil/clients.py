from __future__ import print_function

import json
from builtins import object

import requests
from django.conf import settings

from juloserver.pusdafil.utils import PusdafilDataEncryptor


class Object(object):
    pass


class PusdafilClient(object):
    def __init__(self, url, username, password, encryptor):
        self.url = url
        self.username = username
        self.password = password
        self.encryptor = encryptor

    def send(self, name, raw_data):
        try:
            response = requests.post(
                self.url,
                {name: self.encryptor.encrypt(json.dumps([raw_data]))},
                auth=(self.username, self.password),
            )

            response_content = json.loads(response.content)

            return response.status_code, response_content
        except Exception as e:
            raise e


def get_pusdafil_client():
    encryptor = PusdafilDataEncryptor(
        settings.PUSDAFIL_ENCRYPTION_KEY,
        settings.PUSDAFIL_ENCRYPTION_IV,
        settings.PUSDAFIL_ENCRYPTION_BS,
    )

    return PusdafilClient(
        settings.PUSDAFIL_URL, settings.PUSDAFIL_USERNAME, settings.PUSDAFIL_PASSWORD, encryptor
    )
