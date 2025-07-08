from __future__ import absolute_import
from builtins import str
from builtins import range
import logging
import uuid

from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (EmailHistory,
                                    FeatureSetting,
                                    SmsHistory)
from juloserver.magic_link.models import MagicLinkHistory
from juloserver.urlshortener.services import shorten_url
from juloserver.magic_link.constants import MagicLinkStatus

logger = logging.getLogger(__name__)


def get_magic_link_expiry_time():
    feature_settings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MAGIC_LINK_EXPIRY_TIME,
        is_active=True
    ).last()

    if feature_settings is not None and feature_settings.parameters:
        return feature_settings.parameters

    return None


def generate_magic_link():
    magic_link_landing_url = settings.MAGIC_LINK_BASE_URL + '{hash_token}'

    magic_link_expiry_time = get_magic_link_expiry_time()
    if magic_link_expiry_time is not None:
        token = str(uuid.uuid4().hex)
        expiry_time = timezone.localtime(timezone.now()) + \
                      timedelta(minutes=magic_link_expiry_time)
        magic_link_url = magic_link_landing_url.format(hash_token=token)
        short_url, short_url_obj = shorten_url(magic_link_url, get_object=True)

        magic_link_history = MagicLinkHistory.objects.create(
            token=token,
            expiry_time=expiry_time,
            status=MagicLinkStatus.UNUSED)

        return short_url, magic_link_history

    return None, None


def is_valid_magic_link_token(token):
    now = timezone.localtime(timezone.now())
    magic_link_history = MagicLinkHistory.objects.filter(
        token=token,
        status=MagicLinkStatus.UNUSED,
        expiry_time__gte=now
    ).order_by("cdate").last()

    if magic_link_history:
        magic_link_history.status = MagicLinkStatus.USED
        magic_link_history.save()
        return True
    else:
        # check if magic link expired and mark status
        mark_magic_link_expired(token)

        return False

def mark_magic_link_expired(token):
    now = timezone.localtime(timezone.now())
    magic_link_history = MagicLinkHistory.objects.filter(
        token=token,
        status__in=[MagicLinkStatus.UNUSED, MagicLinkStatus.EXPIRED],
        expiry_time__lte=now
    ).order_by("cdate").last()

    if magic_link_history:
        if magic_link_history.status == MagicLinkStatus.UNUSED:
            magic_link_history.status = MagicLinkStatus.EXPIRED
            magic_link_history.save()
        return True

    return False


def check_if_magic_link_verified(application, magic_link_type):
    now = timezone.localtime(timezone.now())
    if magic_link_type == "email":
        magic_link_history = MagicLinkHistory.objects.filter(email_history__application=application).\
            order_by("cdate").last()
    else:
        magic_link_history = MagicLinkHistory.objects.filter(sms_history__application=application).\
            order_by("cdate").last()

    if magic_link_history:
        if magic_link_history.status == MagicLinkStatus.USED:        
            return "verified"
        if magic_link_history.status == MagicLinkStatus.EXPIRED:        
            return "expired"

        is_expired = mark_magic_link_expired(magic_link_history.token)
        return "expired" if is_expired else "not-verified"

    return
