
from django.conf import settings

from .clients import DokuClient

def get_doku_client(token, systrace):
    return DokuClient(
        settings.DOKU_BASE_URL,
        settings.DOKU_CLIENT_ID,
        settings.DOKU_CLIENT_SECRET,
        settings.DOKU_SHARED_KEY,
        token,
        systrace
    )


default_app_config = 'juloserver.qris.apps.QrisConfig'
