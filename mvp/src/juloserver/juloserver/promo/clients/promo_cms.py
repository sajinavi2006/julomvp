import logging
import requests
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.promo.constants import DEFAULT_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class PromoCMSClient(object):

    PROMO_LIST = '/api/julo_rest/promolist'

    def __init__(self, base_url):
        self.base_url = base_url

    def _get(self, path, **kwargs):
        url = self.base_url + path
        response = requests.get(url=url, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()

    def promo_list(self):
        response = self._get(path=self.PROMO_LIST)
        return response['data']
