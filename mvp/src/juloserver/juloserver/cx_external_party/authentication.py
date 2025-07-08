import typing
from datetime import datetime

from cryptography.fernet import InvalidToken
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from juloserver.cx_external_party.constants import ERROR_MESSAGE
from juloserver.cx_external_party.crypto import get_crypto
from juloserver.cx_external_party.models import CXExternalParty
from juloserver.cx_external_party.parser import APIKeyParser


class CXAPIKeyAuthentication(BaseAuthentication):
    model = CXExternalParty
    key_parser = APIKeyParser()

    def __init__(self):
        self.key_crypto = get_crypto()

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return self.key_parser.get(request)

    def authenticate(self, request, **kwargs):
        key = self.get_key(request)
        external_party, key = self._authenticate_credentials(request, key)
        request.external_party = external_party
        request.key = key

    def _authenticate_credentials(self, request, key):
        key_crypto = self.key_crypto
        today = timezone.localtime(timezone.now()).timestamp()

        try:
            payload = key_crypto.decrypt(key)
        except (ValueError, InvalidToken):
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.API_KEY_INVALID_DATA)

        if "_pk" not in payload or "_exp" not in payload:
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.API_KEY_INVALID_DATA)

        if payload["_exp"]:
            exp_date = datetime.strptime(payload["_exp"], "%Y-%m-%d %H:%M:%S").timestamp()
            if exp_date < today:
                raise exceptions.AuthenticationFailed(ERROR_MESSAGE.API_KEY_EXPIRED)
        try:
            external_party = self.model.objects.filter(id=payload["_pk"]).first()
        except ObjectDoesNotExist:
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.EXTERNAL_PARTY_NOT_FOUND)

        if not external_party.is_active:
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.EXTERNAL_PARTY_NOT_ACTIVE)

        return external_party, key


class CXUserTokenAuthentication(CXAPIKeyAuthentication):
    def authenticate(self, request, **kwargs):
        key = self.get_key(request)
        user_external_party = self._authenticate_user_token_credentials(request, key)
        external_party, key = self._authenticate_credentials(
            request, user_external_party["_api_key"]
        )
        request.user_external_party = user_external_party
        request.external_party = external_party

    def _authenticate_user_token_credentials(self, request, key):
        key_crypto = self.key_crypto
        today = timezone.localtime(timezone.now()).timestamp()

        try:
            user_token = key_crypto.decrypt(key)
        except (ValueError, InvalidToken):
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.USER_TOKEN_INVALID_DATA)

        if "_api_key" not in user_token and "_identifier" not in user_token:
            raise exceptions.AuthenticationFailed(ERROR_MESSAGE.USER_TOKEN_INVALID_DATA)

        if user_token["_exp"]:
            if user_token["_exp"] < today:
                raise exceptions.AuthenticationFailed(ERROR_MESSAGE.USER_TOKEN_EXPIRED)

        return user_token
