from builtins import str
from builtins import object
import json
import logging

import requests

from ..exceptions import JuloException
from ..product_lines import ProductLineCodes


logger = logging.getLogger(__name__)


class JuloAppsFlyer(object):
    """Client SDK for interacting with AppsFlyer API"""

    def __init__(self, ios_client_id, client_id, api_key, base_url):
        self.ios_client_id = ios_client_id
        self.client_id = client_id
        self.api_key = api_key
        self.base_url = base_url

    def post_event(self, application, event_name, extra_params={}):
        client_id = self.client_id
        if application.is_julo_one_ios():
            client_id = self.ios_client_id

        url = self.base_url + client_id
        headers = {
            'authentication': self.api_key,
            'Content-type': 'application/json'
        }

        # extra_params : dict, can pass any extra key value pair with events
        if extra_params.get('credit_limit_balance'):
            extra_params['af_revenue'] = extra_params.get('credit_limit_balance')
            extra_params['af_currency'] = 'IDR'
            extra_params['af_content_type'] = 'Loan'

            extra_params.pop("credit_limit_balance")

        event_value_dict = {
            "application_xid": str(application.application_xid),
            "old_status": str(application.application_status.status_code),
            "customer_id": str(application.customer_id),
            **(extra_params or {})
        }

        data = {
            'appsflyer_id': application.customer.appsflyer_device_id,
            'advertising_id': application.customer.advertising_id,
            'eventName': event_name,
            'eventValue': json.dumps(event_value_dict),
            'af_events_api': 'true'
        }
        if application.customer.appsflyer_customer_id:
            data['customer_user_id'] = application.customer.appsflyer_customer_id
        logger.info({
            'action': 'post_appsflyer',
            'data': data,
            'application_id': application.id
        })
        response = requests.post(url, headers=headers, json=data)
        logger.info({
            'action': 'result_post_appsflyer',
            'data': data,
            'response_code': response.status_code,
            'application_id': application.id
        })

        if response.status_code != requests.codes.ok:
            raise JuloException(
                "Failed to notify AppsFlyer status change for "
                "application: %s (%s: %s)" % (
                    application.id, response.status_code, response.reason
                )
            )

        return response
