from django.test import TestCase
import mock
from unittest.mock import patch

from juloserver.ratelimit.decorator import rate_limit_incoming_http

from juloserver.ratelimit.constants import (
    RateLimitAlgorithm,
)


class TestRateLimitDecorator(TestCase):
    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    def test_not_rate_limited(
        self,
        mock_get_key_prefix_from_request,
        mock_fixed_window_rate_limit,
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False

        @rate_limit_incoming_http()
        def mock_call(view, request):
            return None

        resp = mock_call(mock.MagicMock(), mock.MagicMock())
        self.assertEqual(resp, None)

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    def test_rate_limit_exceeded_decorator_fixed_window(
        self,
        mock_get_key_prefix_from_request,
        mock_fixed_window_rate_limit,
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = True

        @rate_limit_incoming_http(algo=RateLimitAlgorithm.FixedWindow)
        def mock_call(view, request):
            return None

        resp = mock_call(mock.MagicMock(), mock.MagicMock())
        self.assertEqual(resp.status_code, 429)

    @patch('juloserver.ratelimit.decorator.sliding_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    def test_rate_limit_exceeded_decorator_sliding_window(
        self,
        mock_get_key_prefix_from_request,
        mock_sliding_window_rate_limit,
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_sliding_window_rate_limit.return_value = True

        @rate_limit_incoming_http(algo=RateLimitAlgorithm.SlidingWindow)
        def mock_call(view, request):
            return None

        resp = mock_call(mock.MagicMock(), mock.MagicMock())
        self.assertEqual(resp.status_code, 429)
