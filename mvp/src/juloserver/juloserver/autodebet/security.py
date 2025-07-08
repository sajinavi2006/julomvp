from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from django.conf import settings


class AutodebetBRIAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.META.get('HTTP_X_CALLBACK_TOKEN')

        if not token:
            raise exceptions.AuthenticationFailed('No token provided.')

        if token == settings.XENDIT_AUTODEBET_CALLBACK_TOKEN:
            return None
        raise exceptions.AuthenticationFailed('Invalid token.')
