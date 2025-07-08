from django.http import HttpRequest
from django.test import TestCase
import mock
from unittest.mock import patch

from juloserver.ratelimit.constants import RateLimitParameter, RateLimitTimeUnit

from juloserver.ratelimit.service import (
    get_key_prefix_from_request,
    get_time_window,
    fixed_window_rate_limit,
    sliding_window_rate_limit,
)


class TestGetKeyPrefixFromRequest(TestCase):
    def test_happy_path(self):
        request = HttpRequest()
        request.path = '/some/path'
        request.method = 'GET'
        request.META['REMOTE_ADDR'] = '1.1.1.1'

        resp = get_key_prefix_from_request(request)
        self.assertEqual(resp, '/some/path:GET:1.1.1.1')

    def test_success_with_custom_parameter_values(self):
        request = HttpRequest()
        request.path = '/some/path'
        request.method = 'GET'
        request.META['REMOTE_ADDR'] = '1.1.1.1'

        resp = get_key_prefix_from_request(request, custom_parameter_values=['custom1', 'custom2'])
        self.assertEqual(resp, '/some/path:GET:1.1.1.1:custom1:custom2')

    def test_invalid_ip(self):
        request = HttpRequest()
        request.path = '/some/path'
        request.method = 'GET'
        request.META['REMOTE_ADDR'] = 'invalid ip hehehehe'

        resp = get_key_prefix_from_request(request)
        self.assertEqual(resp, '/some/path:GET:None')

    def test_only_path(self):
        request = HttpRequest()
        request.path = '/some/path'

        parameters = [RateLimitParameter.Path]
        resp = get_key_prefix_from_request(request, parameters)
        self.assertEqual(resp, '/some/path')

    def test_only_http_method(self):
        request = HttpRequest()
        request.method = 'GET'

        parameters = [RateLimitParameter.HTTPMethod]
        resp = get_key_prefix_from_request(request, parameters)
        self.assertEqual(resp, 'GET')

    def test_only_ip(self):
        request = HttpRequest()
        request.META['REMOTE_ADDR'] = '1.1.1.1'

        parameters = [RateLimitParameter.IP]
        resp = get_key_prefix_from_request(request, parameters)
        self.assertEqual(resp, '1.1.1.1')

    def test_only_authenticated_user(self):
        request = HttpRequest()
        request.user = mock.MagicMock()
        request.user.is_authenticated = True
        request.user.id = 69

        parameters = [RateLimitParameter.AuthenticatedUser]
        resp = get_key_prefix_from_request(request, parameters)
        self.assertEqual(resp, '69')

    def test_only_custom_parameter_values(self):
        request = HttpRequest()

        parameters = []
        resp = get_key_prefix_from_request(
            request, parameters, custom_parameter_values=['custom1', 'custom2']
        )
        self.assertEqual(resp, 'custom1:custom2')

    def test_no_parameters(self):
        request = HttpRequest()

        parameters = []
        resp = get_key_prefix_from_request(request, parameters)
        self.assertEqual(resp, '')


class TestGetTimeWindow(TestCase):
    def test_seconds(self):
        resp = get_time_window(6, RateLimitTimeUnit.Seconds)
        self.assertEqual(resp, 6)

    def test_minutes(self):
        resp = get_time_window(69, RateLimitTimeUnit.Minutes)
        self.assertEqual(resp, 1)

    def test_hours(self):
        resp = get_time_window(6969, RateLimitTimeUnit.Hours)
        self.assertEqual(resp, 1)

    def test_days(self):
        resp = get_time_window(1707216969, RateLimitTimeUnit.Days)
        self.assertEqual(resp, 19759)

    def test_int_param(self):
        for i in range(0, 10):
            resp = get_time_window(69, i)
            self.assertEqual(resp, None)


class TestFixedWindowRateLimit(TestCase):
    @patch('juloserver.ratelimit.service.get_redis_client')
    @patch('juloserver.ratelimit.service.datetime')
    def test_rate_limit_not_exceeded(
        self,
        mock_datetime,
        mock_get_redis_client,
    ):
        mock_datetime.now.return_value.timestamp.return_value = 123456789

        mock_redis_client = mock.MagicMock()
        mock_redis_client.increment.return_value = 69
        mock_get_redis_client.return_value = mock_redis_client

        resp = fixed_window_rate_limit('some prefix', 96, RateLimitTimeUnit.Seconds)
        self.assertFalse(resp)

    @patch('juloserver.ratelimit.service.get_redis_client')
    @patch('juloserver.ratelimit.service.datetime')
    def test_rate_limit_exceeded(
        self,
        mock_datetime,
        mock_get_redis_client,
    ):
        mock_datetime.now.return_value.timestamp.return_value = 123456789

        mock_redis_client = mock.MagicMock()
        mock_redis_client.increment.return_value = 96
        mock_get_redis_client.return_value = mock_redis_client

        resp = fixed_window_rate_limit('some prefix', 69, RateLimitTimeUnit.Seconds)
        self.assertTrue(resp)


class TestSlidingWindowRateLimit(TestCase):
    @patch('juloserver.ratelimit.service.get_redis_client')
    @patch('juloserver.ratelimit.service.datetime')
    def test_rate_limit_not_exceeded(
        self,
        mock_datetime,
        mock_get_redis_client,
    ):
        mock_datetime.now.return_value.timestamp.return_value = 123456789

        mock_redis_client = mock.MagicMock()
        mock_redis_client.zcard.return_value = 69
        mock_get_redis_client.return_value = mock_redis_client

        resp = sliding_window_rate_limit('some prefix', 96, RateLimitTimeUnit.Seconds)
        self.assertFalse(resp)

    @patch('juloserver.ratelimit.service.get_redis_client')
    @patch('juloserver.ratelimit.service.datetime')
    def test_rate_limit_exceeded(
        self,
        mock_datetime,
        mock_get_redis_client,
    ):
        mock_datetime.now.return_value.timestamp.return_value = 123456789

        mock_redis_client = mock.MagicMock()
        mock_redis_client.zcard.return_value = 96
        mock_get_redis_client.return_value = mock_redis_client

        resp = sliding_window_rate_limit('some prefix', 69, RateLimitTimeUnit.Seconds)
        self.assertTrue(resp)
