from django.test.testcases import TestCase, override_settings
from datetime import timedelta
from mock import patch, Mock
from juloserver.julo.clients import get_doku_snap_client
from juloserver.julo.clients.constants import RedisKey


class TestDokuSnapClient(TestCase):
    @patch('juloserver.julo.clients.doku.serialization.load_pem_private_key')
    @patch('juloserver.julo.clients.doku.get_redis_client')
    @patch('juloserver.julo.clients.doku.generate_sha256_rsa')
    @patch('juloserver.julo.clients.doku.requests.post')
    def setUp(
        self,
        mock_request_post,
        mock_generate_sha256_rsa,
        mock_get_redis_client,
        mock_load_pem_private_key,
    ):
        self.mock_redis = Mock()
        mock_get_redis_client.return_value = self.mock_redis
        mock_generate_sha256_rsa.return_value = 'test_signature'
        mock_request_post.return_value.json.return_value = {
            'responseCode': '2007300',
            'responseMessage': 'Successful',
            'accessToken': 'test_access_token',
            'tokenType': 'Bearer',
            'expiresIn': 900,
            'additionalInfo': '',
        }
        mock_request_post.return_value.status_code = 200
        self.mock_redis.get.return_value = None

        self.doku_snap_client = get_doku_snap_client()

    def test_get_access_token(self):
        self.assertEqual(self.doku_snap_client.access_token, 'test_access_token')
        self.mock_redis.set.assert_called_with(
            RedisKey.DOKU_CLIENT_ACCESS_TOKEN, 'test_access_token', timedelta(seconds=300)
        )

    @patch('juloserver.julo.clients.doku.store_payback_api_log')
    @patch('juloserver.julo.clients.doku.requests.post')
    def test_inquiry_status_success(self, mock_request_post, mock_store_payback_api_log):
        mock_request_post.return_value.json.return_value = {
            'responseCode': '2002600',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'paymentFlagReason': {'english': 'Success', 'indonesia': 'Sukses'},
                'partnerServiceId': '  088899',
                'customerNo': '12345678901234567890',
                'virtualAccountNo': '  08889912345678901234567890',
                'inquiryRequestId': 'abcdef-123456-abcdef',
                'paymentRequestId': 'abcdef-123456-abcdef',
                'paidAmount': {'value': '12345678.00', 'currency': 'IDR'},
                'billAmount': {'value': '12345678.00', 'currency': 'IDR'},
                'additionalInfo': {'acquirer': 'MANDIRI', 'trxId': ' test123'},
            },
        }
        mock_request_post.return_value.status_code = 200

        partner_service_id = '088899'
        customer_no = '12345678901234567890'
        virtual_account_no = '08889912345678901234567890'
        transaction_id = 'txid123'

        response_data, error_message = self.doku_snap_client.inquiry_status(
            partner_service_id, customer_no, virtual_account_no, transaction_id
        )

        self.assertEqual(response_data['responseCode'], '2002600')
        self.assertIsNone(error_message)
