from unittest import TestCase as UnitTestCase
from mock import patch

from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julocore.common_services.redis_service import (
    query_redis_ids_whitelist,
    set_redis_ids_whitelist,
)


class TestRedisCommonServices(UnitTestCase):
    def setUp(self):
        self.fake_redis = MockRedisHelper()

    @patch("juloserver.julocore.common_services.redis_service.get_redis_client")
    def test_set_redis_ids_whitelist(self, mock_get_redis_client):
        key = "blue_eyes_white_dragon"
        temp_key = "temp_blue_eyes_white_dragon"

        mock_get_redis_client.return_value = self.fake_redis

        test_set = {1, 2, 3}
        generator = (x for x in test_set)

        set_redis_ids_whitelist(
            ids=generator,
            key=key,
            temp_key=temp_key,
        )

        does_exist_key = self.fake_redis.exists(key)
        does_exist_temp_key = self.fake_redis.exists(temp_key)

        self.assertEqual(does_exist_key, True)
        self.assertEqual(does_exist_temp_key, False)

        # test elements in set

        for item in test_set:
            self.assertTrue(self.fake_redis.sismember(key=key, value=item))

    @patch("juloserver.julocore.common_services.redis_service.get_redis_client")
    def test_query_redis_ids_whitelist(self, mock_get_redis_client):
        # set up
        key = "red_eyes_black_dragon"
        test_set = {1, 2, 3}
        self.fake_redis.sadd(key=key, members=test_set)

        mock_get_redis_client.return_value = self.fake_redis

        # non whitelist
        is_redis_success, is_whitelisted = query_redis_ids_whitelist(id=4, key=key)

        self.assertEqual(is_redis_success, True)
        self.assertEqual(is_whitelisted, False)

        # test whitelist
        is_redis_success, is_whitelisted = query_redis_ids_whitelist(id=1, key=key)

        self.assertEqual(is_redis_success, True)
        self.assertEqual(is_whitelisted, True)

        # key doesn't exist
        is_redis_success, is_whitelisted = query_redis_ids_whitelist(id=1, key="fake_key")

        self.assertEqual(is_redis_success, False)
        self.assertEqual(is_whitelisted, False)
