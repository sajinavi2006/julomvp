from builtins import str
from django.test.testcases import TestCase
from juloserver.cootek.clients.cootek import CootekClient
from mock import patch, MagicMock, ANY
import mock
from juloserver.julo.exceptions import JuloException
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.minisquad.constants import FeatureNameConst


class TestCootekClient(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AIRUDDER_RECOMMENDED_TIMEOUT,
            is_active=True,
            parameters={
                'recommended_connect_timeout': 120,
                'recommended_read_timeout': 120
            }
        )

    @mock.patch.object(CootekClient, '_CootekClient__get_token_from_redis')
    def test_cootek_client_init(self, mock_token):
        mock_token.return_value = 'test_cootek'
        cootek_client = CootekClient(
            'test_cootek',
            'test_cootek',
            'test_cootek'
        )
        assert mock_token.called

    @mock.patch.object(CootekClient, '_CootekClient__get_token_from_redis')
    @mock.patch('requests.post')
    @patch('juloserver.cootek.clients.cootek.get_redis_client')
    def test_refresh_token(self, mock_redis_client, mock_response, mock_token):
        mock_response.return_value.status_code = 401
        mock_token.return_value = 'test_cootek'
        cootek_client = CootekClient(
            'test_cootek',
            'test_cootek',
            'test_cootek'
        )
        with self.assertRaises(JuloException) as context:
            cootek_client.refresh_token()
        self.assertTrue('Failed to Get Token from Cootek - Unauthorized' in str(context.exception))

    @mock.patch.object(CootekClient, '_CootekClient__get_token_from_redis')
    @mock.patch('requests.post')
    def test_make_request(self, mock_response, mock_token):
        mock_response.return_value.status_code = 401
        mock_token.return_value = 'test_cootek'
        cootek_client = CootekClient(
            'test_cootek',
            'test_cootek',
            'test_cootek'
        )
        with self.assertRaises(JuloException) as context:
            cootek_client._make_request('POST', 'test')
        self.assertFalse('Failed to Make Request to Cootek - Max Retry Reached' in str(context.exception))

    @mock.patch.object(CootekClient, '_CootekClient__get_token_from_redis')
    @mock.patch('requests.post')
    def test_cancel_phone_call_for_payment_paid_off(self, mock_response, mock_token):
        mock_response.return_value.status_code = 500
        mock_token.return_value = 'test_cootek'
        cootek_client = CootekClient(
            'test_cootek',
            'test_cootek',
            'test_cootek'
        )
        with self.assertRaises(JuloException) as context:
            cootek_client.cancel_phone_call_for_payment_paid_off(
                '1234', '+6289532412977366')
        self.assertFalse('Cannot cancel phone call' in str(context.exception))


    @mock.patch.object(CootekClient, '_CootekClient__get_token_from_redis')
    @mock.patch('requests.get')
    def test_get_task_details(self, mock_response, mock_token):
        mock_response.return_value.status_code = 500
        mock_token.return_value = 'test_cootek'
        cootek_client = CootekClient(
            'test_cootek',
            'test_cootek',
            'test_cootek'
        )
        with self.assertRaises(JuloException) as context:
            cootek_client.get_task_details(
                'test')
        self.assertFalse('Cannot get Task detail' in str(context.exception))
