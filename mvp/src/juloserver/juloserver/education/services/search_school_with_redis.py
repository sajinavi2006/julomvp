import json
import redis

from juloserver.education.constants import (
    REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME,
    FeatureNameConst,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import FeatureSetting
from juloserver.julocore.redis_completion_py3 import RedisEnginePy3


def is_search_school_with_redis():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SEARCH_SCHOOL_IN_REDIS,
        is_active=True,
    ).exists()


def search_school_by_name_with_redis(phrase, limit):
    try:
        redis_completion_engine = RedisEnginePy3(prefix=REDIS_SCHOOL_AUTO_COMPLETE_HASH_TABLE_NAME)
        # in case search by some letters
        if redis_completion_engine.clean_phrase(phrase=phrase):
            schools = redis_completion_engine.search_json(phrase=phrase, limit=limit)

        # in case not search anything -> get school data in hash table
        else:
            redis_client = redis_completion_engine.client
            schools = []
            count = 0
            for _, value in redis_client.hscan_iter(redis_completion_engine.data_key):
                schools.append(json.loads(value.decode()))
                count += 1
                if count >= limit:
                    break

        return True, schools
    except redis.exceptions.RedisError:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        return False, None
