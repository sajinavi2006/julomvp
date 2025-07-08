import mock
import requests

from http import HTTPStatus
from mock import patch, MagicMock
from requests import ConnectTimeout

from django.test import TestCase
from juloserver.disbursement.services import (
    AyoconnectDisbursementProcess,
    PaymentGatewayDisbursementProcess,
)
from juloserver.disbursement.services.ayoconnect import AyoconnectService
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData,
    PaymentGatewayCustomerDataHistory,
    PaymentGatewayApiLog,
    PaymentGatewayTransaction,
    GrabAPILog,
)
from juloserver.grab.tests.factories import PaymentGatewayCustomerDataFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    BankFactory,
    ProductLookupFactory,
    ProductLineFactory,
    WorkflowFactory,
    LenderFactory,
    FeatureSettingFactory,
)
from juloserver.disbursement.constants import (
    DisbursementStatus,
    AyoconnectBeneficiaryStatus,
    NameBankValidationStatus,
    AyoconnectErrorCodes,
    AyoconnectConst,
    DisbursementVendors,
    AyoconnectErrorReason,
    NameBankValidationVendors,
)
from juloserver.disbursement.tests.factories import (
    DisbursementFactory,
    NameBankValidationFactory,
    PaymentGatewayCustomerDataLoanFactory,
)
from juloserver.grab.tests.factories import PaymentGatewayBankCodeFactory
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.disbursement.models import PaymentGatewayCustomerDataLoan, Disbursement2History
from juloserver.disbursement.exceptions import (
    AyoconnectApiError,
    AyoconnectServiceError,
    AyoconnectServiceForceSwitchToXfersError,
)
from juloserver.disbursement.tests.tests_utils import DummyAyoconnectClient, DummySentryClient
from unittest import skip
from juloserver.account.tests.factories import AccountLimitFactory, AccountFactory, \
    AccountLookupFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.grab.clients.paths import GrabPaths
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from juloserver.julo.models import FeatureSetting
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from juloserver.apiv1.constants import BankCodes

fake = Faker()
fake.add_provider(JuloFakerProvider)

json_response_bad_request = {
    "code": 400,
    "message": "bad.request",
    "responseTime": "20211015060602",
    "transactionId": "01234567890123456789012345678912",
    "referenceNumber": "027624209e6945678652abe61c91f49c",
    "errors": [
        {
            "code": "400",
            "message": "error.bad.request",
            "details": "The request can't be processed by the server"
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


def mocked_requests_bad_requests(*args, **kwargs):
    """
    mock all API to bad request response, except the get token API
    """

    class MockResponseUnauthorized:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponseUnauthorized(json_response_bad_request, HTTPStatus.BAD_REQUEST)
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponseUnauthorized(json_response_success_get_access_token, HTTPStatus.OK)
    elif 'api/v1/bank-disbursements/disbursement' in args[0]:
        return MockResponseUnauthorized(json_response_bad_request, HTTPStatus.BAD_REQUEST)
    elif 'api/v1/bank-disbursements/status/' in args[0]:
        return MockResponseUnauthorized(json_response_bad_request, HTTPStatus.BAD_REQUEST)
    elif 'api/v1/merchants/balance' in args[0]:
        return MockResponseUnauthorized(json_response_bad_request, HTTPStatus.BAD_REQUEST)


def mocked_requests_412_requests(*args, **kwargs):
    """
    mock all API to bad request response, except the get token API
    """

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
            "code": 412,
            "message": "bad.request",
            "responseTime": "20211015060602",
            "transactionId": "01234567890123456789012345678912",
            "referenceNumber": "027624209e6945678652abe61c91f49c",
            "errors": [
                {
                    "code": "0325",
                    "message": "error.bad.request",
                    "details": "The request can't be processed by the server"
                }
            ]
        }, HTTPStatus.PRECONDITION_FAILED.value)
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


def mocked_requests_unauthorized(*args, **kwargs):
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
            "code": 401,
            "message": "invalid token",
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
        }, HTTPStatus.UNAUTHORIZED)
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


def mocked_requests_timeout_disbursement(*args, **kwargs):
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
        raise ConnectTimeout()

    return MockResponseSuccess({"success": True}, HTTPStatus.OK)


def mocked_requests_system_under_maintenance_when_beneficiary_id(*args, **kwargs):
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'api/v1/bank-disbursements/beneficiary' in args[0]:
        return MockResponse(
            {
                "code": 503,
                "message": "service.unavailable",
                "responseTime": "20211015060602",
                "transactionId": "01234567890123456789012345678912",
                "referenceNumber": "027624209e6945678652abe61c91f49c",
                "errors": [
                    {
                        "code": "0924",
                        "message": "error.validator.0924",
                        "details": "System under maintenance.",
                    }
                ],
            },
            HTTPStatus.SERVICE_UNAVAILABLE.value,
        )
    elif 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponse(json_response_success_get_access_token, HTTPStatus.OK)

    return MockResponse({"success": True}, HTTPStatus.OK)


