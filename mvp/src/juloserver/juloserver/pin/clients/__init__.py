import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def get_julo_pin_email_client():
    from .email import JuloPinEmailClient

    return JuloPinEmailClient(settings.SENDGRID_API_KEY, settings.EMAIL_FROM)


def get_julo_pin_sms_client():
    from .sms import JuloPinSmsClient

    return JuloPinSmsClient()
