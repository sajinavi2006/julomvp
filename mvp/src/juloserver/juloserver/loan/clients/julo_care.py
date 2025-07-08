from builtins import object
from builtins import str

import logging
import requests

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)

RTO_IN_SEC = 60


class JULOCaresClient(object):
    def __init__(self, base_url):
        self.base_url = base_url

    def send_request(self, request_path, request_type, data=None, params=None, json=None):
        """
        Send API request to JULO Cares Client
        :param request_path: JULO Cares route url
        :param request_type: Request type [get, post]
        :param data: Dictionary contains data using for requests body usually using by [POST]
        :param params: Dictionary contains data using for requests params usually using by [GET]
        :param json: JSON contains data using for requests body usually using by [POST]
        :return: object response.json
        """
        request_params = dict(
            url=self.base_url + request_path,
            data=data,
            params=params,
            json=json,
            timeout=RTO_IN_SEC,
        )
        logger_dict = {
            'action': 'JULOCaresClient.send_request - [{}] {}'.format(request_type, request_path),
            'request_params': request_params,
        }

        try:
            if request_type == "post":
                response = requests.post(**request_params)
            else:
                response = requests.get(**request_params)
            return_response = response.json()
            logger_dict.update(
                {
                    'response_status': response.status_code,
                    'request': response.request.__dict__,
                }
            )
            response.raise_for_status()
        except Exception as error:
            get_julo_sentry_client().captureException()
            error_message = str(error)
            return_response = {'success': False, 'message': error_message}
            logger_dict.update({'error': error_message})

        logger_dict.update({'response': return_response})
        logger.info(logger_dict)

        return return_response
