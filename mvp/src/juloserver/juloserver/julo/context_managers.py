import time
from contextlib import contextmanager
from juloserver.julo.constants import (
    REDIS_SET_CACHE_KEY_RETRY_IN_SECONDS,
    REDIS_TIME_OUT_SECOND_DEFAULT,
    RedisLockKeyName,
    LOCK_ON_REDIS,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.exceptions import RetryTimeOutRedis, RedisNameNotExists, DuplicateRequests


@contextmanager
def redis_lock_for_update(
    key_name, unique_value, no_wait=False, timeout_second=REDIS_TIME_OUT_SECOND_DEFAULT):
    """
    Acquires a Redis lock to handle concurrent requests

        params:: key_name must define in RedisLockKeyName and unique for specific feature
        params:: no_wait when is True => raise exception for second requests
        params:: unique_value is a unique value for specific customers, accounts.
        params:: timeout_second is max time for retrying of second requests.
    """
    # key_name must exist in RedisLockKeyName
    if not RedisLockKeyName.key_name_exists(key_name):
        raise RedisNameNotExists("key_name doesn't exists")

    # LOCK_ON_REDIS + key_name + unique_value
    key_name = ':'.join([LOCK_ON_REDIS, key_name, str(unique_value)])
    redis_client = get_redis_client()
    total_time_retry = 0

    while total_time_retry < timeout_second:
        if redis_client.setnx(key_name, key_name):
            break

        # raise exception for the second request
        if no_wait:
            raise DuplicateRequests

        time.sleep(REDIS_SET_CACHE_KEY_RETRY_IN_SECONDS)
        total_time_retry += REDIS_SET_CACHE_KEY_RETRY_IN_SECONDS

    if total_time_retry >= REDIS_TIME_OUT_SECOND_DEFAULT:
        raise RetryTimeOutRedis("Retry timeout for duplicate requests")

    try:
        yield
    finally:
        redis_client.delete_key(key_name)
