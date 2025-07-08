import requests
from django.conf import settings
from requests import Response


def get_seon_client():
    return SeonClient(
        base_url=settings.SEON_API_BASE_URL,
        license_key=settings.SEON_API_LICENSE_KEY,
    )


class SeonClient:
    """
    Class to communicate with SEON API:
    https://docs.seon.io/api-reference
    """
    FRAUD_API_ENDPOINT = '/SeonRestService/fraud-api/v2.0/'

    def __init__(self, base_url, license_key):
        self.base_url = base_url
        self.license_key = license_key

    def fetch_fraud_api(self, payload) -> Response:
        """
        Fetch the fraud API result from  SEON.
        """
        url = self.base_url + self.FRAUD_API_ENDPOINT
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-API-KEY': self.license_key,
        }
        response = requests.post(url, headers=headers, json=payload)
        return response
