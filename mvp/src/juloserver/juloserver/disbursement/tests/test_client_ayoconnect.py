
from http import HTTPStatus

from django.conf import settings
from django.test import TestCase
from mock import patch, Mock, call

from juloserver.disbursement.clients.ayoconnect import AyoconnectClient
from juloserver.disbursement.exceptions import AyoconnectApiError
from juloserver.grab.models import (PaymentGatewayVendor, PaymentGatewayApiLog,
                                    PaymentGatewayLogIdentifier)
from juloserver.julo.tests.factories import ApplicationFactory, AuthUserFactory, CustomerFactory
from juloserver.disbursement.utils import generate_unique_id
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from juloserver.disbursement.constants import AyoconnectURLs

fake = Faker()
fake.add_provider(JuloFakerProvider)

json_response_unauthorized = {
    "code": "401",
    "message": "Unauthorised error",
    "responseTime": "20230820020508",
    "errors": [
        {
            "code": "401",
            "message": "Unauthorised error",
            "details": "Token is invalid/expired"
        }
    ]
}

json_response_success_get_access_token = {
    "apiProductList": "[of-oauth, bank-account-disbursement-sandbox, of-merchants-sandbox]",
    "organizationName": "ayoconnect-open-finance",
    "developer.email": "devin.winardi@julofinance.com",
    "tokenType": "BearerToken",
    "responseTime": "20230823160624",
    "clientId": "zKNYhhBpghWquRSNUxqEZoXdWuOGDSBzk1faRZLtmPCaGCSA",
    "accessToken": "7eR3RYuLHtYBnOhcunifeXseYEq4",
    "expiresIn": "3599"
}


def mocked_requests_unauthorized(*args, **kwargs):
    """
    mock all API to unauthorized response, except the get token API
    """

    class MockResponseUnauthorized:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponseUnauthorized(json_response_unauthorized, HTTPStatus.UNAUTHORIZED)
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponseUnauthorized(json_response_success_get_access_token, HTTPStatus.OK)
    elif 'api/v1/bank-disbursements/disbursement' in args[0]:
        return MockResponseUnauthorized(json_response_unauthorized, HTTPStatus.UNAUTHORIZED)
    elif 'api/v1/bank-disbursements/status/' in args[0]:
        return MockResponseUnauthorized(json_response_unauthorized, HTTPStatus.UNAUTHORIZED)
    elif 'api/v1/merchants/balance' in args[0]:
        return MockResponseUnauthorized(json_response_unauthorized, HTTPStatus.UNAUTHORIZED)

    return MockResponseUnauthorized(None, 404)


def mocked_requests_success(*args, **kwargs):
    """
    mock all API to unauthorized response, except the get token API
    """

    class MockResponseSuccess:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponseSuccess({
            "code": 202,
            "message": "ok",
            "responseTime": "20230822120715",
            "transactionId": "vP2hrin12psrrAZC8quoQcQAKKNDMdvC",
            "referenceNumber": "fe0b5fa4942e4c6bbec1b8eed2cd0994",
            "customerId": "JULOTF-135H11AC",
            "beneficiaryDetails": {
                "beneficiaryAccountNumber": "510654300",
                "beneficiaryBankCode": "CENAIDJA",
                "beneficiaryId": "BE_388137e762",
                "beneficiaryName": "N/A",
                "accountType": "N/A"
            }
        }, HTTPStatus.ACCEPTED)
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponseSuccess(json_response_success_get_access_token, HTTPStatus.OK)
    elif 'api/v1/bank-disbursements/disbursement' in args[0]:
        return MockResponseSuccess({
            "code": 202,
            "message": "ok",
            "responseTime": "20230821044409",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdZz",
            "referenceNumber": "4c224c8acde54d51b0d2b6205ca12917",
            "customerId": "JULOTF-135H11D5",
            "transaction": {
                "beneficiaryId": "BE_83c7d11daf",
                "status": 0,
                "referenceNumber": "4c224c8acde54d51b0d2b6205ca12917",
                "amount": "50000.0",
                "currency": "IDR"
            }
        }, HTTPStatus.ACCEPTED)
    elif 'api/v1/bank-disbursements/status/' in args[0]:
        return MockResponseSuccess({
            "code": 202,
            "message": "ok",
            "responseTime": "20230820032920",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdNx",
            "referenceNumber": "618c2a2f624d4083af93c04cd7c5a7c6",
            "customerId": "JULOTF-135H11D5",
            "transaction": {
                "beneficiaryId": "BE_83c7d11daf",
                "status": 1,
                "referenceNumber": "eccaad5e721b4a58b98a7f4640a4a96c",
                "amount": "10000.0",
                "currency": "IDR",
                "remark": "Testing"
            }
        }, HTTPStatus.ACCEPTED)
    elif 'api/v1/merchants/balance' in args[0]:
        return MockResponseSuccess({
            "code": 200,
            "message": "ok",
            "responseTime": "20230823105241",
            "transactionId": "vZ2hrin12psrrAZC8quoQYQAKKNDMxZz",
            "referenceNumber": "a991acdbd6f74c3e860b1ab6185ea456",
            "merchantCode": "JULOTF",
            "accountInfo": [
                {
                    "availableBalance": {
                        "value": "4960000.00",
                        "currency": "IDR"
                    }
                }
            ]
        }, HTTPStatus.OK)

    return MockResponseSuccess({"success": True}, HTTPStatus.OK)


