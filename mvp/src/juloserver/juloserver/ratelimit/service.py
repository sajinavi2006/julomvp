from datetime import datetime

from django.http import HttpRequest

from juloserver.julo.services2 import get_redis_client
from juloserver.julocore.utils import get_client_ip

from .constants import (
    RateLimitCount,
    RateLimitParameter,
    RateLimitTimeUnit,
)
from juloserver.julo.constants import RedisLockKeyName
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.julo.exceptions import RetryTimeOutRedis


def get_key_prefix_from_request(
    request: HttpRequest,
    parameters: list = RateLimitParameter.get_default(),
    custom_parameter_values: list = None,
) -> str:
    """
    Generate a key's prefix for rate limiting based on specified parameters.

    Args:
        request (HttpRequest): The HTTP request object.
        parameters (list, optional): The list of rate limit parameters to consider.
            Defaults to RateLimitParameter.get_default().
        custom_parameter_values (list, optional): The list of custom parameter values to include.
            Defaults to None.

    Returns:
        str: The generated key's prefix for rate limiting.
    """

    values = []

    if RateLimitParameter.Path in parameters:
        values.append(request.path)

    if RateLimitParameter.HTTPMethod in parameters:
        values.append(request.method)

    if RateLimitParameter.IP in parameters:
        values.append(str(get_client_ip(request)))

    if RateLimitParameter.AuthenticatedUser in parameters and request.user.is_authenticated:
        values.append(str(request.user.id))

    if custom_parameter_values:
        values += custom_parameter_values

    # join the values with ':' separator to form the key's prefix
    return ":".join(values)


def get_time_window(
    unix_timestamp: int,
    time_unit: RateLimitTimeUnit = RateLimitTimeUnit.Minutes,
) -> int:
    """
    Get the current time window based on the specified time unit.

    Args:
        unix_timestamp (int): The Unix timestamp representing the current time.
        time_unit (RateLimitTimeUnit, optional): The time unit for calculating the time window.
            Defaults to RateLimitTimeUnit.Minutes.

    Returns:
        int: The current time window based on the specified time unit.

    """

    if time_unit is RateLimitTimeUnit.Seconds:  # get current second
        return unix_timestamp % 60

    elif time_unit is RateLimitTimeUnit.Minutes:  # get current minute
        return (unix_timestamp % 3600) // 60

    elif time_unit is RateLimitTimeUnit.Hours:  # get current hour
        return (unix_timestamp % 86400) // 3600

    elif time_unit is RateLimitTimeUnit.Days:  # get N of days since epoch
        return unix_timestamp // 86400

    return


def fixed_window_rate_limit(
    key_prefix: str = None,
    max_count: int = RateLimitCount.DefaultPerMinute,
    time_unit: RateLimitTimeUnit = RateLimitTimeUnit.Minutes,
) -> bool:
    """
    Fixed window rate limiting using Redis.

    Args:
        key_prefix (str, optional): Prefix for the Redis key.
            Defaults to None.
        max_count (int, optional): Maximum count allowed within the time window.
            Defaults to RateLimitCount.DefaultPerMinute.
        time_unit (RateLimitTimeUnit, optional): Time unit for the rate limit.
            Defaults to RateLimitTimeUnit.Minutes.

    Returns:
        bool: True if the rate limit is exceeded, False otherwise.
    """

    redis_client = get_redis_client()
    unix_timestamp = int(datetime.now().timestamp())
    ttl = RateLimitTimeUnit.get_ttl(time_unit)
    window = get_time_window(unix_timestamp, time_unit)

    # construct the Redis key
    key = 'fixed_window:{}:{}:{}'.format(key_prefix, time_unit.value, window)

    # increment to current window
    count = redis_client.increment(key)

    # set expiration
    redis_client.expire(key, ttl)  # TODO: explore NX's compatibility

    return count > max_count


def sliding_window_rate_limit(
    key_prefix: str = None,
    max_count: int = RateLimitCount.DefaultPerMinute,
    time_unit: RateLimitTimeUnit = RateLimitTimeUnit.Minutes,
) -> bool:
    """
    Sliding window rate limiting using a sorted set in Redis.

    Args:
        key_prefix (str, optional): Prefix for the Redis key. Defaults to None.
        max_count (int, optional): Maximum number of requests allowed within the sliding window.
            Defaults to RateLimitCount.DefaultPerMinute.
        time_unit (RateLimitTimeUnit, optional): Time unit for the sliding window.
            Defaults to RateLimitTimeUnit.Minutes.

    Returns:
        bool: True if the rate limit is exceeded, False otherwise.
    """

    redis_client = get_redis_client()
    now = datetime.now()
    unix_timestamp = now.timestamp()
    ttl = RateLimitTimeUnit.get_ttl(time_unit)

    # construct the Redis key
    key = 'sliding_window:{}'.format(key_prefix)

    try:
        with redis_lock_for_update(RedisLockKeyName.RATE_LIMITER, key, timeout_second=5):
            # remove timestamps outside the sliding window
            min_score = unix_timestamp - RateLimitTimeUnit.get_ttl(time_unit)
            redis_client.zremrangebyscore(key, '-inf', min_score)

            count = redis_client.zcard(key)
            is_rate_limited = count >= max_count

            if not is_rate_limited:
                # increment the current sliding window
                redis_client.zadd(key, **{str(unix_timestamp): unix_timestamp})

                # set expiration
                redis_client.expire(key, ttl)
            return is_rate_limited
    except RetryTimeOutRedis:
        # By pass if the lock is not acquired because of timeout
        return False
