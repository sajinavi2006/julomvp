from typing import Any

from juloserver.employee_financing.models import EmFinancingWFAccessToken
from juloserver.employee_financing.utils import decode_jwt_token
from juloserver.employee_financing.constants import ErrorMessageConstEF

from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from juloserver.employee_financing.exceptions import APIError


class EmployeeFinancingAuthentication(BaseAuthentication):
    """
        Simple JSON Web token based authentication.
        Authenticate using key JWT.
    """

    def authenticate(self, request: Request) -> Any:
        error_message = {
            'token': ErrorMessageConstEF.INVALID_TOKEN
        }

        try:
            auth = request.META['HTTP_AUTHORIZATION'] or None
        except KeyError:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        if auth is None:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        if not 'Bearer' in auth:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        try:
            token = auth.split('Bearer ')
            token = token[-1]
        except Exception:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        decode_token = decode_jwt_token(token)
        if not decode_token:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        # Get User Access Token from DB
        user_access_token = EmFinancingWFAccessToken.objects.filter(
            token=token, form_type=decode_token['form_type']).last()

        if not user_access_token:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        if user_access_token.is_used:
            raise APIError(status_code=status.HTTP_403_FORBIDDEN,
                           detail=error_message)

        if user_access_token.is_clicked == False:
            user_access_token.is_clicked = True
            user_access_token.save(update_fields=['is_clicked'])

        request.user_access_token = user_access_token
        request.token_data = decode_token
