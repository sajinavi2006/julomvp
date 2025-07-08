import time

from contextlib import contextmanager
from django.core.cache import cache

from juloserver.employee_financing.exceptions import LockAquisitionError


@contextmanager
def lock(key, retry_interval=1, retry=0, ttl=10, release_on_exit=False):
    """ Context manager to lock shared resources. Handy to prevent race conditions.
        key = cache key for shared resource
        retry_interval = interval in seconds to retry getting lock
        retry = retry this many time before raising error
        ttl = key expiry time(in s), to prevent key locking up indefinitely
    """
    if cache.add(key, True, ttl):
        if release_on_exit:
            cache.delete(key)
        yield
        return
    else:
        for retry_count in range(0, retry):
            time.sleep(retry_interval)
            if cache.add(key, True, ttl):
                if release_on_exit:
                    cache.delete(key)
                yield
                return
        raise LockAquisitionError()
