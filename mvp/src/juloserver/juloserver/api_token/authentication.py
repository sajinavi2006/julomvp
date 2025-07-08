from datetime import timedelta

import semver
from cuser.middleware import CuserMiddleware
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

from juloserver.julocore.cache_client import get_token_cache
from juloserver.api_token.constants import (
    EXPIRY_SETTING_KEYWORD,
    REFRESH_TOKEN_EXPIRY
)
from abc import ABC, abstractmethod
from typing import Dict, Any
import hashlib
from juloserver.api_token.exceptions import UnsupportedAlgoException
from juloserver.api_token.constants import REFRESH_TOKEN_MIN_APP_VERSION
from juloserver.api_token.models import ExpiryToken
from typing import Tuple, Union


def get_token_version_header(request):
    token_version = request.META.get('HTTP_TOKEN_VERSION', '')
    return token_version


class ExpiryTokenAuthentication(TokenAuthentication):
    model = ExpiryToken

    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return result

        user, expiry_token = result

        if not expiry_token.is_never_expire and not expiry_token.is_active:
            if get_token_version_header(request):
                expiry_token.is_active = True
                expiry_token.generated_time = timezone.localtime(timezone.now())
                expiry_token.save()
        app_version = request.META.get('HTTP_X_APP_VERSION')
        is_expired, _expire_on = is_expired_token(expiry_token, app_version)
        if is_expired:
            raise exceptions.AuthenticationFailed('Token Expired')

        CuserMiddleware.set_user(user)
        return user, expiry_token

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = get_expiry_token(key, model)
        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(_('Invalid token.'))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_('User inactive or deleted.'))

        return (token.user, token)


def is_expired_token(expiry_token: ExpiryToken, app_version: str = None) \
        -> Tuple[Union[bool, None], Union[timedelta, None]]:
    """
    Used to check the token has been expired or not.
    If not will calculate the expiry time.

    Args:
        expiry_token param : The ExpiryToken obj
        app_version param : Gets the app_version from request

    Returns:
        tuple: A tuple containing the processed boolean value and the timedelta obj.
    """
    expiry_range = get_expiry_range()
    expiry_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING, is_active=True
    )
    if expiry_setting and expiry_setting.parameters:
        refresh_token_min_app_version = expiry_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
    else:
        refresh_token_min_app_version = None

    if (app_version and refresh_token_min_app_version
            and semver.match(app_version, "<{}".format(refresh_token_min_app_version))):
        return None, None  # Expiry Token from the old app version will not be expired.

    if not expiry_token.is_never_expire and expiry_token.is_active and expiry_range is not None:
        expiry_time = timezone.localtime(expiry_token.generated_time + expiry_range)
        time_now = timezone.localtime(timezone.now())
        next_2am = expiry_time + relativedelta(
            hour=2, minute=0, second=0, days=(expiry_time.hour >= 2)
        )
        if time_now > next_2am:
            return True, None
        return False, next_2am - time_now

    return None, None


def get_expiry_range():
    expiry_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING, is_active=True
    )
    if expiry_setting and expiry_setting.parameters:
        expiry_hours = expiry_setting.parameters.get(EXPIRY_SETTING_KEYWORD)
        if isinstance(expiry_hours, int):
            return timedelta(hours=expiry_hours)

    return None


def generate_new_token(user):
    expiry_token = ExpiryToken.objects.get(user=user)
    if expiry_token.is_active and not expiry_token.is_never_expire:
        if get_expiry_range():
            expiry_token.key = expiry_token.generate_key()
        expiry_token.generated_time = timezone.localtime(timezone.now())
        expiry_token.save()

    return expiry_token.key


def make_never_expiry_token(user):
    expiry_token = ExpiryToken.objects.get(user=user)
    expiry_token.is_never_expire = True
    expiry_token.save()


def get_expiry_token(key, model=ExpiryToken):
    token_cache = get_token_cache()
    token = token_cache.get(key)

    if not token:
        token = model.objects.select_related('user').get(key=key)
        if token:
            token_cache.set(key, token)

    return token


class WebToken(ABC):
    _supported_algorithm = {'HS256': hashlib.sha256}

    def is_supported_algorithm(self, name: str) -> bool:
        name = name.upper()
        if name in self._supported_algorithm.keys():
            return True
        return False

    def get_algorithm_by_name(self, name: str):
        name = name.upper()
        if self.is_supported_algorithm(name):
            algorithm = self._supported_algorithm[name]
        else:
            raise UnsupportedAlgoException("Upsupported algorithm {}".format(name))
        return algorithm

    @abstractmethod
    def encode(self) -> str:
        pass

    @abstractmethod
    def decode(self) -> Dict[str, Any]:
        pass


def generate_new_token_and_refresh_token(user):
    """
    Function to generate:
    Expiry token  - short-lived token
    Refresh Token - long-lived token.
    """
    expiry_token = ExpiryToken.objects.get(user=user)
    expiry_token.refresh_key = expiry_token.generate_key()
    expiry_token.key = expiry_token.generate_key()
    expiry_token.generated_time = timezone.localtime(timezone.now())
    expiry_token.save()

    return expiry_token.key, expiry_token.refresh_key


def get_refresh_token_expiry_range():
    expiry_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING, is_active=True
    )
    if expiry_setting and expiry_setting.parameters:
        expiry_hours = expiry_setting.parameters.get(REFRESH_TOKEN_EXPIRY)
        if expiry_hours:
            return relativedelta(hours=int(expiry_hours))

    return None


class RefreshTokenAuthentication(TokenAuthentication):
    model = ExpiryToken

    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return result

        user, expiry_token = result

        if not expiry_token.is_never_expire and not expiry_token.is_active:
            if get_token_version_header(request):
                expiry_token.is_active = True
                expiry_token.generated_time = timezone.localtime(timezone.now())
                expiry_token.save()

        is_expired, _expire_on = is_expired_refresh_token(expiry_token)
        if is_expired:
            raise exceptions.AuthenticationFailed('Token Expired')

        CuserMiddleware.set_user(user)
        return user, expiry_token

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = get_refresh_token(key, model)
        except model.DoesNotExist:
            # handle upgrade process, expecting expiry token as a refresh token
            try:
                token = get_expiry_token(key, model)
            except model.DoesNotExist:
                raise exceptions.AuthenticationFailed(_('Invalid token.'))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_('User inactive or deleted.'))

        return (token.user, token)


def is_expired_refresh_token(expiry_token):
    expiry_range = get_refresh_token_expiry_range()
    if not expiry_token.is_never_expire and expiry_token.is_active and expiry_range is not None:
        expiry_time = timezone.localtime(expiry_token.generated_time + expiry_range)
        time_now = timezone.localtime(timezone.now())
        next_2am = expiry_time + relativedelta(
            hour=2, minute=0, second=0, days=(expiry_time.hour >= 2)
        )
        if time_now > next_2am:
            return True, None
        return False, next_2am - time_now

    return None, None


def get_refresh_token(key, model=ExpiryToken):
    return model.objects.select_related('user').get(refresh_key=key)
