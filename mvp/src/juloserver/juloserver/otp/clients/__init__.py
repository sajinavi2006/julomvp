import logging
import requests

from django.conf import settings


logger = logging.getLogger(__name__)


def get_julo_otpless_client():
    from .otpless import JuloOTPLessClient

    return JuloOTPLessClient(settings.JULO_OTPLESS_CLIENT_ID, settings.JULO_OTPLESS_CLIENT_SECRET)


def get_citcall_client():
    from .citcall import CitcallClient

    return CitcallClient(
        host=settings.CITCALL_URL,
        api_key=settings.CITCALL_API_KEY,
        backup_host=settings.CITCALL_BACKUP_URL,
        callback_url=None,
        session=requests.Session(),
    )
