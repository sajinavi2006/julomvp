from mock import patch
from django.test.testcases import TestCase


from juloserver.disbursement.clients.xfers import XfersClient
from juloserver.disbursement.exceptions import XfersApiError
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.julo.utils import format_e164_indo_phone_number


class TestXfersClient(TestCase):
    def setUp(self):
        self.xfers_client = XfersClient(
            'test123',
            'test123',
            'test123',
            'test123',
            'test123',
        )

    @patch('juloserver.julo.utils.get_redis_client')
    @patch('juloserver.disbursement.clients.xfers.ss_requests.post')
    def test_get_user_token(self, mock_ss_requests_post, mock_get_redis_client):
        mock_redis_helper = MockRedisHelper()
        mock_get_redis_client.return_value = mock_redis_helper

        mock_ss_requests_post.return_value.status_code = 200
        mock_ss_requests_post.return_value.json.return_value = {
            'msg': 'success',
            'id': 'user_udvvt6m8y5ct',
            'user_api_token': '456',
            'currency': 'idr',
            'wallet_name': 'Julo Disbursement Wallet'
        }

        mobile_phone = '081234567890'
        cache_key = 'xfers_user_api_token:{}'.format(format_e164_indo_phone_number(mobile_phone))
        fs_cache_xfers_user_api_token = FeatureSettingFactory(
            feature_name=FeatureNameConst.CACHE_XFERS_USER_API_TOKEN,
            is_active=True,
            parameters={
                'expire_time_in_days': 1
            }
        )

        # test get data from cache and data exist in cache
        mock_redis_helper.set(key=cache_key, value='123')
        result = self.xfers_client.get_user_token(mobile_phone, is_use_cache_data_if_exist=True)
        mock_ss_requests_post.assert_not_called()
        self.assertEqual(result['user_api_token'], '123')

        # test get data from cache but data not exist in cache
        mock_redis_helper.delete_key(key=cache_key)
        result = self.xfers_client.get_user_token(mobile_phone, is_use_cache_data_if_exist=True)
        mock_ss_requests_post.assert_called_once()
        self.assertEqual(result['user_api_token'], '456')
        self.assertEqual(mock_redis_helper.get(cache_key), '456')

        # test not get data from cache
        fs_cache_xfers_user_api_token.is_active = False
        fs_cache_xfers_user_api_token.save()
        mock_redis_helper.delete_key(key=cache_key)
        result = self.xfers_client.get_user_token(mobile_phone, is_use_cache_data_if_exist=True)
        mock_ss_requests_post.assert_called()
        self.assertEqual(result['user_api_token'], '456')
        self.assertEqual(mock_redis_helper.get(cache_key), None)

    @patch('juloserver.disbursement.clients.xfers.ss_requests.post')
    def test_submit_withdraw(self, mock_ss_requests_post):
        mock_ss_requests_post.return_value.status_code = 200
        mock_ss_requests_post.return_value.json.return_value = {}
        result = self.xfers_client.submit_withdraw(
            bank_id=1, amount=1, idempotency_id='1', user_token='1'
        )
        self.assertIsNotNone(result)

        mock_ss_requests_post.return_value.status_code = 500
        with self.assertRaises(XfersApiError) as context:
            self.xfers_client.submit_withdraw(
                bank_id=1, amount=1, idempotency_id='1', user_token='1'
            )
        mock_ss_requests_post.assert_called()
        self.assertEqual(context.exception.http_code, 500)

    @patch('juloserver.disbursement.clients.xfers.ss_requests.post')
    def test_submit_charge_jtp(self, mock_ss_requests_post):
        mock_ss_requests_post.return_value.status_code = 200
        mock_ss_requests_post.return_value.json.return_value = {}
        result = self.xfers_client.submit_charge_jtp(amount=1, order_id='1', client_token='1')
        self.assertIsNotNone(result)

        mock_ss_requests_post.return_value.status_code = 500
        with self.assertRaises(XfersApiError) as context:
            self.xfers_client.submit_charge_jtp(amount=1, order_id='1', client_token='1')
        mock_ss_requests_post.assert_called()
        self.assertEqual(context.exception.http_code, 500)
