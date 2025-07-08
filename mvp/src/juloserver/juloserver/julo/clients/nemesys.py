from builtins import object
import requests
import logging

from ..exceptions import JuloException

logger = logging.getLogger(__name__)


class JuloNemesysClient(object):
    """
    Julo Nemesys Client
    """

    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def update_email_delivery_status(self, request_data):
        api_url = self.base_url + '/deliveries/api/external/v1/callbacks/emails'
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.post(api_url, headers=headers, json=request_data)
        status_code = response.status_code
        logger.info({
            'action': 'update_email_delivery_status',
            'status_code': status_code
        })

        if status_code != 200:
            raise JuloException(
                "Failed update email delivery status nemesys, API status code %s" % status_code)

        return response

    def push_notification_api(self, request_data):
        """Redirect PN data to process in messaging service"""
        api_url = self.base_url + '/tracks/api/external/v1/record'

        logger_data = {
            'module': 'juloserver.julo.clients.nemesys',
            'action': 'push_notification_api',
            'request_data': request_data,
            'url': api_url,
        }
        headers = {
            'Authorization': self.token,
            'Content-Type': 'application/json'
        }

        logger.info({
            'message': 'Sending send Push Notification to Messaging service',
            **logger_data,
        })
        response = requests.post(api_url, headers=headers, json=request_data)
        status_code = response.status_code
        logger.info({
            'message': 'Finish send Push Notification to Messaging service',
            'status_code': status_code,
            **logger_data,
        })

        return response
