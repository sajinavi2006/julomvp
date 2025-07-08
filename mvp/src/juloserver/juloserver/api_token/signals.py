from django.conf import settings
from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from juloserver.julo.models import AuthUser
from .cache_client import get_token_cache
from .models import ExpiryToken


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def on_auth_user_updated(sender, instance=None, created=False, **kwargs):
    """A signal is caught after a user is created to create a api token for
    the user.
    """
    if not created and hasattr(instance, "auth_expiry_token"):
        token_cache = get_token_cache()
        token_cache.delete(instance.auth_expiry_token.key)


@receiver(post_save, sender=AuthUser)
def on_auth_user_pii_updated(sender, instance=None, created=False, **kwargs):
    """A signal is caught after a user is created to create a api token for
    the user.
    """
    if not created and hasattr(instance, "auth_expiry_token"):
        token_cache = get_token_cache()
        token_cache.delete(instance.auth_expiry_token.key)


@receiver(post_save, sender=ExpiryToken)
def on_expiry_token_updated(sender, instance=None, created=False, **kwargs):
    """A signal is caught after a user is created to create a api token for
    the user.
    """
    if not created:
        token_cache = get_token_cache()
        token_cache.delete(instance.initial_key)


@receiver(post_init, sender=ExpiryToken)
def before_expiry_token_updated(sender, instance=None, **kwargs):
    instance.initial_key = instance.key
