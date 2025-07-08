import requests
import logging
import ipinfo
from django.conf import settings
from juloserver.loan.exceptions import JuloException

logger = logging.getLogger(__name__)


class IPInfoClient:

    def __init__(self, host, api_token, session=None):
        self.host = host
        self.api_token = api_token
        self.session = session or requests.Session()

    def get_ip_info_detail(self, ip_address):
        """
            Default time out request is 10 seconds
            Can set the cache config when initializing getHandler
            Sample response
            {
                "ip": "118.137.237.132",
                "hostname": "fm-dyn-118-137-237-132.fast.net.id",
                "city": "Jakarta",
                "region": "Jakarta",
                "country": "ID",
                "loc": "-6.2146,106.8451",
                "org": "AS23700 Linknet-Fastnet ASN",
                "timezone": "Asia/Jakarta",
                "privacy": {
                    "vpn": true,
                    "proxy": false,
                    "tor": false,
                    "hosting": false
                }
            }
        """
        handler = ipinfo.getHandler(self.api_token)
        details = handler.getDetails(ip_address, timeout=10)

        logger.info('check ip response success|data={}'.format(details.details))

        return details.details


def get_ipinfo_client():
    host = settings.IPINFO_HOST
    api_token = settings.IPINFO_API_TOKEN
    client = IPInfoClient(host, api_token)

    return client
