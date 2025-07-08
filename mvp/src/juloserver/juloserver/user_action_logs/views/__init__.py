from django.conf import settings

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


class UserActionLogAuthentication(TokenAuthentication):
    def authenticate(self, request):
        token = request.META.get('HTTP_AUTHORIZATION')
        if not token:
            raise exceptions.AuthenticationFailed('Forbidden request, invalid token')

        if token != 'Token %s' % settings.USER_ACTION_LOG_TOKEN:
            raise exceptions.AuthenticationFailed('Forbidden request, invalid token')
        # mock user to ana_server user
        user = User()
        return user, None
