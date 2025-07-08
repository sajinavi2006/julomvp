from builtins import str
from builtins import object
import logging
from typing import List, Dict
from enum import Enum
import requests
import json
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.exceptions import JuloException
from datetime import timedelta, datetime

logger = logging.getLogger(__name__)


class FieldCollectionErrorCodes(Enum):
    INTERNAL_SERVER_ERROR = ("500000R", "internal server error", "internal server error")

    def __init__(self, code, message, description):
        self._code = code
        self._message = message
        self._description = description

    @property
    def code(self):
        return self._code

    @property
    def message(self):
        return self._message

    @property
    def description(self):
        return self._description


ERROR_MAPPING_CODE = {
    "2000000": None,  # This is a placeholder for successful response
    "500000R": FieldCollectionErrorCodes.INTERNAL_SERVER_ERROR,
}


class FieldCollectionClient(object):
    '''
    Field Collection is part of JULO service related to field collection.
    '''

    COLLECTION_RECOMMENDED_CONNECT_TIMEOUT = 60
    COLLECTION_RECOMMENDED_READ_TIMEOUT = 60

    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def _make_request(self, method: str, url: str, retry_count=0, **kwargs):
        response = None
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Token ' + self.api_key,
            }
            response = requests.request(method, url, headers=headers, **kwargs)

            if response.status_code != 200:
                logger.info(
                    {
                        'action': 'FieldCollectionClient._make_request',
                        'message': 'raw response from field collection',
                        'data': json.loads(response.text),
                    }
                )

            return response
        except Exception as e:
            raise JuloException(e)

    def get_similar_active_agents(self, fullname):
        url = self.base_url + 'api/v1/user/agents'
        payload = {"page": "1", "page_size": "20", "user_statuses": "active", "fullname": fullname}
        data = {}
        response = self._make_request(
            "POST",
            url,
            data=json.dumps(payload),
            timeout=(
                self.COLLECTION_RECOMMENDED_CONNECT_TIMEOUT,
                self.COLLECTION_RECOMMENDED_READ_TIMEOUT,
            ),
        )
        if response.status_code == 200:
            response_json = response.json()
            data = response_json['data']
        else:
            logger.error({'action': 'get_similar_active_agents', 'fullname': fullname})

        return data