def mocked_requests_pre_conditional_failed(*args, **kwargs):
    """
    mock all API to preconditional response, except the get token API
    """

    class MockResponseSuccess:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponseSuccess({
            "code": 412,
            "message": "precondition.failed",
            "responseTime": "20230820030202",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdNB",
            "referenceNumber": "7fbd8e34fc824344b1e943ad5e16e444",
            "errors": [
                {
                    "code": "0325",
                    "message": "error.validator.0325",
                    "details": "The 'A-Correlation-ID' header is already used"
                }
            ]
        }, HTTPStatus.PRECONDITION_FAILED)
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponseSuccess(json_response_success_get_access_token, HTTPStatus.OK)

    return MockResponseSuccess({"success": True}, HTTPStatus.OK)


def mocked_requests_ayoconnect_system_error_maintenance(*args, **kwargs):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponse({
            "code": 202,
            "message": "ok",
            "responseTime": "20230822120715",
            "transactionId": "vP2hrin12psrrAZC8quoQcQAKKNDMdvC",
            "referenceNumber": "fe0b5fa4942e4c6bbec1b8eed2cd0994",
            "customerId": "JULOTF-135H11AC",
            "beneficiaryDetails": {
                "beneficiaryAccountNumber": "510654300",
                "beneficiaryBankCode": "CENAIDJA",
                "beneficiaryId": "BE_388137e762",
                "beneficiaryName": "N/A",
                "accountType": "N/A"
            }
        }, HTTPStatus.ACCEPTED)
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponse(json_response_success_get_access_token, HTTPStatus.OK)
    elif 'api/v1/bank-disbursements/disbursement' in args[0]:
        return MockResponse({
            "code": 503,
            "message": "service.unavailable",
            "responseTime": "20211015060602",
            "transactionId": "01234567890123456789012345678912",
            "referenceNumber": "027624209e6945678652abe61c91f49c",
            "errors": [
                {
                    "code": "0924",
                    "message": "error.validator.0924",
                    "details": "System under maintenance. Please reach out to customer support for further assistance."
                }
            ]
        }, HTTPStatus.SERVICE_UNAVAILABLE)
    elif 'api/v1/bank-disbursements/status/' in args[0]:
        return MockResponse({
            "code": 202,
            "message": "ok",
            "responseTime": "20230820032920",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdNx",
            "referenceNumber": "618c2a2f624d4083af93c04cd7c5a7c6",
            "customerId": "JULOTF-135H11D5",
            "transaction": {
                "beneficiaryId": "BE_83c7d11daf",
                "status": 1,
                "referenceNumber": "eccaad5e721b4a58b98a7f4640a4a96c",
                "amount": "10000.0",
                "currency": "IDR",
                "remark": "Testing"
            }
        }, HTTPStatus.ACCEPTED)
    elif 'api/v1/merchants/balance' in args[0]:
        return MockResponse({
            "code": 200,
            "message": "ok",
            "responseTime": "20230823105241",
            "transactionId": "vZ2hrin12psrrAZC8quoQYQAKKNDMxZz",
            "referenceNumber": "a991acdbd6f74c3e860b1ab6185ea456",
            "merchantCode": "JULOTF",
            "accountInfo": [
                {
                    "availableBalance": {
                        "value": "4960000.00",
                        "currency": "IDR"
                    }
                }
            ]
        }, HTTPStatus.OK)

    return MockResponse({"success": True}, HTTPStatus.OK)


