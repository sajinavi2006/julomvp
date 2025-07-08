from collections import Counter

from django.test.testcases import TestCase

from juloserver.julo.constants import RedisLockKeyName


class TestRedisLockKeyName(TestCase):
    def test_redis_lock_key_name_duplicate(self):
        list_keys = RedisLockKeyName.list_key_name()
        key_count = Counter(list_keys)

        for _, count in key_count.items():
            self.assertEqual(count, 1)
