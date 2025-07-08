import json
from builtins import object

import requests

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julolog.julolog import JuloLog

sentry = get_julo_sentry_client()


class HEREMapsClient(object):
    """Client SDK for interacting with HERE Maps API"""

    def __init__(self, api_key, api_url):
        self.api_key = api_key
        self.api_url = api_url
        self.logger = JuloLog()

    def get_geocoding_response_by_address(self, enconded_address):
        params = {'q': enconded_address, 'apiKey': self.api_key}
        ret = requests.get(self.api_url, params=params)
        if ret.status_code != 200:
            sentry.captureMessage(
                'Failed to hit HERE API with status code: {}'.format(ret.status_code)
            )
            return None, None
        results = ret.json()['items']
        if not results:
            self.logger.info({"message": "Failed to get results from HERE API"})
            return None, None
        coordinates = results[0]['position']
        geocoding_response = json.dumps(ret.json())
        return coordinates, geocoding_response

    def get_reverse_geocode_by_coordinates(self, latitude, longitude):
        params = {
            'at': '{},{}'.format(latitude, longitude),
            'lang': 'en-US',
            'apiKey': self.api_key,
        }
        ret = requests.get("https://revgeocode.search.hereapi.com/v1/revgeocode", params=params)
        if ret.status_code != 200:
            sentry.captureMessage(
                'Failed to hit HERE API with status code: {}'.format(ret.status_code)
            )
            return None
        results = ret.json()['items']
        return results[0]
