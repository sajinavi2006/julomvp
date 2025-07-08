from __future__ import unicode_literals

import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.models import AuthUser

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def on_auth_user_created(sender, instance=None, created=False, **kwargs):
    """A signal is caught after a user is created to create a api token for
    the user.
    """
    if created:
        Token.objects.create(user=instance)
        logger.info({'message': "Token generated", 'user': instance})


@receiver(post_save, sender=AuthUser)
def on_auth_user_pii_created(sender, instance=None, created=False, **kwargs):
    """A signal is caught after a user is created to create a api token for
    the user.
    """
    if created:
        Token.objects.create(user=instance)
        logger.info({'message': "Token generated", 'user': instance})
