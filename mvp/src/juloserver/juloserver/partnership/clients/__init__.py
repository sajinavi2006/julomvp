# This File copied from juloserver/julo/clients/__init__.py

import logging

from django.conf import settings


logger = logging.getLogger(__name__)


def get_julo_sentry_client(module_name=None):
    from raven.contrib.django.raven_compat.models import client
    client.tags_context({'domain': settings.SERVICE_DOMAIN})
    return client


def get_partnership_email_client():
    from .email import PartnershipEmailClient

    return PartnershipEmailClient(
        settings.SENDGRID_API_KEY,
        settings.EMAIL_FROM
    )
