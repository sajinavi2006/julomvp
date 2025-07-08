import typing

from django.http import HttpRequest
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from juloserver.cx_external_party.constants import (
    AUTHENTICATION_KEYWORD_HEADER,
    ERROR_MESSAGE,
)


class APIKeyParser:
    """
    This is a parser used to retrieve the API Key from the
    authorization header.
    """

    keyword = AUTHENTICATION_KEYWORD_HEADER

    def get(self, request: HttpRequest) -> typing.Optional[str]:

        return self.get_from_authorization(request)

    def get_from_authorization(self, request: HttpRequest) -> typing.Optional[str]:
        authorization = request.META.get("HTTP_AUTHORIZATION")

        if not authorization:
            raise NotAuthenticated(ERROR_MESSAGE.API_KEY_NOT_PROVIDED)

        try:
            _, key = authorization.split(f"{self.keyword} ")
        except ValueError:
            raise AuthenticationFailed(ERROR_MESSAGE.API_KEY_INCORRECT_FORMAT)

        return key

    def get_from_header(self, request: HttpRequest, name: str) -> typing.Optional[str]:
        return request.META.get(name) or None
