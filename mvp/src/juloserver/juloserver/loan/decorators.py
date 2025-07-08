from functools import wraps
from rest_framework.response import Response
from juloserver.loan.constants import DEFAULT_ANDROID_CACHE_EXPIRY_DAY


def cache_expiry_on_headers(cache_expiry_day=DEFAULT_ANDROID_CACHE_EXPIRY_DAY):
    def _handle_response(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            func = function(view, request, *args, **kwargs)
            if type(func) == Response:
                func['x-cache-expiry'] = cache_expiry_day
            return func
        return wrapper
    return _handle_response
