import logging
import time

import requests
from requests import HTTPError

from juloserver.ecommerce.constants import ORDER_TIMEOUT_SECONDS
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class JuloShopClient(object):

    ORDER_CONFIRMATION = '/v3/juloshop/order-confirmation'

    def __init__(self, base_url, juloshop_token):
        self.base_url = base_url
        self.juloshop_token = juloshop_token

    def _post(self, path, **kwargs):
        url = self.base_url + path
        headers = {"Authorization": "Token %s" % self.juloshop_token}
        logger_data = {
            'action': 'juloserver.ecommerce.clients.juloshop.JuloShopClient.post',
            'message': 'sending request to JuloShop',
            'request_url': url,
            'request_json': kwargs.get('json'),
            'request_params': kwargs.get('params'),
        }
        logger.info(logger_data)
        start_time = time.time()
        response = requests.post(url=url, json=kwargs['data'], headers=headers,
                                 timeout=ORDER_TIMEOUT_SECONDS)
        end_time = time.time()
        logger_data.update({
            'response_code': response.status_code,
            'response_body': response.text,
            'request_duration': round(end_time - start_time, 2)
        })
        logger.info(logger_data)
        response.raise_for_status()
        return response.json()

    def sent_order_confirmation(self, transaction_xid, application_xid):
        data = {
            "transaction_id": str(transaction_xid),
            "application_xid": str(application_xid),
        }
        try:
            response_data = self._post(path=self.ORDER_CONFIRMATION, data=data)
        except HTTPError as err:
            sentry_client.captureException()
            return False, err

        if response_data.get('orderCreated'):
            return True, None
        return False, response_data['errors']
