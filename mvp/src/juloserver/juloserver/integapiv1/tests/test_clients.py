from django.test.testcases import TestCase, override_settings
from datetime import timedelta
from mock import patch, Mock
from juloserver.integapiv1.clients import get_faspay_snap_client


class TestFaspaySnapClient(TestCase):
    @patch('juloserver.integapiv1.clients.get_julo_sentry_client')
    @patch('juloserver.integapiv1.clients.generate_signature_asymmetric')
    @patch('juloserver.integapiv1.clients.FaspaySnapClient.generate_string_to_sign')
    @patch('juloserver.integapiv1.clients.requests.post')
    def test_create_transaction_va_data_success(
        self,
        mock_request_post,
        mock_generate_string_to_sign,
        mock_generate_signature_asymmetric,
        mock_julo_sentry_client,
    ):
        self.faspay_snap_client = get_faspay_snap_client()

        mock_generate_string_to_sign.return_value = 'test-string-to-sign'
        mock_generate_signature_asymmetric.return_value = 'test_signature'
        mock_request_post.return_value.json.return_value = {
            'responseCode': '2002700',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'partnerServiceId': '121212121',
                'customerNo': '121212121',
                'virtualAccountNo': '9881859302198949',
                'virtualAccountName': 'Testing VA',
                'virtualAccountEmail': 'testing@gmail.com',
                'virtualAccountPhone': '6281212121212',
                'trxId': '988121212121212',
                'totalAmount': {'value': '100000.00', 'currency': 'IDR'},
                'expiredDate': '2035-01-15T13:27:21+07:00',
                'additionalInfo': {
                    'billDate': '2025-01-17T13:27:21+07:00',
                    'channelCode': '111',
                    'billDescription': 'JULO BNI Faspay',
                    'redirectUrl': 'https://sandbox.faspay.co.id/pws/11111/11111/11111?trx_id=11111&merchant_id=1111&bill_no=11111',
                },
            },
        }
        mock_request_post.return_value.status_code = 200

        transaction_data = {
            'virtualAccountName': 'Testing VA',
            'virtualAccountEmail': 'testing@gmail.com',
            'virtualAccountPhone': '6281212121212',
            'virtualAccountNo': '988121212121212',
            'trxId': '988121212121212',
            'totalAmount': {'value': '10000.00', 'currency': 'IDR'},
            'expiredDate': '2035-01-15T13:27:21+07:00',
            'additionalInfo': {
                'billDate': '2025-01-17T13:27:21+07:00',
                'channelCode': '111',
                'billDescription': 'JULO BNI Faspay',
            },
        }

        response, error = self.faspay_snap_client.create_transaction_va_data(transaction_data)

        self.assertIsNone(error)
        self.assertEqual(response['responseCode'], '2002700')

    @patch('juloserver.integapiv1.clients.get_julo_sentry_client')
    @patch('juloserver.integapiv1.clients.generate_signature_asymmetric')
    @patch('juloserver.integapiv1.clients.FaspaySnapClient.generate_string_to_sign')
    @patch('juloserver.integapiv1.clients.requests.post')
    def test_create_transaction_va_data_success_without_json(
        self,
        mock_request_post,
        mock_generate_string_to_sign,
        mock_generate_signature_asymmetric,
        mock_julo_sentry_client,
    ):
        self.faspay_snap_client = get_faspay_snap_client()

        mock_generate_string_to_sign.return_value = 'test-string-to-sign'
        mock_generate_signature_asymmetric.return_value = 'test_signature'
        mock_request_post.return_value.text.return_value = 'success'
        mock_request_post.return_value.json.side_effect = ValueError(
            "Expecting value: line 1 column 1 (char 0)"
        )
        mock_request_post.return_value.status_code = 200

        transaction_data = {
            'virtualAccountName': 'Testing VA',
            'virtualAccountEmail': 'testing@gmail.com',
            'virtualAccountPhone': '6281212121212',
            'virtualAccountNo': '988121212121212',
            'trxId': '988121212121212',
            'totalAmount': {'value': '10000.00', 'currency': 'IDR'},
            'expiredDate': '2035-01-15T13:27:21+07:00',
            'additionalInfo': {
                'billDate': '2025-01-17T13:27:21+07:00',
                'channelCode': '111',
                'billDescription': 'JULO BNI Faspay',
            },
        }

        response, error = self.faspay_snap_client.create_transaction_va_data(transaction_data)
        self.assertIsNotNone(error)
        self.assertIsNone(response)
