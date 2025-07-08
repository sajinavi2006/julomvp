from builtins import str
from mock import patch, MagicMock, ANY
from django.test.testcases import TestCase
from django.conf import settings

from juloserver.disbursement.exceptions import BcaApiError
from juloserver.disbursement.clients.bca import BcaClient
from juloserver.julo_privyid.tests.factories import (
    MockRedis,
    MockRedisEmpty)


class TestBcaClient(TestCase):
    def setUp(self):
        self.BCA_BASE_URL = settings.BCA_BASE_URL


    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_init(self, mock_get_access_token):
        mock_get_access_token.return_value = ['test','123']
        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        assert mock_get_access_token.called


    @patch('requests.post')
    @patch("juloserver.julo.services2.redis_helper.RedisHelper")
    def test_BcaClient_get_access_token_case_1(self, mock_redis, mock_requests):
        mock_redis.return_value = MockRedis()
        mock_requests.return_value.status_code = 200
        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        result = result.get_access_token()
        assert not mock_requests.called
        assert mock_redis.called


    @patch('requests.post')
    @patch("juloserver.julo.services2.redis_helper.RedisHelper")
    def test_BcaClient_get_access_token_case_2(self, mock_redis, mock_requests):
        mock_redis.return_value = MockRedisEmpty()
        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.get_access_token()

        assert mock_requests.called
        self.assertTrue('Failed to get access token API BCA:' in str(context.exception))


    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_generate_signature_case_1(self, mock_get_access_token):
        mock_get_access_token.return_value = ['test','123']
        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        result = result.generate_signature('test',2,3,4,5)
        assert result == '6c7e48b78b82f995d4b3f3da95b5c69c070c4fd388e248e6ac6be78d2e4f5f2d'


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.get')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_get_balance_case_1(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_requests.return_value.status_code = 123
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.get_balance()

        self.assertTrue('error_test' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/v3/corporates/test123/accounts/test123', headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.get')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_get_balance_case_2(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_requests.return_value.status_code = 200
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'AccountDetailDataFailed': [{
                'English':'error_test'
            }]
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.get_balance()

        self.assertTrue('error_test' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/v3/corporates/test123/accounts/test123', headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.get')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_get_balance_case_3(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_requests.return_value.status_code = 200
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_response_res_json = {
            'AccountDetailDataFailed':False
            }
        mock_requests.return_value.json.return_value = mock_response_res_json

        result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
        result = result.get_balance()

        assert result == mock_response_res_json
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/v3/corporates/test123/accounts/test123', headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.post')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_transfer_case_1(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        description = 'disburse_id'
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.transfer(1,2,3,description)

        self.assertTrue('test123' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/corporates/transfers', data=ANY, headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.post')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_transfer_case_2(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        description = '0123456789111315171921'
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.transfer(1,2,3,description)

        self.assertTrue('test123' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/corporates/transfers', data=ANY, headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.post')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_transfer_case_3(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        description = '01234567891113151719210123456789111315171921'
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.transfer(1,2,3,description)

        self.assertTrue('test123' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/corporates/transfers', data=ANY, headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.post')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_transfer_case_4(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_requests.return_value.status_code = 200
        description = 'disburse_id'
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123',
            'Status':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        result = result.transfer(1,2,3,description)

        assert result['Status'] == mock_requests_json['Status']
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/corporates/transfers', data=ANY, headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.get')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_get_statements_case_1(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        start_date = '2020-12-01'
        end_date = '2020-12-30'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123',
            'Status':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        with self.assertRaises(BcaApiError) as context:
            result = BcaClient(
                'test123',
                'test123',
                'test123',
                'test123',
                self.BCA_BASE_URL,
                'test123',
                'test123'
            )
            result = result.get_statements(start_date,end_date)

        self.assertTrue('error_test' in str(context.exception))
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/v3/corporates/test123/accounts/test123/statements?StartDate=2020-12-01&EndDate=2020-12-30', headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.timezone')
    @patch('juloserver.disbursement.clients.bca.BcaClient.generate_signature')
    @patch('requests.get')
    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_get_statements_case_2(self, mock_get_access_token, mock_requests, mock_generate_signature, mock_timezone):
        mock_get_access_token.return_value = ['test','123']
        mock_requests.return_value.status_code = 200
        mock_generate_signature.return_value = 'test123'
        mock_timezone.localtime.return_value.strftime.return_value = 'test123'
        start_date = '2020-12-01'
        end_date = '2020-12-30'
        mock_requests_json = {
            'ErrorMessage':{
                'English':'error_test'
            },
            'ErrorCode':'test123',
            'Status':'test123'
        }
        mock_requests.return_value.json.return_value = mock_requests_json

        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        result = result.get_statements(start_date,end_date)

        assert result == mock_requests_json
        mock_requests.assert_called_with('https://devapi.klikbca.com:9443/banking/v3/corporates/test123/accounts/test123/statements?StartDate=2020-12-01&EndDate=2020-12-30', headers={'X-BCA-Signature': 'test123', 'Content-Type': 'application/json', 'X-BCA-Key': 'test123', 'Authorization': 'Bearer test', 'X-BCA-Timestamp': 'test+07:00'})


    @patch('juloserver.disbursement.clients.bca.BcaClient.get_access_token')
    def test_BcaClient_generate_bca_token_response_case_1(self, mock_get_access_token):
        mock_get_access_token.return_value = ['test','123']

        result = BcaClient(
            'test123',
            'test123',
            'test123',
            'test123',
            self.BCA_BASE_URL,
            'test123',
            'test123'
        )
        result = result.generate_bca_token_response('test123')
        assert result['access_token'] == 'test123'