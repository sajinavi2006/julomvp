from django.test import TestCase
from mock import MagicMock
from unittest.mock import patch

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.antifraud.decorator.rate_limit import antifraud_rate_limit


class TestAntiFraudRateLimit(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.ANTIFRAUD_RATE_LIMIT,
            is_active=True,
            parameters={
                'antifraud_feature': {
                    'is_active': True,
                    'max_count': 2,
                    'time_unit': 'Minutes',
                }
            }
        )

    @patch('juloserver.ratelimit.decorator.sliding_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    def test_success(self, mock_get_key_prefix_from_request, mock_sliding_window_rate_limit):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_sliding_window_rate_limit.return_value = False
        @antifraud_rate_limit(feature_name='antifraud_feature')
        def sample_view(view, request):
            return "Success"

        response = sample_view(MagicMock(), MagicMock())
        self.assertEqual(response, "Success")
