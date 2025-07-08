from django.conf import settings

from juloserver.omnichannel.clients.omnichannel_http import OmnichannelHTTPClient


def get_omnichannel_http_client() -> OmnichannelHTTPClient:
    """
    Get the http client for omnichannel
    """
    return OmnichannelHTTPClient(
        base_url=settings.OMNICHANNEL_BASE_URL,
        token=settings.OMNICHANNEL_TOKEN,
    )
