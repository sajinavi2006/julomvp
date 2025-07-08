from rest_framework.exceptions import APIException
from rest_framework import status

from typing import Dict


class APIForbiddenError(APIException):
    def __init__(self, detail: Dict = {}) -> None:
        self.status_code = status.HTTP_403_FORBIDDEN
        self.detail = detail
