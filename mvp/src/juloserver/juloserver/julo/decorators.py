"""
decorators.py
define decorator handler
"""

from functools import wraps
import time

from juloserver.standardized_api_response.utils import general_error_response


def delay_voice_call(func):
    """
    nexmo voice api limit is 3requests/1s
    Will have 3 workers to handle, then delay 1s on each task
    """
    def wrapper(*args, **kwargs):
        time.sleep(1)
        return func(*args, **kwargs)

    return wrapper


def deprecated_api(error_message):
    def _deprecated_api(function):
        @wraps(function)
        def wrapper(view, request, *args, **kwargs):
            return general_error_response(error_message)

        return wrapper

    return _deprecated_api
