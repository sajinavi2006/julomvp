import json
from time import sleep

import logging
import requests
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework.exceptions import ValidationError

from juloserver.ecommerce.serializers import InvoiceCallbackSerializer

logger = logging.getLogger(__name__)


class IpriceClient(object):
    INVOICE_CALLBACK_URI = '/v1/invoice-callback/julo'
    DEFAULT_RETRIES = 2

    def __init__(self, base_url, pid):
        self.base_url = base_url
        self.pid = pid

    def post(self, uri, retries=DEFAULT_RETRIES, **kwargs):
        url = self.base_url + uri

        response = None
        total_retry = 0
        while total_retry <= retries:
            logger_data = {
                'action': 'juloserver.loan.clients.iprice.iPriceClient.post',
                'message': 'sending request to iPrice',
                'retries': total_retry,
                'request_url': url,
                'request_json': kwargs.get('json'),
                'request_params': kwargs.get('params'),
            }
            logger.info(logger_data.copy())

            response = requests.post(url=url, **kwargs)
            logger_data.update(response_status=response.status_code, response_body=response.text)

            if response.status_code == 200:
                logger_data.update(message='iprice request success')
                logger.info(logger_data)
                return response.json()
            elif response.status_code < 500:
                logger_data.update(message='Request failed.')
                logger.error(logger_data)
                break

            logger_data.update(message='Retrying iPrice post request...')
            logger.warning(logger_data)
            total_retry += 1
            sleep(1)

        response.raise_for_status()
        return {}

    def post_invoice_callback(self, data, retries=DEFAULT_RETRIES):
        params = {'pid': self.pid}
        data = json.loads(json.dumps(data, cls=DjangoJSONEncoder))

        response_data = self.post(
            self.INVOICE_CALLBACK_URI,
            params=params,
            json=data,
            retries=retries
        )
        serializer = InvoiceCallbackSerializer(data=response_data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            logger.warning({
                'action': 'juloserver.loan.clients.iprice.iPriceClient.post_invoice_callback',
                'message': 'iPrice response validation error',
                'error': e.detail,
                'request_data': data,
                'response_data': response_data,
            })
            raise e
        return serializer.data
