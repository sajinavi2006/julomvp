from django.conf import settings

from .gopay import GopayClient


def get_gopay_client():
    return GopayClient(
        server_key = settings.GOPAY_SERVER_KEY,
        base_url = settings.GOPAY_BASE_URL,
        base_snap_url = settings.GOPAY_SNAP_BASE_URL
    )