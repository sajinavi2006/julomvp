from datetime import timedelta
from unittest.mock import (
    patch,
    MagicMock,
)

from django.test import SimpleTestCase

from juloserver.streamlined_communication.cache import RedisCache

PACKAGE_NAME = 'juloserver.streamlined_communication.cache'


@patch(f'{PACKAGE_NAME}.get_redis_client')
class TestRedisCache(SimpleTestCase):
    def test_init_default(self, mock_get_redis_client):
        redis_cache = RedisCache('key-name')
        self.assertEqual('key-name', redis_cache.key)
        self.assertEqual(60.0, redis_cache.expire_time.total_seconds())
        mock_get_redis_client.assert_called_once_with()

    def test_init_custom(self, mock_get_redis_client):
        redis_cache = RedisCache('key-name', days=1, hours=1, minutes=1, seconds=1)
        self.assertEqual('key-name', redis_cache.key)
        self.assertEqual(90061.0, redis_cache.expire_time.total_seconds())
        mock_get_redis_client.assert_called_once_with()

    def test_init_no_expire(self, mock_get_redis_client):
        redis_cache = RedisCache('key-name', seconds=0)
        self.assertEqual('key-name', redis_cache.key)
        self.assertEqual(60.0, redis_cache.expire_time.total_seconds())
        mock_get_redis_client.assert_called_once_with()

    def test_get(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.get.return_value = 'value'
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name')
        ret_value = redis_cache.get()

        self.assertEqual('value', ret_value)
        mock_redis_client.get.assert_called_once_with('key-name')

    def test_set(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.set.return_value = True
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name', seconds=10)
        ret_value = redis_cache.set('value')

        self.assertTrue(ret_value)
        mock_redis_client.set.assert_called_once_with('key-name', 'value', timedelta(seconds=10))

    def test_get_list(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.get_list.return_value = 'value'
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name')
        ret_value = redis_cache.get_list()

        self.assertEqual('value', ret_value)
        mock_redis_client.get_list.assert_called_once_with('key-name')

    def test_set_list(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.set_list.return_value = True
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name', seconds=10)
        ret_value = redis_cache.set_list('value')

        self.assertTrue(ret_value)
        mock_redis_client.set_list.assert_called_once_with('key-name', 'value', timedelta(seconds=10))

    def test_delete(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.delete_key.return_value = True
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name')
        ret_value = redis_cache.delete()

        self.assertTrue(ret_value)
        mock_redis_client.delete_key.assert_called_once_with('key-name')

    def test_remove_element(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_redis_client.remove_element.return_value = True
        mock_get_redis_client.return_value = mock_redis_client

        redis_cache = RedisCache('key-name')
        ret_value = redis_cache.remove_element(1, 2)

        self.assertTrue(ret_value)
        mock_redis_client.remove_element.assert_called_once_with('key-name', 1, 2)