class TestAyoconnectServices(TestCase):
    def setUp(self):
        self.ayo_service = AyoconnectService()
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account_lookup = AccountLookupFactory(
            workflow=WorkflowFactory(name=WorkflowConst.GRAB))
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_success_create_new_beneficiary_data(self, mock_requests):
        account_number = "55772012"
        swift_bank_code = "CENAIDJA"
        old_phone_number = None
        new_phone_number = "085225443883"
        registered, updated = self.ayo_service.create_or_update_beneficiary(
            self.customer.id,
            self.application.id,
            account_number,
            swift_bank_code,
            new_phone_number,
            old_phone_number
        )

        pg_cust_data = PaymentGatewayCustomerData.objects.last()
        pg_cust_data_history = PaymentGatewayCustomerDataHistory.objects.last()
        self.assertTrue(registered)
        self.assertFalse(updated)
        self.assertIsNone(pg_cust_data_history)
        self.assertEqual(pg_cust_data.beneficiary_id, "BE_388137e762")
        self.assertEqual(pg_cust_data.external_customer_id, 'JULOTF-135H11AC')
        self.assertEqual(pg_cust_data.customer_id, self.customer.id)
        self.assertEqual(pg_cust_data.phone_number, new_phone_number)

    def fake_PG_disburse(self):
        return True

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_success_create_beneficiary_data_for_j1(self, mock_requests):
        account_number = "55772012"
        swift_bank_code = "CENAIDJA"
        old_phone_number = None
        new_phone_number = "085225443883"

        # already have customer data for customer id
        # but not for phone number & account number, so it will create new customer data
        PaymentGatewayCustomerDataFactory(
            customer_id=self.customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor
        )
        registered, updated = self.ayo_service.create_or_update_beneficiary(
            self.customer.id,
            self.application.id,
            account_number,
            swift_bank_code,
            new_phone_number,
            old_phone_number,
            is_without_retry=True,
            is_j1=True,
        )

        self.assertEqual(PaymentGatewayCustomerData.objects.count(), 2)
        self.assertTrue(registered)
        self.assertFalse(updated)

        # already have customer data for customer id, phone number & account number,
        # so it will update customer data
        registered, updated = self.ayo_service.create_or_update_beneficiary(
            self.customer.id,
            self.application.id,
            account_number,
            swift_bank_code,
            new_phone_number,
            old_phone_number,
            is_without_retry=True,
            is_j1=True,
        )

        self.assertEqual(PaymentGatewayCustomerData.objects.count(), 2)
        self.assertFalse(registered)
        self.assertTrue(updated)

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    def test_failed_create_new_beneficiary_data(self, mock_requests):
        account_number = "55772012"
        swift_bank_code = "CENAIDJA"
        old_phone_number = "085225443882"
        new_phone_number = "085225443883"
        try:
            self.ayo_service.create_or_update_beneficiary(
                self.customer.id,
                self.application.id,
                account_number,
                swift_bank_code,
                old_phone_number,
                new_phone_number
            )
        except AyoconnectServiceError as error:
            assert 'Failed add beneficiary' in str(error)

        pg_cust_data = PaymentGatewayCustomerData.objects.last()
        pg_cust_data_history = PaymentGatewayCustomerDataHistory.objects.last()
        self.assertIsNone(pg_cust_data_history)
        self.assertIsNone(pg_cust_data)

    @patch(
        'requests.post', side_effect=mocked_requests_system_under_maintenance_when_beneficiary_id
    )
    def test_create_beneficiary_id_failed_due_to_system_under_maintenance(self, mock_requests):
        with self.assertRaises(AyoconnectServiceForceSwitchToXfersError) as error:
            self.ayo_service.create_or_update_beneficiary(
                self.customer.id,
                self.application.id,
                account_number="55772012",
                swift_bank_code="CENAIDJA",
                old_phone_number="085225443882",
                new_phone_number="085225443883",
                is_without_retry=True,
            )
        self.assertEqual(error.exception.error_code, AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE)
        self.assertIsNone(PaymentGatewayCustomerData.objects.last())
        self.assertIsNone(PaymentGatewayCustomerDataHistory.objects.last())

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_check_sufficient_balance(self, mock_requests, mock_request_post):
        balance_type, status, balance = self.ayo_service.check_balance(10000)
        self.assertTrue(status)
        self.assertEqual(balance_type, DisbursementStatus.SUFFICIENT_BALANCE)

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_check_insufficient_balance(self, mock_requests, mock_request_post):
        balance_type, status, balance = self.ayo_service.check_balance(1000000000)
        self.assertFalse(status)
        self.assertEqual(balance_type, DisbursementStatus.INSUFICIENT_BALANCE)

    @patch('juloserver.disbursement.services.ayoconnect.logger')
    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_bad_requests)
    def test_failed_get_merchant_balance_with_invalid_balance(self, mock_requests,
                                                              mock_request_post, mock_logger):
        self.ayo_service.check_balance(1000000000)
        mock_logger.error.assert_called()

    def test_success_get_ayoconnect_payment_gateway_vendor(self):
        pg_vendor = self.ayo_service.get_payment_gateway()
        self.assertEqual(pg_vendor.name, "ayoconnect")

    def test_get_beneficiary_id_and_status(self):
        phone_number = "085225443883"
        account_number = "55772012"
        swift_bank_code = "CENAIDJA"

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=phone_number,
            account_number=account_number,
            bank_code=swift_bank_code,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        # has customer data
        beneficiary_id, status = self.ayo_service.get_beneficiary_id_and_status(
            customer_id=self.customer.id,
            phone_number=phone_number,
            account_number=account_number,
            swift_bank_code=swift_bank_code,
        )
        self.assertEqual(beneficiary_id, "123")
        self.assertEqual(status, AyoconnectBeneficiaryStatus.INACTIVE)

        # no customer data
        beneficiary_id, status = self.ayo_service.get_beneficiary_id_and_status(
            customer_id=345254,
            phone_number=phone_number,
            account_number=account_number,
            swift_bank_code=swift_bank_code,
        )
        self.assertEqual(beneficiary_id, None)
        self.assertEqual(status, None)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_get_beneficiary_j1_success(self, mock_requests):
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            )
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS
        )
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=name_bank_validation,
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)
        beneficiary_id, _ = ayo_disbursement_service.get_beneficiary_j1()
        pg_cust_data = PaymentGatewayCustomerData.objects.get_or_none(
            customer_id=self.customer.id
        )
        pg_cust_data.status = AyoconnectBeneficiaryStatus.ACTIVE
        pg_cust_data.save()
        beneficiary_id, _ = ayo_disbursement_service.get_beneficiary_j1()
        pg_cust_data_loan = PaymentGatewayCustomerDataLoan.objects.filter(
            beneficiary_id=beneficiary_id
        ).last()
        self.assertTrue(beneficiary_id)
        self.assertEqual(pg_cust_data_loan.processed, True)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_disburse_j1_success(self, mock_requests):
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            )
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS
        )
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=name_bank_validation,
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)
        # first one is creating
        beneficiary_id, _ = ayo_disbursement_service.get_beneficiary_j1()

        # mock callback already called (status updated to active)
        pg_cust_data = PaymentGatewayCustomerData.objects.get_or_none(
            customer_id=self.customer.id
        )
        pg_cust_data.status = AyoconnectBeneficiaryStatus.ACTIVE
        pg_cust_data.save()

        status = ayo_disbursement_service.disburse_j1()
        self.assertTrue(status)

        beneficiary_id, _ = ayo_disbursement_service.get_beneficiary_j1()
        pg_cust_data_loan = PaymentGatewayCustomerDataLoan.objects.filter(
            beneficiary_id=beneficiary_id
        ).last()
        # check if new PaymentGatewayApiLog have beneficiary_id
        pg_api_log = PaymentGatewayApiLog.objects.get_or_none(beneficiary_id=beneficiary_id)
        self.assertTrue(pg_api_log)
        self.assertEqual(pg_cust_data_loan.processed, True)

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    def test_disburse_j1_failed(self, mock_requests):
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            )
        )
        name_bank_validation = NameBankValidationFactory(
            validation_id=100,
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS
        )
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        with self.assertRaises(AyoconnectServiceError) as error:
            ayo_disbursement_service.get_beneficiary_j1()
        self.assertTrue('400' in str(error.exception))

        # failed because add beneficiary_id return 400
        status = ayo_disbursement_service.disburse_j1()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.FAILED)
        self.assertEqual(disbursement.reason,
                         AyoconnectErrorCodes.GENERAL_FAILED_ADD_BENEFICIARY)

        pg_customer_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number=name_bank_validation.account_number,
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.DISABLED,
        )
        # status is disabled, so it will call update beneficiary
        # -> failed because add beneficiary_id return 400
        status = ayo_disbursement_service.disburse_j1()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.FAILED)
        self.assertEqual(disbursement.reason,
                         AyoconnectErrorCodes.GENERAL_FAILED_ADD_BENEFICIARY)

        # ben_id status is -1, so it will call update beneficiary
        # -> failed because beneficiary_id API response error that need to force to use Xfers
        mock_requests.side_effect = mocked_requests_system_under_maintenance_when_beneficiary_id
        status = ayo_disbursement_service.disburse_j1()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.FAILED)
        self.assertEqual(disbursement.reason, AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE)

        # test case already have pg_customer_data_loan, but the ben callback is unsuccessful
        mock_requests.side_effect = mocked_requests_success
        pg_customer_data_loan = PaymentGatewayCustomerDataLoanFactory(
            beneficiary_id="BE_388137e762",  # this from mock success
            loan=loan,
            disbursement=disbursement,
            processed=True,
        )
        # update disbursement reason to re-create beneficiary id
        disbursement.reason = AyoconnectErrorCodes.GENERAL_FAILED_ADD_BENEFICIARY
        disbursement.save()
        status = ayo_disbursement_service.disburse_j1()
        # False because ben id status is inactive, waiting for the callback
        self.assertFalse(status)
        # disbursement still has the same status with previous time
        # because new ben still inactive, waiting for the callback
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        self.assertEqual(disbursement.reason,
                         'Create new beneficiary id')
        # pg_customer_data_loan.processed = False because need to trigger disburse task via callback
        pg_customer_data_loan.refresh_from_db()
        self.assertEqual(pg_customer_data_loan.processed, False)
        # pg_customer_data.status = Inactive because it already re-generate by calling API
        pg_customer_data.refresh_from_db()
        self.assertEqual(pg_customer_data.status, AyoconnectBeneficiaryStatus.INACTIVE)

        mock_requests.side_effect = mocked_requests_bad_requests
        pg_customer_data.status = AyoconnectBeneficiaryStatus.ACTIVE
        pg_customer_data.save()
        # failed because got 400 when disburse
        status = ayo_disbursement_service.disburse_j1()
        self.assertTrue(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
        self.assertTrue('Failed create disbursement' in disbursement.reason)

        # test timeout case
        mock_requests.side_effect = mocked_requests_timeout_disbursement
        status = ayo_disbursement_service.disburse_j1()
        self.assertTrue(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)

    def test_process_callback_disbursement(self):
        # test INSUFFICIENT_BALANCE callback for J1
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            )
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            disburse_id='6dab30c9e5554a31ac18ee9a03deb5c9',
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        callback_data = {
            "code": 503,
            "message": "service.unavailable",
            "responseTime": "20231121134019",
            "transactionId": disbursement.disburse_id,
            "referenceNumber": "ec88d73a69b045be8d528992f3a0895e",
            "customerId": "JULOTF-B1ZJC9ST",
            "details": {
                "amount": "5520000.00",
                "currency": "IDR",
                "status": 4,
                "beneficiaryId": "BE_932b203039",
                "remark": "Disbursement 10004072891",
                "errors": [
                    {
                        "code": AyoconnectErrorCodes.ACCOUNT_INSUFFICIENT_BALANCE,
                        "message": "error.validator.0401",
                        "details": "Account does not have sufficient balance."
                    }
                ],
                "A-Correlation-ID": "f20d63445e5f47f580f2d1782c7d7771"
            }
        }
        response_disbursement = self.ayo_service.process_callback_disbursement(callback_data)
        self.assertEqual(response_disbursement['status'], DisbursementStatus.FAILED)
        self.assertEqual(response_disbursement['reason'],
                         AyoconnectErrorCodes.ACCOUNT_INSUFFICIENT_BALANCE)

        callback_data['details']['errors'][0]['code'] = (
            AyoconnectErrorCodes.ERROR_OCCURRED_FROM_BANK
        )
        response_disbursement = self.ayo_service.process_callback_disbursement(callback_data)
        self.assertEqual(response_disbursement['status'], DisbursementStatus.FAILED)
        self.assertEqual(response_disbursement['reason'],
                         AyoconnectErrorCodes.ERROR_OCCURRED_FROM_BANK)

        callback_data['details']['errors'][0][
            'code'
        ] = AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE
        response_disbursement = self.ayo_service.process_callback_disbursement(callback_data)
        self.assertEqual(response_disbursement['status'], DisbursementStatus.FAILED)
        self.assertEqual(
            response_disbursement['reason'], AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE
        )

    @patch('requests.post')
    def test_create_disbursement(self, mock_request_post):
        resp = {'transaction': {"status": 1}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = resp
        mock_request_post.return_value = mock_response

        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'unique_id': '1234'
        }

        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.COMPLETED)
        self.assertEqual(mock_request_post.call_count, 1)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    @patch('requests.post')
    def test_timeout_create_disbursement_pending(self, mock_request_post):
        mock_request_post.side_effect = [requests.exceptions.ConnectTimeout] * 3

        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'unique_id': '1234'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.PENDING)
        self.assertEqual(mock_request_post.call_count, 1)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    @patch('requests.post')
    def test_timeout_create_disbursement_pending_no_retry(self, mock_request_post):
        '''
        the expected is it should be pending, means no retry to timeout for create disburse
        '''
        resp = {'transaction': {"status": 1}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = resp
        mock_request_post.return_value = mock_response
        mock_request_post.side_effect = [requests.exceptions.ConnectTimeout] * 2 + [mock_response]

        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'unique_id': '1234'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.PENDING)
        self.assertEqual(mock_request_post.call_count, 1)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('requests.post')
    def test_unauthorized_create_disbursement_failed_at_the_end(self, mock_request_post,
                                                                mock_get_token):
        resp = {'transaction': {"status": 1}}
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.json.return_value = resp
        mock_request_post.return_value = mock_response
        mock_request_post.side_effect = [mock_response] * 3

        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.PENDING)
        self.assertEqual(mock_request_post.call_count, 3)
        self.assertEqual(mock_get_token.call_count, 3)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    @patch('requests.post', side_effect=mocked_requests_unauthorized)
    def test_unauthorized_create_disbursement_failed_at_the_end_with_log(self, mock_get_token):
        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'n_retry': 3,
            'unique_id': '123'
        }

        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.PENDING)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id)
        access_token_log_count = 0
        disbursement_log_count = 0
        from pprint import pprint
        for i in log_after:
            url = i.api_url.lower() if isinstance(i.api_url, str) else ''
            if 'disbursement' in url:
                disbursement_log_count += 1
            elif 'accesstoken' in url:
                access_token_log_count += 1

        self.assertNotEqual(access_token_log_count, 0)
        self.assertNotEqual(disbursement_log_count, 0)

    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('requests.post')
    def test_unauthorized_create_disbursement_success_at_the_end(self, mock_request_post,
                                                                 mock_get_token):
        resp = {'transaction': {"status": 1}}
        mock_responses = []
        for _ in range(2):
            mock_response = MagicMock()
            mock_response.status_code = HTTPStatus.UNAUTHORIZED
            mock_response.json.return_value = resp
            mock_responses.append(mock_response)

        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = resp
        mock_responses.append(mock_response)

        mock_request_post.side_effect = mock_responses

        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        service = AyoconnectService()

        data = {
            'amount': 1000,
            'user_token': 'test token',
            'pg_cust_data': pg_cust_data,
            'remark': 'hoho',
            'log_data': {'customer_id': self.customer.id, 'application_id': self.application.id},
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        response = service.create_disbursement(data)
        self.assertEqual(response.get('status'), DisbursementStatus.COMPLETED)
        self.assertEqual(mock_request_post.call_count, 3)
        self.assertEqual(mock_get_token.call_count, 2)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    def test_other_error_create_disbursement(self):
        for error in [requests.exceptions.RequestException, AyoconnectApiError('error'),
                      requests.exceptions.Timeout, requests.exceptions.ReadTimeout]:
            with patch('requests.post') as mock_request_post:
                resp = {'transaction': {"status": 1}}
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = resp
                mock_request_post.return_value = mock_response
                mock_request_post.side_effect = [error]

                pg_cust_data = PaymentGatewayCustomerDataFactory(
                    payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
                    customer_id=self.customer.id,
                    beneficiary_id="123",
                    status=AyoconnectBeneficiaryStatus.INACTIVE,
                )
                service = AyoconnectService()
                service.sentry_client = DummySentryClient()

                data = {
                    'amount': 1000,
                    'user_token': 'test token',
                    'pg_cust_data': pg_cust_data,
                    'remark': 'hoho',
                    'log_data': {
                        'customer_id': self.customer.id,
                        'application_id': self.application.id
                    },
                    'unique_id': '1234'
                }
                log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id). \
                    count()
                response = service.create_disbursement(data)
                self.assertEqual(response.get('status'), DisbursementStatus.PENDING)
                self.assertEqual(mock_request_post.call_count, 1)
                self.assertTrue(service.sentry_client.capture_exception_called)
                log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id). \
                    count()
                self.assertNotEqual(log_before, log_after)

    def setup_check_disbursement_status(self):
        pg_cust_data = PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS
        )
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
            )
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )

        return {
            'pg_cust_data': pg_cust_data,
            'disbursement': disbursement
        }

    def test_success_check_disbursement_status(self):
        test_cases = [
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                'is_retrying': True
            },
        ]

        for test_case in test_cases:
            with patch('requests.get') as mock_request_get:
                resp = {'transaction': {'status': test_case.get('status')}}
                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.return_value = resp
                mock_request_get.return_value = mock_response

                service = AyoconnectService()

                result = self.setup_check_disbursement_status()
                pg_cust_data = result.get('pg_cust_data')
                disbursement = result.get('disbursement')

                data = {
                    'user_token': 'test token',
                    'ayoconnect_customer_id': pg_cust_data.external_customer_id,
                    'beneficiary_id': pg_cust_data.beneficiary_id,
                    'a_correlation_id': '1212asdfdasf',
                    'reference_id': disbursement.reference_id,
                    'log_data': {
                        'customer_id': self.customer.id,
                        'application_id': self.application.id
                    },
                    'n_retry': 3,
                    'unique_id': '123'
                }
                log_before = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                is_retrying, _ = service.get_disbursement_status(data)
                self.assertEqual(is_retrying, test_case.get('is_retrying'))
                self.assertEqual(mock_request_get.call_count, 1)
                log_after = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                self.assertNotEqual(log_before, log_after)

    @patch('requests.get')
    def test_timeout_check_disbursement_status(self, mock_request_get):
        resp = {'transaction': {'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS}}
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = resp
        mock_request_get.side_effect = [requests.exceptions.Timeout] * 3

        service = AyoconnectService()
        service.client.bypass_sleep = True

        result = self.setup_check_disbursement_status()
        pg_cust_data = result.get('pg_cust_data')
        disbursement = result.get('disbursement')

        data = {
            'user_token': 'test token',
            'ayoconnect_customer_id': pg_cust_data.external_customer_id,
            'beneficiary_id': pg_cust_data.beneficiary_id,
            'a_correlation_id': '1212asdfdasf',
            'reference_id': disbursement.reference_id,
            'log_data': {
                'customer_id': self.customer.id,
                'application_id': self.application.id
            },
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        is_retrying, _ = service.get_disbursement_status(data)
        self.assertEqual(is_retrying, False)
        self.assertEqual(mock_request_get.call_count, 3)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    def test_timeout_check_disbursement_success_at_end(self):
        test_cases = [
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                'is_retrying': True
            },
        ]
        for test_case in test_cases:
            with patch('requests.get') as mock_request_get:
                resp = {'transaction': {'status': test_case.get('status')}}
                side_effects = []
                for _ in range(2):
                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.OK
                    mock_response.json.return_value = resp
                    side_effects.append(requests.exceptions.Timeout)

                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.return_value = resp
                side_effects.append(mock_response)

                mock_request_get.side_effect = side_effects

                service = AyoconnectService()
                service.client.bypass_sleep = True

                result = self.setup_check_disbursement_status()
                pg_cust_data = result.get('pg_cust_data')
                disbursement = result.get('disbursement')

                data = {
                    'user_token': 'test token',
                    'ayoconnect_customer_id': pg_cust_data.external_customer_id,
                    'beneficiary_id': pg_cust_data.beneficiary_id,
                    'a_correlation_id': '1212asdfdasf',
                    'reference_id': disbursement.reference_id,
                    'log_data': {
                        'customer_id': self.customer.id,
                        'application_id': self.application.id
                    },
                    'n_retry': 3,
                    'unique_id': '123'
                }
                log_before = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                is_retrying, _ = service.get_disbursement_status(data)
                self.assertEqual(is_retrying, test_case.get('is_retrying'))
                self.assertEqual(mock_request_get.call_count, 3)
                log_after = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                self.assertNotEqual(log_before, log_after)

    @patch('requests.get')
    def test_other_error_check_disbursement_status(self, mock_request_get):
        # even the disburse status is pending, we not retry it. it's because the request.get raise an error
        resp = {'transaction': {'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED}}
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.OK
        mock_response.json.return_value = resp
        mock_request_get.side_effect = [requests.exceptions.RequestException] * 3

        service = AyoconnectService()
        service.client.bypass_sleep = True

        result = self.setup_check_disbursement_status()
        pg_cust_data = result.get('pg_cust_data')
        disbursement = result.get('disbursement')

        data = {
            'user_token': 'test token',
            'ayoconnect_customer_id': pg_cust_data.external_customer_id,
            'beneficiary_id': pg_cust_data.beneficiary_id,
            'a_correlation_id': '1212asdfdasf',
            'reference_id': disbursement.reference_id,
            'log_data': {
                'customer_id': self.customer.id,
                'application_id': self.application.id
            },
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        is_retrying, _ = service.get_disbursement_status(data)
        self.assertEqual(is_retrying, False)
        self.assertEqual(mock_request_get.call_count, 1)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    def test_other_check_disbursement_success_at_end(self):
        # if you got error other than timeout, dont retry it, just quit, is_retrying should be false
        test_cases = [
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                'is_retrying': False
            },
        ]
        for test_case in test_cases:
            with patch('requests.get') as mock_request_get:
                resp = {'transaction': {'status': test_case.get('status')}}
                side_effects = []
                for _ in range(2):
                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.OK
                    mock_response.json.return_value = resp
                    side_effects.append(requests.exceptions.RequestException)

                mock_response = MagicMock()
                mock_response.status_code = HTTPStatus.OK
                mock_response.json.return_value = resp
                side_effects.append(mock_response)

                mock_request_get.side_effect = side_effects

                service = AyoconnectService()
                service.client.bypass_sleep = True

                result = self.setup_check_disbursement_status()
                pg_cust_data = result.get('pg_cust_data')
                disbursement = result.get('disbursement')

                data = {
                    'user_token': 'test token',
                    'ayoconnect_customer_id': pg_cust_data.external_customer_id,
                    'beneficiary_id': pg_cust_data.beneficiary_id,
                    'a_correlation_id': '1212asdfdasf',
                    'reference_id': disbursement.reference_id,
                    'log_data': {
                        'customer_id': self.customer.id,
                        'application_id': self.application.id
                    },
                    'n_retry': 3,
                    'unique_id': '123'
                }
                log_before = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                is_retrying, _ = service.get_disbursement_status(data)
                self.assertEqual(is_retrying, test_case.get('is_retrying'))
                self.assertEqual(mock_request_get.call_count, 1)
                log_after = PaymentGatewayApiLog.objects.filter(
                    customer_id=self.customer.id).count()
                self.assertNotEqual(log_before, log_after)

    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('requests.get')
    def test_unauthorized_check_disbursement_status(self, mock_request_get, mock_get_token):
        resp = {'transaction': {'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS}}
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.UNAUTHORIZED
        mock_response.json.return_value = resp
        mock_request_get.return_value = mock_response
        mock_request_get.side_effect = [mock_response] * 3

        service = AyoconnectService()
        service.client.bypass_sleep = True

        result = self.setup_check_disbursement_status()
        pg_cust_data = result.get('pg_cust_data')
        disbursement = result.get('disbursement')

        data = {
            'user_token': 'test token',
            'ayoconnect_customer_id': pg_cust_data.external_customer_id,
            'beneficiary_id': pg_cust_data.beneficiary_id,
            'a_correlation_id': '1212asdfdasf',
            'reference_id': disbursement.reference_id,
            'log_data': {
                'customer_id': self.customer.id,
                'application_id': self.application.id
            },
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        is_retrying, _ = service.get_disbursement_status(data)
        self.assertEqual(is_retrying, False)
        self.assertEqual(mock_request_get.call_count, 3)
        self.assertEqual(mock_get_token.call_count, 3)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    def test_unauthorized_check_disbursement_status_success_at_the_end(self):
        test_cases = [
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                'is_retrying': True
            },
        ]
        for test_case in test_cases:
            with patch(
                    'juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token') as mock_get_token:
                with patch('requests.get') as mock_request_get:
                    resp = {'transaction': {'status': test_case.get('status')}}
                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.UNAUTHORIZED
                    mock_response.json.return_value = resp
                    mock_request_get.return_value = mock_response
                    side_effects = [mock_response] * 2

                    mock_response = MagicMock()
                    mock_response.status_code = HTTPStatus.OK
                    mock_response.json.return_value = resp
                    side_effects.append(mock_response)

                    mock_request_get.side_effect = side_effects

                    service = AyoconnectService()
                    service.client.bypass_sleep = True

                    result = self.setup_check_disbursement_status()
                    pg_cust_data = result.get('pg_cust_data')
                    disbursement = result.get('disbursement')

                    data = {
                        'user_token': 'test token',
                        'ayoconnect_customer_id': pg_cust_data.external_customer_id,
                        'beneficiary_id': pg_cust_data.beneficiary_id,
                        'a_correlation_id': '1212asdfdasf',
                        'reference_id': disbursement.reference_id,
                        'log_data': {
                            'customer_id': self.customer.id,
                            'application_id': self.application.id
                        },
                        'n_retry': 3,
                        'unique_id': '123'
                    }
                    log_before = PaymentGatewayApiLog.objects.filter(
                        customer_id=self.customer.id).count()
                    is_retrying, _ = service.get_disbursement_status(data)
                    self.assertEqual(is_retrying, test_case.get('is_retrying'))
                    self.assertEqual(mock_request_get.call_count, 3)
                    self.assertEqual(mock_get_token.call_count, 2)
                    log_after = PaymentGatewayApiLog.objects.filter(
                        customer_id=self.customer.id).count()
                    self.assertNotEqual(log_before, log_after)

    @patch('juloserver.disbursement.clients.ayoconnect.generate_unique_id')
    @patch('juloserver.disbursement.clients.ayoconnect.replace_ayoconnect_transaction_id_in_url')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('requests.get')
    def test_precondition_failed_check_disbursement_status(self, mock_request_get, mock_get_token,
                                                           mock_replace_transaction_id,
                                                           mock_generate_unique_id):
        mock_generate_unique_id.return_value = '1234'
        resp = {'errors': [{'code': "0325"}]}
        mock_response = MagicMock()
        mock_response.status_code = HTTPStatus.PRECONDITION_FAILED
        mock_response.json.return_value = resp
        mock_request_get.return_value = mock_response
        mock_request_get.side_effect = [mock_response] * 3

        service = AyoconnectService()
        service.client.bypass_sleep = True

        result = self.setup_check_disbursement_status()
        pg_cust_data = result.get('pg_cust_data')
        disbursement = result.get('disbursement')

        data = {
            'user_token': 'test token',
            'ayoconnect_customer_id': pg_cust_data.external_customer_id,
            'beneficiary_id': pg_cust_data.beneficiary_id,
            'a_correlation_id': '1212asdfdasf',
            'reference_id': disbursement.reference_id,
            'log_data': {
                'customer_id': self.customer.id,
                'application_id': self.application.id
            },
            'n_retry': 3,
            'unique_id': '123'
        }
        log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        is_retrying, _ = service.get_disbursement_status(data)
        self.assertEqual(is_retrying, False)
        self.assertEqual(mock_request_get.call_count, 3)
        self.assertEqual(mock_get_token.call_count, 0)
        self.assertEqual(mock_replace_transaction_id.call_count, 3)
        self.assertEqual(mock_generate_unique_id.call_count, 4)
        log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
        self.assertNotEqual(log_before, log_after)

    @patch('juloserver.disbursement.clients.ayoconnect.generate_unique_id')
    @patch('juloserver.disbursement.clients.ayoconnect.replace_ayoconnect_transaction_id_in_url')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('requests.get')
    def test_precondition_failed_check_disbursement_status_success_at_the_end(
            self, mock_request_get, mock_get_token, mock_replace_transaction_id,
            mock_generate_unique_id):
        test_cases = [
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'is_retrying': False
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_FAILED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_REFUNDED,
                'is_retrying': True
            },
            {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_CANCELLED,
                'is_retrying': True
            },
        ]

        expected_request_get_call_count = 3
        expected_replace_transaction_id_call_count = 2
        expected_generate_unique_id_call_count = 3

        for test_case in test_cases:
            mock_generate_unique_id.return_value = '1234'
            resp = {'errors': [{'code': "0325"}]}
            mock_response = MagicMock()
            mock_response.status_code = HTTPStatus.PRECONDITION_FAILED.value
            mock_response.json.return_value = resp
            mock_request_get.return_value = mock_response
            side_effects = [mock_response] * 2

            mock_generate_unique_id.return_value = '1234'
            resp = {'transaction': {'status': test_case.get('status')}}
            mock_response = MagicMock()
            mock_response.status_code = HTTPStatus.OK
            mock_response.json.return_value = resp
            side_effects.append(mock_response)

            mock_request_get.side_effect = side_effects

            service = AyoconnectService()
            service.client.bypass_sleep = True

            result = self.setup_check_disbursement_status()
            pg_cust_data = result.get('pg_cust_data')
            disbursement = result.get('disbursement')

            data = {
                'user_token': 'test token',
                'ayoconnect_customer_id': pg_cust_data.external_customer_id,
                'beneficiary_id': pg_cust_data.beneficiary_id,
                'a_correlation_id': '1212asdfdasf',
                'reference_id': disbursement.reference_id,
                'log_data': {
                    'customer_id': self.customer.id,
                    'application_id': self.application.id
                },
                'n_retry': 3,
                'unique_id': '123'
            }
            log_before = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
            is_retrying, _ = service.get_disbursement_status(data)
            self.assertEqual(is_retrying, test_case.get('is_retrying'))
            self.assertEqual(mock_request_get.call_count, expected_request_get_call_count)
            self.assertEqual(mock_get_token.call_count, 0)
            self.assertEqual(mock_replace_transaction_id.call_count,
                             expected_replace_transaction_id_call_count)
            self.assertEqual(mock_generate_unique_id.call_count,
                             expected_generate_unique_id_call_count)

            log_after = PaymentGatewayApiLog.objects.filter(customer_id=self.customer.id).count()
            self.assertNotEqual(log_before, log_after)
            mock_request_get.reset_mock()
            mock_replace_transaction_id.reset_mock()
            mock_generate_unique_id.reset_mock()

    @patch('juloserver.disbursement.services.ayoconnect.generate_unique_id')
    @patch('requests.post', side_effect=mocked_requests_success)
    def test_disburse_grab_success(self, mock_requests, mock_generate_unique_id):
        mock_generate_unique_id.return_value = fake.numerify(text="#%#%#%")
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
            account_number="55772012",
        )
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            ),
            name_bank_validation_id=name_bank_validation.id,
        )
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=name_bank_validation,
            account_number="55772012",
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=None,
            account_number="55772012",
            bank_code="CENAIDJA",
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.ACTIVE,
        )
        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse_grab()
        disbursement.refresh_from_db()

        self.assertTrue(mock_generate_unique_id.called)
        self.assertTrue(status)
        call_args = None
        for i in mock_requests.call_args:
            if 'headers' in i:
                call_args = i
                break

        correlation_id = call_args['headers']['A-Correlation-ID']
        transaction_id = call_args['json']['transactionId']
        self.assertEqual(correlation_id, transaction_id)

        pg_transactions = PaymentGatewayTransaction.objects.filter(
            disbursement_id=disbursement.id
        )
        self.assertTrue(pg_transactions.exists())
        pg_transaction = pg_transactions.last()
        self.assertEqual(pg_transaction.disbursement_id, disbursement.id)
        self.assertEqual(pg_transaction.correlation_id, correlation_id)
        self.assertEqual(pg_transaction.transaction_id, transaction_id)
        self.assertEqual(pg_transaction.payment_gateway_vendor.name, 'ayoconnect')
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
        self.assertTrue(Disbursement2History.objects.filter(disbursement=disbursement).count() > 1)

    @patch('requests.post', side_effect=mocked_requests_412_requests)
    def test_disburse_grab_412_do_nothing(self, mock_requests):
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
            account_number="55772012",
        )
        loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            ),
            name_bank_validation_id=name_bank_validation.id,
        )
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=name_bank_validation,
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=None,
            account_number="55772012",
            bank_code="CENAIDJA",
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.ACTIVE,
        )
        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse_grab()
        disbursement.refresh_from_db()

        self.assertTrue(status)
        call_args = None
        for i in mock_requests.call_args:
            if 'headers' in i:
                call_args = i
                break

        correlation_id = call_args['headers']['A-Correlation-ID']
        transaction_id = call_args['json']['transactionId']
        self.assertEqual(correlation_id, transaction_id)

        pg_transactions = PaymentGatewayTransaction.objects.filter(
            disbursement_id=disbursement.id
        )
        self.assertTrue(pg_transactions.exists())
        pg_transaction = pg_transactions.last()
        self.assertEqual(pg_transaction.disbursement_id, disbursement.id)
        self.assertEqual(pg_transaction.correlation_id, correlation_id)
        self.assertEqual(pg_transaction.transaction_id, transaction_id)
        self.assertEqual(pg_transaction.payment_gateway_vendor.name, 'ayoconnect')
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        disbursement_history = Disbursement2History.objects.filter(disbursement=disbursement)
        self.assertTrue(disbursement_history.exists())
        self.assertEqual(disbursement_history.last().disburse_status, DisbursementStatus.INITIATED)
        self.assertTrue("0325" in disbursement.reason)

    @patch.object(PaymentGatewayDisbursementProcess, 'disburse_grab', fake_PG_disburse)
    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_failed')
    @patch('juloserver.loan.services.lender_related.update_committed_amount_for_lender_balance')
    @patch('juloserver.disbursement.services.get_new_disbursement_flow')
    def test_disburse_grab_redirected_to_pg_service_with_blocked_beneficiary(
        self,
        get_new_disbursement_flow,
        mock_commit_lender_balance,
        mock_ayoconnect_loan_disbursement_failed,
        mock_request_post,
    ):

        get_new_disbursement_flow.return_value = DisbursementVendors.XFERS, True
        mock_commit_lender_balance.return_value = True
        product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        bank = BankFactory(bank_code=BankCodes.BCA)
        name_bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method=NameBankValidationVendors.PAYMENT_GATEWAY,
            account_number=123,
            name_in_bank='test',
            bank_code=bank.bank_code,
            validation_status=NameBankValidationStatus.SUCCESS,
            bank=bank,
        )
        application = ApplicationFactory(customer=self.customer,
                                         workflow=WorkflowFactory(name=WorkflowConst.GRAB),
                                         name_bank_validation=name_bank_validation)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
        )
        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=self.account,
            product=product,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination,
            name_bank_validation_id=name_bank_validation.id,
        )
        AccountLimitFactory(account=loan.account)

        GrabAPILog.objects.create(loan_id=loan.id,
                                  query_params=GrabPaths.LOAN_CREATION,
                                  http_status_code=HTTPStatus.OK
                                  )

        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER,
            is_active=True)

        disbursement = DisbursementFactory(
            method="Ayoconnect",
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number=name_bank_validation.account_number,
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id=fake.numerify(text="#%#%#%"),
            status=AyoconnectBeneficiaryStatus.BLOCKED,
        )

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.method, DisbursementVendors.PG)
        self.assertEqual(disbursement.retry_times, 0)
        self.assertFalse(mock_ayoconnect_loan_disbursement_failed.called)

    @patch('juloserver.disbursement.services.ayoconnect.generate_unique_id')
    @patch('requests.post', side_effect=mocked_requests_success)
    def test_disburse_grab_success_transaction_not_found_case(self, mock_requests,
                                                              mock_generate_unique_id):
        mock_generate_unique_id.return_value = fake.numerify(text="#%#%#%")
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
            account_number="55772012",
        )
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=212),
            product=ProductLookupFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
            ),
            name_bank_validation_id=name_bank_validation.id,
            application=None,
        )
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=name_bank_validation,
            account_number=name_bank_validation.account_number,
        )
        disbursement = DisbursementFactory(
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        self.application.bank_account_number = name_bank_validation.account_number
        self.application.save()
        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=None,
            account_number="55772012",
            bank_code="CENAIDJA",
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.ACTIVE,
        )
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            status=DisbursementStatus.FAILED,
            reason=AyoconnectErrorReason.ERROR_TRANSACTION_NOT_FOUND,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor
        )
        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse_grab()
        disbursement.refresh_from_db()

        self.assertFalse(mock_generate_unique_id.called)
        self.assertTrue(status)
        call_args = None
        for i in mock_requests.call_args:
            if 'headers' in i:
                call_args = i
                break

        correlation_id = call_args['headers']['A-Correlation-ID']
        transaction_id = call_args['json']['transactionId']
        self.assertEqual(correlation_id, transaction_id)

        pg_transactions = PaymentGatewayTransaction.objects.filter(
            disbursement_id=disbursement.id
        )
        self.assertTrue(pg_transactions.exists())
        pg_transaction = pg_transactions.last()
        self.assertEqual(pg_transaction.disbursement_id, disbursement.id)
        self.assertEqual(pg_transaction.correlation_id, correlation_id)
        self.assertEqual(pg_transaction.transaction_id, transaction_id)
        self.assertEqual(pg_transaction.payment_gateway_vendor.name, 'ayoconnect')
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)

    @patch(
        'juloserver.grab.segmented_tasks.disbursement_tasks.trigger_create_or_update_ayoconnect_beneficiary.delay'
    )
    def test_disburse_grab_with_inactive_beneficiary(
        self, mock_trigger_create_or_update_ayoconnect_beneficiary
    ):

        product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        name_bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        application = ApplicationFactory(customer=self.customer,
                                         workflow=WorkflowFactory(name=WorkflowConst.GRAB),
                                         name_bank_validation=name_bank_validation)
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number=name_bank_validation.account_number,
        )
        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=self.account,
            product=product,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination,
            name_bank_validation_id=name_bank_validation.id,
        )
        disbursement = DisbursementFactory(
            method="Ayoconnect",
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number=name_bank_validation.account_number,
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id=fake.numerify(text="#%#%#%"),
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        self.assertEqual(disbursement.method, DisbursementVendors.AYOCONNECT)
        self.assertEqual(disbursement.reason, AyoconnectErrorReason.ERROR_BENEFICIARY_INACTIVE)
        self.assertTrue(mock_trigger_create_or_update_ayoconnect_beneficiary.called)

    @patch(
        'juloserver.grab.segmented_tasks.disbursement_tasks.trigger_create_or_update_ayoconnect_beneficiary.delay'
    )
    def test_disburse_grab_with_nonmatching_beneficiary(
        self, mock_trigger_create_or_update_ayoconnect_beneficiary
    ):

        product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        name_bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        application = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
            name_bank_validation=name_bank_validation,
        )
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number=name_bank_validation.account_number,
        )
        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=self.account,
            product=product,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination,
            name_bank_validation_id=name_bank_validation.id,
        )
        disbursement = DisbursementFactory(
            method="Ayoconnect",
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation,
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number="567",
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id=fake.numerify(text="#%#%#%"),
            status=AyoconnectBeneficiaryStatus.ACTIVE,
        )

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        self.assertEqual(disbursement.method, DisbursementVendors.AYOCONNECT)
        self.assertEqual(
            disbursement.reason, AyoconnectErrorReason.ERROR_BENEFICIARY_MISSING_OR_DISABLED
        )
        self.assertTrue(mock_trigger_create_or_update_ayoconnect_beneficiary.called)

    @patch(
        'juloserver.grab.segmented_tasks.disbursement_tasks.trigger_create_or_update_ayoconnect_beneficiary.delay'
    )
    def test_disburse_grab_with_disabled_beneficiary(
        self, mock_trigger_create_or_update_ayoconnect_beneficiary
    ):

        product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        name_bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        application = ApplicationFactory(customer=self.customer,
                                         workflow=WorkflowFactory(name=WorkflowConst.GRAB),
                                         name_bank_validation=name_bank_validation)
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
        )
        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=self.account,
            product=product,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination
        )
        disbursement = DisbursementFactory(
            method="Ayoconnect",
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number=name_bank_validation.account_number,
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id=fake.numerify(text="#%#%#%"),
            status=AyoconnectBeneficiaryStatus.DISABLED,
        )

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse()
        self.assertFalse(status)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        self.assertEqual(disbursement.method, DisbursementVendors.AYOCONNECT)
        self.assertEqual(disbursement.reason,
                         AyoconnectErrorReason.ERROR_BENEFICIARY_MISSING_OR_DISABLED)
        self.assertTrue(mock_trigger_create_or_update_ayoconnect_beneficiary.called)

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    def test_disburse_grab_pending_with_blocked_beneficiary(self, mock_julo_one_disbursement_process,
                                                            mock_request_post):

        product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        name_bank_validation = NameBankValidationFactory(
            validation_id=100,
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        application = ApplicationFactory(customer=self.customer,
                                         workflow=WorkflowFactory(name=WorkflowConst.GRAB),
                                         name_bank_validation=name_bank_validation)
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
        )
        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=self.account,
            product=product,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination,
            name_bank_validation_id=name_bank_validation.id,
        )
        AccountLimitFactory(account=loan.account)

        GrabAPILog.objects.create(
            loan_id=loan.id, query_params=GrabPaths.LOAN_CREATION, http_status_code=HTTPStatus.OK
        )

        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER, is_active=True
        )

        disbursement = DisbursementFactory(
            method="Ayoconnect",
            external_id=loan.loan_xid,
            name_bank_validation=name_bank_validation,
        )
        ayo_bank = PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_destination.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        loan.disbursement_id = disbursement.id
        loan.save()

        PaymentGatewayCustomerDataFactory(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            customer_id=self.customer.id,
            phone_number=self.customer.phone,
            account_number=name_bank_validation.account_number,
            bank_code=ayo_bank.swift_bank_code,
            beneficiary_id="123",
            status=AyoconnectBeneficiaryStatus.BLOCKED,
        )

        ayo_disbursement_service = AyoconnectDisbursementProcess(disbursement)

        status = ayo_disbursement_service.disburse()
        self.assertFalse(status)
        self.assertTrue(mock_julo_one_disbursement_process.called)



