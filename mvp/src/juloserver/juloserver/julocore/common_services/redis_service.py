import logging
import redis
from typing import Iterable, Tuple

from django.db import transaction

from juloserver.julo.models import RedisWhiteListUploadHistory
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@transaction.atomic
def set_latest_success_redis_whitelist(history: RedisWhiteListUploadHistory):
    whitelist_name = history.whitelist_name
    RedisWhiteListUploadHistory.objects.filter(
        whitelist_name=whitelist_name,
    ).update(is_latest_success=False)

    history.is_latest_success = True
    history.save(update_fields=['is_latest_success'])


def set_redis_ids_whitelist(ids: Iterable[int], key: str, temp_key: str) -> int:
    """
    Set new temporary set of whitelisted customer_ids
    To avoid down time, we create new temp key then rename
    Params:
    - ids: customer_ids/applications ids (set/generator/list)
    - key: redis key for what you want to cache
    - temp_key: temp redis key used to set before renaming to *key*

    Return:
    - Length of set ids
    """
    logger.info(
        {
            "action": "set_redis_customer_whitelist",
            "message": f"Starting adding new temp key: {temp_key}",
        }
    )

    redis_client = get_redis_client()

    # add new set
    len_ids = redis_client.sadd(
        key=temp_key,
        members=ids,
    )

    logger.info(
        {
            "action": "set_redis_customer_whitelist",
            "message": f"Successfully set on redis total {len_ids} ids on temp key {temp_key}",
        }
    )

    # rename key to main set
    redis_client.rename_key(
        old_name=temp_key,
        new_name=key,
    )

    logger.info(
        {
            "action": "set_redis_customer_whitelist",
            "message": f"Successfuly renamed {temp_key} to {key}",
        }
    )

    return len_ids


def query_redis_ids_whitelist(id: int, key: str) -> Tuple[bool, bool]:
    """
    Return is_success, is_whitelisted
    - is_success: Success querying common Redis DB
    - is_whitelisted: is ID whitelisted
    """

    try:
        redis_client = get_redis_client()

        if not redis_client.exists(key):
            raise redis.exceptions.RedisError(f"Redis Key: {key} doesn't exist")

        is_whitelisted = redis_client.sismember(
            key=key,
            value=id,
        )
    except (Exception):
        sentry_client.captureException()
        return False, False

    return True, is_whitelisted
