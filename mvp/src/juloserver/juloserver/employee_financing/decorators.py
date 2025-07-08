from functools import wraps

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from juloserver.employee_financing.exceptions import APIError

from typing import Callable, Any


def check_is_form_submitted(function: Callable) -> Callable:
    @wraps(function)
    def wrapper(view, request: Request, *args: Any, **kwargs: Any) -> Response:
        access_token = request.user_access_token
        if access_token.is_used:
            error_message = {
                'web_form': 'Form is already submit'
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST,
                           detail=error_message)

        return function(view, request, *args, **kwargs)

    return wrapper
