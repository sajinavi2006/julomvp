import jwt
from django.conf import settings
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from jwt import InvalidTokenError
from rest_framework.authentication import (
    BaseAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission


class AnySourceAuthentication(BaseAuthentication):
    """
    Authentication class for any source.

    Note:
    The class name is used as the issuer. So renaming the class will invalidate all existing tokens.
    """

    def authenticate(self, request):
        token = self.get_bearer_token(request)
        try:
            decoded_token = self.decode_token(token)
            source = decoded_token.get('source')
            if not source:
                raise AuthenticationFailed(_('Invalid token.'))

            whitelisted_sources = self.whitelisted_sources()
            if whitelisted_sources is not None and source not in self.whitelisted_sources():
                raise AuthenticationFailed(_('Invalid token.'))

            request.request_source = source
            return None, None
        except InvalidTokenError as e:
            raise AuthenticationFailed(_('Invalid token.'))

    @staticmethod
    def get_bearer_token(request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != b'bearer' or len(auth) == 1:
            msg = _('No credentials provided.')
            raise AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = _('Invalid token.')
            raise AuthenticationFailed(msg)

        try:
            return auth[1].decode()
        except UnicodeError:
            msg = _('Invalid token.')
            raise AuthenticationFailed(msg)

    @classmethod
    def issuer(cls) -> str:
        return "{}.{}".format(settings.ENVIRONMENT.upper(), cls.__name__)

    @classmethod
    def generate_token(cls, source: str) -> str:
        payload = {
            'source': source,
            'iat': int(timezone.now().timestamp()),
            'iss': cls.issuer(),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm='HS256').decode('utf-8')

    @classmethod
    def decode_token(cls, token: str, verify=True) -> dict:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            verify=verify,
            algorithms=['HS256'],
            issuer=cls.issuer(),
        )

    def whitelisted_sources(self):
        """
        Return list of Whitelisted sources, None if all sources are allowed
        """
        return None


class IsSourceAuthenticated(BasePermission):
    """
    Permission class to check if the request is authenticated by a source.
    """

    def has_permission(self, request, view):
        return hasattr(request, 'request_source')


class CommProxyAuthentication(AnySourceAuthentication):
    OMNICHANNEL = "omnichannel"

    def whitelisted_sources(self):
        return [
            self.OMNICHANNEL,
        ]
