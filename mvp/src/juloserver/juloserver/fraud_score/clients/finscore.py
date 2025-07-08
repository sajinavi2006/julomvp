import logging
from typing import (
    Dict,
    Optional,
    Tuple,
)

import requests
from requests import (
    RequestException,
    Response,
)

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class FinscoreClient:
    def __init__(self, partner_code=None, partner_key=None, host_url=None):
        if not partner_code:
            raise ValueError('Missing configuration "partner_code".')
        if not partner_key:
            raise ValueError('Missing configuration "partner_key".')
        if not host_url:
            raise ValueError('Missing configuration "host_url".')

        self.partner_code = partner_code
        self.partner_key = partner_key
        self.host_url = host_url

    def construct_payload(self, data: Dict) -> Dict:
        """
        Process the given data into payload for Finscore API.

        Args:
            data (Dict): Data to be processed.

        Returns:
            Dict: Constructed payload.
        """
        payload = {
            'apply_time': data['apply_time'],
            'id_num': data['id'],
            'act_mbl': data['phone_number'],
            'full_nm': data['fullname'],
            'app_name': 'JuloTek_and',  # Need to reconfirm with TG
            'package_id': 'finscore5.1',
        }

        if data.get('device_id'):
            payload.update({'device_id': data['device_id']})

        return payload

    def fetch_finscore_result(self, data: Dict) -> Tuple[Optional[Response], bool]:
        """
        Hit Trust Decision's API to fetch Finscore scoring.

        Args:
            data (Dict): Data expected to be processed as payload.

        Returns:
            Optional[Response]: Response object from Trust Decision.
            bool: True if the fetching process is successful.
        """
        headers = {
            'Content-Type': 'application/json',
        }
        params = {
            'partner_code': self.partner_code,
            'partner_key': self.partner_key,
        }

        try:
            finscore_payload = self.construct_payload(data)

            response = requests.post(
                '{}/Carpo/query/v1'.format(self.host_url),
                headers=headers, params=params, json=finscore_payload
            )
            response.raise_for_status()

            return response, False
        except RequestException as e:
            logger.exception({
                'action': 'fetch_finscore_result',
                'message': 'HTTP requests exception detected.',
                'error': e,
                'application_id': data['application_id'],
            })

            return None, True
        except Exception as e:
            sentry_client.captureException()
            logger.exception({
                'action': 'fetch_finscore_result',
                'message': 'Unexpected error during Finscore score retrieval.',
                'error': e,
                'application_id': data['application_id'],
            })

            return None, True
