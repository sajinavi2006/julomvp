from builtins import str
from mock import patch, MagicMock
from django.test.testcases import TestCase
from django.conf import settings

from juloserver.disbursement.exceptions import GopayServiceError, GopayClientException
from juloserver.disbursement.clients.gopay import GopayClient

class TestGopayClient(TestCase):
    def setUp(self):
        self.GOPAY_BASE_URL = settings.GOPAY_BASE_URL


    @patch('requests.get')
    def test_GopayClient_get_balance_case_1(self,mock_requests):
        mock_requests.return_value.status_code = 200
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
        result = result.get_balance()

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/balance', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDEyMw==:'})
        assert result == mock_requests_json


    @patch('requests.get')
    def test_GopayClient_get_balance_case_2(self,mock_requests):
        mock_requests.return_value.status_code = 123
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(GopayClientException) as context:
            result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
            result = result.get_balance()

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/balance', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDEyMw==:'})
        self.assertTrue('Failed get balance' in str(context.exception))


    @patch('requests.post')
    def test_GopayClient_create_payouts_case_1(self,mock_requests):
        mock_requests.return_value.status_code = 201
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        receiver_data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test', 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]

        result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
        result = result.create_payouts(receiver_data)

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/payouts', data='{"payouts": [{"beneficiary_email": "test@gmail.com", "notes": "test", "beneficiary_name": "test", "amount": "100", "beneficiary_bank": "gopay", "beneficiary_account": "test123"}]}', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDEyMw==:'})
        assert result == mock_requests_json


    @patch('requests.post')
    def test_GopayClient_create_payouts_case_2(self,mock_requests):
        mock_requests.return_value.status_code = 123
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        receiver_data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test', 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]

        with self.assertRaises(GopayClientException) as context:
            result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
            result = result.create_payouts(receiver_data)

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/payouts', data='{"payouts": [{"beneficiary_email": "test@gmail.com", "notes": "test", "beneficiary_name": "test", "amount": "100", "beneficiary_bank": "gopay", "beneficiary_account": "test123"}]}', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDEyMw==:'})
        self.assertFalse('failed get response 123' in str(context.exception))


    @patch('requests.post')
    def test_GopayClient_approve_payouts_case_1(self,mock_requests):
        mock_requests.return_value.status_code = 202
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        receiver_data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test', 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]

        result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
        result = result.approve_payouts('test123')

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/payouts/approve', data='{"reference_nos": "test123"}', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDMyMQ==:'})


    @patch('requests.post')
    def test_GopayClient_approve_payouts_case_2(self,mock_requests):
        mock_requests.return_value.status_code = 123
        mock_requests_json = 'test'
        mock_requests.return_value.json.return_value = mock_requests_json

        receiver_data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test', 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]

        with self.assertRaises(GopayClientException) as context:
            result = GopayClient('test123','test321',self.GOPAY_BASE_URL)
            result = result.approve_payouts('test123')

        mock_requests.assert_called_with('https://api.sandbox.midtrans.com/api/v1/payouts/approve', data='{"reference_nos": "test123"}', headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': 'Basic dGVzdDMyMQ==:'})
        self.assertTrue('Failed to approve payout test123' in str(context.exception))
