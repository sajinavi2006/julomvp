from typing import Dict
from rest_framework.exceptions import APIException


class APIError(APIException):

    def __init__(self, status_code: int = None, detail: Dict = {}) -> None:
        self.status_code = status_code
        self.detail = detail


class LockAquisitionError(Exception):
    pass


class FailedUploadImageException(Exception):
    pass
