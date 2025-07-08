from functools import wraps
from juloserver.minisquad.constants import (
    RedisKey,
)
from datetime import datetime
from juloserver.julo.services2 import get_redis_client
import logging
import inspect

logger = logging.getLogger(__name__)


def redis_prevent_double_run(bucket_name, fn_name):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if the bucket exists in the database
            redis_client = get_redis_client()
            lock_key = RedisKey.LOCK_CHAINED_TASK_RECOVERY.format(bucket_name)
            now = datetime.now()
            midnight = datetime.combine(now.date(), datetime.max.time())
            time_remaining = midnight - now
            eod_redis_duration = int(time_remaining.total_seconds())
            lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=eod_redis_duration)
            redis_client.set_list(RedisKey.DAILY_REDIS_KEY_FOR_DIALER_RECOVERY, [lock_key])
            if not lock_acquired:
                logger.info(
                    {
                        'fn_name': fn_name,
                        'identifier': bucket_name,
                        'msg': 'Task already in progress',
                    }
                )
                return

            # If it exists, proceed with the original function
            return func(*args, **kwargs)

        return wrapper

    return decorator


def chain_trigger_daily(redis_key, chain_func=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            sign = inspect.signature(func)
            parameters = list(sign.parameters.keys())
            task_identifier = None
            if args and 'task_identifier' in parameters:
                task_identifier_index = parameters.index('task_identifier')
                if len(args) > task_identifier_index:
                    task_identifier = args[task_identifier_index]
            else:
                task_identifier = kwargs.get('task_identifier')

            if task_identifier:
                current_date = datetime.now().strftime("%Y-%m-%d")
                formated_key = redis_key.format(current_date)
                redis_client = get_redis_client()
                redis_client.lrem(formated_key, 1, task_identifier)
                if chain_func and not redis_client.get_list(formated_key):
                    chain_func.delay() if hasattr(chain_func, 'delay') else chain_func()

            return result

        return wrapper

    return decorator