class TestAyoconnectBeneficiaryTurnedOff(TestCase):
    def setUp(self):
        self.feature_name = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
            is_active=True,
            parameters={'xfers_ratio': '100%', 'ac_ratio': '0%'},
        )
        self.customer = CustomerFactory()
        self.name_bank_validation = NameBankValidationFactory()
        self.bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer, name_bank_validation=self.name_bank_validation
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=52),
            application_status=StatusLookupFactory(status_code=190),
            name_bank_validation=self.name_bank_validation,
        )
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()

    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService')
    def test_no_beneficiary_call_on_zero_ac(self, mocked_ac_service):
        mocked_service = mock.MagicMock()
        mocked_bank_obj = mock.MagicMock()
        mocked_bank_obj.swift_bank_code = "SWIFT"
        mocked_service.get_payment_gateway_bank.return_value = mocked_bank_obj
        mocked_service.create_or_update_beneficiary.return_value = None
        mocked_ac_service.return_value = mocked_service
        trigger_create_or_update_ayoconnect_beneficiary(self.customer.id)
        mocked_service.create_or_update_beneficiary.assert_not_called()
        mocked_service.get_payment_gateway_bank.assert_not_called()

    @patch('juloserver.grab.segmented_tasks.disbursement_tasks.AyoconnectService')
    def test_no_beneficiary_call_on_non_zero_ac(self, mocked_ac_service):
        self.feature_name.parameters = {'xfers_ratio': '50%', 'ac_ratio': '50%'}
        self.feature_name.save()
        mocked_service = mock.MagicMock()
        mocked_bank_obj = mock.MagicMock()
        mocked_bank_obj.swift_bank_code = "SWIFT"
        mocked_service.get_payment_gateway_bank.return_value = mocked_bank_obj
        mocked_service.create_or_update_beneficiary.return_value = None
        mocked_ac_service.return_value = mocked_service
        trigger_create_or_update_ayoconnect_beneficiary(self.customer.id)
        mocked_service.get_payment_gateway_bank.assert_called()
        mocked_service.create_or_update_beneficiary.assert_called()

    @patch('juloserver.grab.segmented_tasks.disbursement_tasks.AyoconnectService')
    def test_no_beneficiary_call_on_non_zero_ac_update_phone(self, mocked_ac_service):
        self.feature_name.parameters = {'xfers_ratio': '50%', 'ac_ratio': '50%'}
        self.feature_name.save()
        mocked_service = mock.MagicMock()
        mocked_bank_obj = mock.MagicMock()
        mocked_bank_obj.swift_bank_code = "SWIFT"
        mocked_service.get_payment_gateway_bank.return_value = mocked_bank_obj
        mocked_service.create_or_update_beneficiary.return_value = None
        mocked_ac_service.return_value = mocked_service
        trigger_create_or_update_ayoconnect_beneficiary(self.customer.id, update_phone=True)
        mocked_service.get_payment_gateway_bank.assert_called()
        mocked_service.create_or_update_beneficiary.assert_called()

    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService')
    def test_no_beneficiary_call_on_zero_ac_update_phone(self, mocked_ac_service):
        mocked_service = mock.MagicMock()
        mocked_bank_obj = mock.MagicMock()
        mocked_bank_obj.swift_bank_code = "SWIFT"
        mocked_service.get_payment_gateway_bank.return_value = mocked_bank_obj
        mocked_service.create_or_update_beneficiary.return_value = None
        mocked_ac_service.return_value = mocked_service
        trigger_create_or_update_ayoconnect_beneficiary(self.customer.id, update_phone=True)
        mocked_service.create_or_update_beneficiary.assert_not_called()
        mocked_service.get_payment_gateway_bank.assert_not_called()
