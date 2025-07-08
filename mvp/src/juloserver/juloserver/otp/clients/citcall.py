import logging

import requests
from django.conf import settings
from rest_framework.status import HTTP_200_OK
from requests.exceptions import ConnectionError

from juloserver.otp.constants import CitcallApi

logger = logging.getLogger(__name__)


class CitcallClient:
    def __init__(self, host, api_key, backup_host, callback_url=None, session=None):
        self.host = host
        self.backup_host = backup_host
        self.api_key = api_key
        self.session = session if session else requests.Session()
        self.call_back_url = '{}{}'.format(settings.BASE_URL, callback_url or CitcallApi.CALLBACK)
        self.headers = self._generate_headers()

    def _generate_headers(self):
        return {'Authorization': 'Apikey %s' % self.api_key}

    def request_backup_miscall_otp(self, data):
        url = self.backup_host + CitcallApi.ASYNC_CALL
        response = self.session.post(url=url, json=data, headers=self.headers)
        status = response.status_code
        if status != HTTP_200_OK:
            logger.warning(
                'Backup Miscall otp request error|status={}, data={}.'.format(status, response.text)
            )
            return {}
        return response

    def request_otp(self, phone_number: str, retry: int, callback_id) -> dict:
        data = {
            'msisdn': phone_number,
            'retry': retry,
            'callback_url': self.call_back_url + callback_id,
        }
        logger.info('Miscall otp request|data={}'.format(data))
        url = self.host + CitcallApi.ASYNC_CALL
        retry_called = False

        try:
            response = self.session.post(url=url, json=data, headers=self.headers)
        except ConnectionError as exception:
            logger.warning(
                {
                    'action': 'citcall_client_request_otp',
                    'error': str(exception),
                    'phone_number': str(phone_number),
                }
            )
            response = self.request_backup_miscall_otp(data=data)
            retry_called = True

        status = response.status_code
        if status != HTTP_200_OK and not retry_called:
            logger.warning(
                {
                    'action': 'citcall_client_request_otp',
                    'error': 'Status not success',
                    'phone_number': str(phone_number),
                    'status': str(status),
                    'data': str(response.text),
                }
            )

            response = self.request_backup_miscall_otp(data=data)
        result = response.json()
        logger.info('Miscall otp request success|data={}'.format(result))
        return result
