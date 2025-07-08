from builtins import object
import logging
from hashlib import md5

import requests
import time
import math
import json

from django.conf import settings
from requests.auth import HTTPBasicAuth
from juloserver.moengage.exceptions import MoengageApiError
from juloserver.moengage.constants import MAX_RETRY, MAX_RETRY_FOR_TIMEOUT


logger = logging.getLogger(__name__)


def get_julo_moengage_client():
    return MoEngageClient(
        settings.MOENGAGE_API_ID,
        settings.MOENGAGE_API_KEY,
        settings.MOENGAGE_API_BASE_URL
    )


class MoEngageClient(object):
    def __init__(self, data_api_id, data_api_key, api_base_url):
        self.data_api_id = data_api_id
        self.data_api_key = data_api_key
        self.api_base_url = api_base_url

    def send_event(self, elements, retry_count=0, timeout_retry_count=0):
        headers = {
            'Content-type': 'application/json'
        }
        url = '{}transition/{}'.format(self.api_base_url, self.data_api_id)
        data = {
            "type": "transition",
        }
        param = {
            "elements": elements
        }
        data.update(param)

        logger_data = {
            'action': "send_event_data_to_moengage",
            'data_hash': md5(json.dumps(elements).encode()).hexdigest(),
            'total_element': len(elements),
            'retry_count': str(retry_count),
            'timeout_retry_count': str(timeout_retry_count)
        }
        logger.info({
            "message": "sending data to moengage",
            **logger_data,
            'url': url,
            'data': data,
            'headers': headers,
        })

        try:
            response = requests.post(
                url, auth=HTTPBasicAuth(self.data_api_id, self.data_api_key),
                headers=headers, json=data, timeout=60)

            logger.info({
                'message': "result send_event_data_to_moengage",
                **logger_data,
                'response': response.content
            })
        except requests.exceptions.Timeout:
            logger.error({
                'message': 'API Timeout',
                **logger_data
            })

            # retry for API timeout
            if timeout_retry_count > MAX_RETRY_FOR_TIMEOUT:
                raise MoengageApiError(
                    'send_event_data_to_moengage failed due to API timeout')

            logger.info({
                'message': "Retry for timeout",
                **logger_data
            })
            timeout_retry_count += 1
            time.sleep(60 * math.pow(2, timeout_retry_count))
            return self.send_event(
                elements, retry_count=retry_count, timeout_retry_count=timeout_retry_count)

        # retry for status 503
        if response.status_code == requests.status_codes.codes.service_unavailable:
            if retry_count > MAX_RETRY:
                raise MoengageApiError(
                    'send_event_data_to_moengage failed. result: %s' % (response.content))

            logger.info({
                'message': 'retry for network error code {}'.format(response.status_code),
                'response_status_code': response.status_code,
                **logger_data
            })
            time.sleep(60)
            retry_count += 1
            return self.send_event(
                elements, retry_count=retry_count, timeout_retry_count=timeout_retry_count)

        # retry for status 502, 404
        if response.status_code in [404, 502]:
            if timeout_retry_count > MAX_RETRY_FOR_TIMEOUT:
                raise MoengageApiError(
                    'send_event_data_to_moengage with status code:{} maximum retries. '
                    'result:{}'.format(response.status_code, response.content))

            logger.info({
                'message': 'retry for network error code {}'.format(response.status_code),
                'response_status_code': response.status_code,
                **logger_data
            })
            timeout_retry_count += 1
            time.sleep(60 * math.pow(2, timeout_retry_count))
            return self.send_event(
                elements, retry_count=retry_count, timeout_retry_count=timeout_retry_count)

        if response.status_code not in [requests.codes.ok]:
            raise MoengageApiError(
                'send_event_data_to_moengage failed. result: %s' %
                (response.content)
            )

        return response.json()
