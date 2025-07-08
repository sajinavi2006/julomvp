import logging
from functools import wraps
from typing import List
from datetime import datetime

from juloserver.ratelimit.constants import (
    RateLimitAlgorithm,
    RateLimitCount,
    RateLimitParameter,
    RateLimitTimeUnit,
    RateLimitMessages,
)
from juloserver.ratelimit.service import (
    get_key_prefix_from_request,
    fixed_window_rate_limit,
    sliding_window_rate_limit,
)

from juloserver.standardized_api_response.utils import (
    too_many_requests_response,
)

logger = logging.getLogger(__name__)


def rate_limit_incoming_http(
    max_count: int = RateLimitCount.DefaultPerMinute,
    time_unit: RateLimitTimeUnit = RateLimitTimeUnit.Minutes,
    algo: RateLimitAlgorithm = RateLimitAlgorithm.FixedWindow,
    message: str = RateLimitMessages.Default.value,
    parameters: List[str] = RateLimitParameter.get_default(),
    custom_parameter_values: list = None,
):
    """
    Decorator to ease rate limiting for incoming HTTP requests.

    Args:
        max_count (int): The maximum number of requests allowed within the specified time unit.
        time_unit (RateLimitTimeUnit): The time unit for rate limiting.
        algo (RateLimitAlgorithm): The rate limiting algorithm to use.
        message (str): The message to be returned when the rate limit is exceeded.
        parameters (List[str]): The list of parameters used to generate the rate limit key.
        custom_parameter_values (list): List of custom parameter values.

    Returns:
        The decorated function.

    Example usage:
        @rate_limit_incoming_http(max_count=100, time_unit=RateLimitTimeUnit.Minutes)
        def some_view(request):
            pass
    """

    def _rate_limit(func):
        @wraps(func)
        def wrapper(view, request, *args, **kwargs):

            key_prefix = get_key_prefix_from_request(request, parameters, custom_parameter_values)
            is_rate_limited = False

            if algo is RateLimitAlgorithm.FixedWindow:
                is_rate_limited = fixed_window_rate_limit(key_prefix, max_count, time_unit)
            elif algo is RateLimitAlgorithm.SlidingWindow:
                is_rate_limited = sliding_window_rate_limit(key_prefix, max_count, time_unit)

            if is_rate_limited:
                logger.info({
                    'action': 'rate_limit_incoming_http',
                    'message': 'the request reached limit',
                    'user_id': request.user.id,
                    'timestamp': datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
                })
                return too_many_requests_response(message)

            return func(
                view,
                request,
                *args,
                **kwargs,
            )

        return wrapper

    return _rate_limit
