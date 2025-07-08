from django.conf import settings
from juloserver.antifraud.client.http_client import HTTPClient


def get_anti_fraud_http_client() -> HTTPClient:
    return HTTPClient(
        settings.ANTI_FRAUD_BASE_URL,
    )
