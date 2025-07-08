from juloserver.julo.exceptions import JuloException
from rest_framework.exceptions import APIException
from rest_framework import status

from typing import Dict


class PartnershipWebviewException(JuloException):
    pass


class LinkAjaClientException(JuloException):
    pass


class APIUnauthorizedError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = status.HTTP_401_UNAUTHORIZED
        self.detail = detail


class APIError(APIException):
    def __init__(self, status_code: int = None, detail: Dict = {}) -> None:
        self.status_code = status_code
        self.detail = detail
