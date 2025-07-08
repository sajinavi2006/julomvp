from builtins import object
import logging
import requests
import json

from requests.auth import HTTPBasicAuth
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)


class BukalapakClient(object):
    def __init__(self, username, secret_key):
        self.username = username
        self.secret_key = secret_key


    def approve_paylater(self, url, data):
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }

        logger.info({
            'action': "approve paylater callback",
            'url': url,
            'headers': headers
        })
        response = requests.post(
            url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, json=data)
        logger.info({
            'action': "result approve paylater callback",
            'response': response
        })
        if response.status_code != requests.codes.ok:
            raise JuloException(
                'approve paylater callback failed. result: %s' %
                (response.content)
            )
        return response