class TestAyoconnectClient(TestCase):
    def set_client(self):
        return AyoconnectClient(
            self.AYOCONNECT_BASE_URL,
            settings.AYOCONNECT_CLIENT_ID,
            settings.AYOCONNECT_CLIENT_SECRET,
            settings.AYOCONNECT_MERCHANT_CODE,
            settings.AYOCONNECT_LATITUDE,
            settings.AYOCONNECT_LONGITUDE,
            settings.AYOCONNECT_IP_ADDRESS
        )

    def setUp(self):
        self.AYOCONNECT_BASE_URL = settings.AYOCONNECT_BASE_URL
        self.ayo_client = self.set_client()
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_success_get_access_token(self, mock_requests):
        response = self.ayo_client.get_token()
        self.assertEqual(mock_requests.call_count, 1)
        self.assertIsNotNone(response.get("accessToken"))

    @patch('juloserver.disbursement.clients.ayoconnect.logger')
    @patch('juloserver.disbursement.clients.ayoconnect.generate_unique_id')
    @patch('requests.post', side_effect=mocked_requests_success)
    def test_success_create_beneficiary(self, mock_requests, mock_generate_unique_id, mock_logger):
        mocked_unique_id = generate_unique_id()
        mock_generate_unique_id.return_value = mocked_unique_id
        mock_requests.return_value.status_code = HTTPStatus.OK
        log_data = {
            "payment_gateway_vendor_id": self.ayoconnect_payment_gateway_vendor.id,
            "customer_id": self.customer.id,
            "application_id": self.application.id
        }
        response = self.ayo_client.add_beneficiary(
            user_token="tokenabc",
            bank_account="1234567",
            swift_bank_code="cenaidja",
            phone_number="085225443990",
            log_data=log_data
        )
        log_data = PaymentGatewayApiLog.objects.last()
        self.assertIsNotNone(log_data)
        self.assertTrue(mock_requests.called)
        self.assertEqual(response.get("message"), "ok")
        mock_logger.info.assert_called_once_with(
            {'action': 'AyoconnectClient.add_beneficiary',
             'headers': {'Authorization': 'Bearer tokenabc', 'Content-Type': 'application/json',
                         'Accept': 'application/json',
                         'A-Correlation-ID': mocked_unique_id,
                         'A-Merchant-Code': 'JULOTF', 'A-Latitude': '-6.2146',
                         'A-Longitude': '106.845'},
             'payload': {'transactionId': mocked_unique_id,
                         'phoneNumber': '6285225443990',
                         'customerDetails': {'ipAddress': '192.168.100.12'},
                         'beneficiaryAccountDetails': {'accountNumber': '1234567',
                                                       'bankCode': 'cenaidja'}}
             }
        )

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    def test_create_beneficiary_without_retry(self, mock_requests):
        # test not go to retry mechanism
        log_data = {
            "payment_gateway_vendor_id": self.ayoconnect_payment_gateway_vendor.id,
            "customer_id": self.customer.id,
            "application_id": self.application.id
        }
        with self.assertRaises(AyoconnectApiError):
            self.ayo_client.add_beneficiary(
                user_token="tokenabc",
                bank_account="1234567",
                swift_bank_code="cenaidja",
                phone_number="085225443990",
                log_data=log_data,
                is_without_retry=True,
            )
        log_data = PaymentGatewayApiLog.objects.last()
        self.assertIsNotNone(log_data)
        mock_requests.assert_called_once()

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_success_create_disbursement(self, mock_requests):
        mock_requests.return_value.status_code = HTTPStatus.OK
        response = self.ayo_client.create_disbursement(
            user_token="tokenabc",
            ayoconnect_customer_id="1234",
            beneficiary_id="1234567",
            unique_id=generate_unique_id(),
            amount="100000",
            log_data={'customer_id': self.customer.id, 'application_id': self.application.id}
        )
        self.assertTrue(mock_requests.called)
        self.assertEqual(response.get("message"), "ok")

    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_get_disbursement_status(self, mock_requests):
        mock_requests.return_value.status_code = HTTPStatus.OK
        log_data = {
            "payment_gateway_vendor_id": self.ayoconnect_payment_gateway_vendor.id,
            "customer_id": self.customer.id,
            "application_id": self.application.id
        }
        a_correlation_id = "ahdiadiaidaidhiqwin"
        response = self.ayo_client.get_disbursement_status(
            user_token="tokenabc",
            ayoconnect_customer_id="1234",
            beneficiary_id="1234567",
            a_correlation_id=a_correlation_id,
            reference_id="198301kn13ni",
            log_data=log_data
        )
        pg_api_log_identifier = PaymentGatewayLogIdentifier.objects.filter(
            identifier=a_correlation_id).last()
        self.assertTrue(mock_requests.called)
        self.assertEqual(response.get("message"), "ok")
        self.assertTrue(pg_api_log_identifier)
        self.assertEqual(pg_api_log_identifier.identifier, a_correlation_id)
        self.assertIsNotNone(pg_api_log_identifier.query_param)

    @patch('juloserver.disbursement.clients.ayoconnect.logger')
    @patch('juloserver.disbursement.clients.ayoconnect.generate_unique_id')
    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_get_merchant_balance(self, mock_requests, mock_request_post,
                                          mock_generate_unique_id, mock_logger):
        mocked_unique_id = generate_unique_id()
        mock_generate_unique_id.return_value = mocked_unique_id
        response = self.ayo_client.get_merchant_balance(user_token="abcde")
        self.assertEqual(mock_requests.call_count, 1)
        self.assertIsNotNone(response)
        self.assertEqual(response.get("message"), "ok")
        self.assertIsNotNone(response.get("accountInfo")[0].get("availableBalance").get("value"))
        calls = [
            call({
                'action': 'AyoconnectClient.get_merchant_balance',
                'headers': {
                    'Authorization': 'Bearer abcde', 'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'A-Correlation-ID': mocked_unique_id,
                    'A-Merchant-Code': 'JULOTF'},
                'full_url': '{}{}?transactionId={}'.format(
                    self.AYOCONNECT_BASE_URL,
                    AyoconnectURLs.MERCHANT_BALANCE_URL,
                    mocked_unique_id)
            })
        ]
        mock_logger.info.assert_has_calls(calls, any_order=False)

    @patch('requests.post')
    def test_failed_get_access_token(self, mock_requests):
        mock_requests.return_value.status_code = HTTPStatus.PRECONDITION_FAILED
        with self.assertRaises(AyoconnectApiError) as context:
            response = self.ayo_client.get_token()

        self.assertTrue("Failed to get token" in str(context.exception))

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    def test_failed_create_beneficiary_token_expired(self, mock_requests):
        with self.assertRaises(AyoconnectApiError) as context:
            response = self.ayo_client.add_beneficiary(
                user_token="tokenabc",
                bank_account="1234567",
                swift_bank_code="cenaidja",
                phone_number="085225443990"
            )

        self.assertTrue("Failed add beneficiary" in str(context.exception))
        self.assertEqual(mock_requests.call_count, 8)

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    def test_failed_create_disbursement_token_expired(self, mock_requests):
        with self.assertRaises(AyoconnectApiError) as context:
            self.ayo_client.create_disbursement(
                user_token="tokenabc",
                ayoconnect_customer_id="1234",
                beneficiary_id="1234567",
                unique_id=generate_unique_id(),
                amount="100000",
                log_data={'customer_id': self.customer.id, 'application_id': self.application.id}
            )
        self.assertTrue('401' in str(context.exception))
        self.assertEqual(mock_requests.call_count, 2)

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    @patch('requests.get', side_effect=mocked_requests_unauthorized)
    def test_failed_get_disbursement_status_token_expired(self, mock_requests, mock_request_post):
        # will fix later
        with self.assertRaises(AyoconnectApiError) as context:
            self.ayo_client.get_disbursement_status(
                user_token="tokenabc",
                ayoconnect_customer_id="1234",
                beneficiary_id="1234567",
                a_correlation_id="ahdiadiaidaidhiqwin",
                reference_id="198301kn13ni",
                log_data={'customer_id': self.customer.id, 'application_id': self.application.id},
                n_retry=3
            )
        self.assertTrue('unauthorized' in str(context.exception).lower())
        self.assertEqual(mock_requests.call_count, 3)

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    @patch('requests.get', side_effect=mocked_requests_unauthorized)
    def test_failed_get_merchant_balance_token_expired(self, mock_requests, mock_request_post):
        with self.assertRaises(AyoconnectApiError) as context:
            response = self.ayo_client.get_merchant_balance(user_token="tokenabc", n_retry=3)

        self.assertTrue("Unauthorized: 401" in str(context.exception))
        self.assertEqual(mock_requests.call_count, 3)

    @patch('requests.get', side_effect=mocked_requests_success)
    def test_error_get_disbursement_status(self, mock_requests):
        mock_requests.return_value.status_code = HTTPStatus.OK
        log_data = {
            "payment_gateway_vendor_id": self.ayoconnect_payment_gateway_vendor.id,
            "customer_id": self.customer.id,
            "application_id": self.application.id
        }
        a_correlation_id = "ahdiadiaidaidhiqwin"
        response = self.ayo_client.get_disbursement_status(
            user_token="tokenabc",
            ayoconnect_customer_id="1234",
            beneficiary_id="1234567",
            a_correlation_id=a_correlation_id,
            reference_id="198301kn13ni",
            log_data=log_data
        )
        pg_api_log_identifier = PaymentGatewayLogIdentifier.objects.filter(
            identifier=a_correlation_id).last()
        self.assertTrue(mock_requests.called)
        self.assertEqual(response.get("message"), "ok")
        self.assertTrue(pg_api_log_identifier)
        self.assertEqual(pg_api_log_identifier.identifier, a_correlation_id)
        self.assertIsNotNone(pg_api_log_identifier.query_param)

    @patch('requests.get')
    def test_success_no_error(self, mock_get):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        data = {
            'url': 'https://example.com',
            'headers': {'Content-Type': 'application/json'},
            'timeout': 10,
            'n_retry': 3,
            'sleep_duration': 5,
        }

        # Act
        result = self.ayo_client.hit_ayoconnect_with_retry(data, "GET")

        # Assert
        self.assertEqual(result['response'], mock_response)
        self.assertIsNone(result['error'])
        self.assertFalse(result['is_error'])

    @patch(
        'juloserver.disbursement.clients.ayoconnect.send_payment_gateway_vendor_api_alert_slack.delay')
    @patch('requests.post', side_effect=mocked_requests_pre_conditional_failed)
    def test_failed_create_beneficiary_pre_condition_correlation_already_used(self, mock_requests,
                                                                              mock_slack_alert):
        with self.assertRaises(AyoconnectApiError) as context:
            response = self.ayo_client.add_beneficiary(
                user_token="tokenabc",
                bank_account="1234567",
                swift_bank_code="cenaidja",
                phone_number="085225443990"
            )
        mock_slack_alert.assert_called_once()
        self.assertTrue("Failed add beneficiary" in str(context.exception))
        self.assertEqual(mock_requests.call_count, 4)

    @patch('requests.get', side_effect=mocked_requests_success)
    def test_error_get_disbursement_status(self, mock_requests):
        mock_requests.return_value.status_code = HTTPStatus.OK
        log_data = {
            "payment_gateway_vendor_id": self.ayoconnect_payment_gateway_vendor.id,
            "customer_id": self.customer.id,
            "application_id": self.application.id
        }
        a_correlation_id = "ahdiadiaidaidhiqwin"
        response = self.ayo_client.get_disbursement_status(
            user_token="tokenabc",
            ayoconnect_customer_id="1234",
            beneficiary_id="1234567",
            a_correlation_id=a_correlation_id,
            reference_id="198301kn13ni",
            log_data=log_data
        )
        pg_api_log_identifier = PaymentGatewayLogIdentifier.objects.filter(
            identifier=a_correlation_id).last()
        self.assertTrue(mock_requests.called)
        self.assertEqual(response.get("message"), "ok")
        self.assertTrue(pg_api_log_identifier)
        self.assertEqual(pg_api_log_identifier.identifier, a_correlation_id)
        self.assertIsNotNone(pg_api_log_identifier.query_param)

    @patch('requests.get')
    def test_success_no_error(self, mock_get):
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        data = {
            'url': 'https://example.com',
            'headers': {'Content-Type': 'application/json'},
            'timeout': 10,
            'n_retry': 3,
            'sleep_duration': 5,
        }

        # Act
        result = self.ayo_client.hit_ayoconnect_with_retry(data, "GET")

        # Assert
        self.assertEqual(result['response'], mock_response)
        self.assertIsNone(result['error'])
        self.assertFalse(result['is_error'])

