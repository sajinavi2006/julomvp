from typing import Dict

from rest_framework import status
from rest_framework.exceptions import APIException


class APIError(APIException):
    def __init__(self, status_code: int = None, detail: Dict = {}) -> None:
        self.status_code = status_code
        self.detail = detail


class APIInvalidFieldFormatError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = status.HTTP_400_BAD_REQUEST
        self.detail = detail


class APIMandatoryFieldError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = status.HTTP_400_BAD_REQUEST
        self.detail = detail


class APIUnauthorizedError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = status.HTTP_401_UNAUTHORIZED
        self.detail = detail
