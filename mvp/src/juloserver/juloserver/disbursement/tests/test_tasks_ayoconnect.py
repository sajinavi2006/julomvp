import mock
from http import HTTPStatus
from mock import patch

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import MagicMock
import datetime
from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory, AccountLookupFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.exceptions import AyoconnectServiceError
from juloserver.disbursement.models import Disbursement
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory
from juloserver.grab.tests.factories import (
    GrabCustomerDataFactory,
    PaymentGatewayApiLogFactory,
    PaymentGatewayLogIdentifierFactory,
    PaymentGatewayApiLogArchivalFactory
)
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import StatusLookup, FeatureSetting
from juloserver.julo.tests.factories import (CustomerFactory, ApplicationFactory, PartnerFactory,
                                             StatusLookupFactory, AuthUserFactory,
                                             LoanFactory, ProductLookupFactory, ProductLineFactory,
                                             BankFactory, FeatureSettingFactory, WorkflowFactory,
                                             LenderFactory)
from juloserver.grab.models import (PaymentGatewayVendor, PaymentGatewayCustomerData,
                                    PaymentGatewayApiLog, PaymentGatewayApiLogArchival,
                                    PaymentGatewayBankCode,
                                    PaymentGatewayLogIdentifier, PaymentGatewayTransaction,
                                    GrabAPILog)
from juloserver.disbursement.constants import (
    DisbursementVendors,
    NameBankValidationStatus,
    NameBankValidationVendors,
)
from juloserver.disbursement.services.ayoconnect import AyoconnectService
from juloserver.disbursement.constants import DisbursementStatus
from juloserver.disbursement.tasks import (
    check_payment_gateway_vendor_balance,
    check_disbursement_status_schedule,
    verify_ayoconnect_loan_disbursement_status,
    payment_gateway_api_log_archival_task,
    remove_duplicate_archive_log,
)
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from unittest import skip
from juloserver.disbursement.services import PaymentGatewayDisbursementProcess
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from juloserver.grab.clients.paths import GrabPaths
from freezegun import freeze_time

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


def mocked_requests_transaction_not_found(*args, **kwargs):
    """
    mock check disbursement status API to (412) transaction not found.
    """

    class MockResponseSuccess:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

    if 'v1/oauth/client_credential/accesstoken?grant_type=client_credentials' in args[0]:
        return MockResponseSuccess(json_response_success_get_access_token, HTTPStatus.OK)
    elif 'api/v1/bank-disbursements/status/' in args[0]:
        return MockResponseSuccess({
            "code": 412,
            "message": "precondition.failed",
            "responseTime": "20231219131246",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdZz",
            "referenceNumber": "ab63e4780ec34d0a88ff8fa26ce3a1fd",
            "errors": [
                {
                    "code": "0213",
                    "message": "error.internal.0213",
                    "details": "Transaction was not found. Please reach out to customer support for further assistance."
                }
            ]
        }, HTTPStatus.PRECONDITION_FAILED)

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

    return MockResponseUnauthorized(None, 404)


class TestAyoconnectTasks(TestCase):
    def setUp(self):
        self.ayo_service = AyoconnectService()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.disbursement = DisbursementFactory(
            method=DisbursementVendors.AYOCONNECT,
            cdate=timezone.localtime(timezone.now() - timedelta(hours=3)),
            disburse_status=DisbursementStatus.PENDING
        )
        self.name_bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='HELLOQWE',
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            partner=self.partner,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            name_bank_validation=self.name_bank_validation
        )
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.bank = BankFactory(xfers_bank_code=self.name_bank_validation.bank_code)
        self.payment_gateway_bank_code = PaymentGatewayBankCode.objects.create(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=self.bank.id,
            swift_bank_code="CENAIDJA",
            is_active=True
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            customer=self.customer,
            name_bank_validation=self.name_bank_validation,
        )

    def fake_create_or_update_beneficiary(self, customer_id, last_active_app_id, account_number,
                                          swift_bank_code,
                                          new_phone_number, old_phone_number):
        return True

    def fake_PG_disburse(self):
        return True

    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_bad_requests)
    def test_failed_get_vendor_balance_token_expired(self, mock_requests, mock_request_post):
        self.assertEqual(None, check_payment_gateway_vendor_balance())

    @patch('slackclient.SlackClient.api_call')
    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_check_payment_gateway_vendor_balance(self, mock_requests, mock_request_post,
                                                          mock_get_slack_bot_client):
        payment_gateway_alert_feature_setting = FeatureSetting.objects.update_or_create(
            feature_name=FeatureNameConst.PAYMENT_GATEWAY_ALERT
        )
        parameters = {
            "slack_alert_dev": True,
            "slack_alert_staging": True,
            "slack_alert_uat": True,
            "slack_alert_prod": True
        }
        payment_gateway_alert_feature_setting = payment_gateway_alert_feature_setting[0]
        payment_gateway_alert_feature_setting.update_safely(
            is_active=True,
            parameters=parameters
        )
        check_payment_gateway_vendor_balance()
        self.assertEqual((DisbursementStatus.INSUFICIENT_BALANCE, False, '4960000.00'),
                         self.ayo_service.check_balance(1000000000))
        self.assertTrue(mock_get_slack_bot_client.called)

    @patch('slackclient.SlackClient.api_call')
    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('requests.get', side_effect=mocked_requests_success)
    def test_success_check_payment_gateway_vendor_balance_with_feature_setting(self, mock_requests,
                                                                               mock_request_post,
                                                                               mock_get_slack_bot_client):
        random_int = fake.random_int(5000000, 20000000)
        formatted_random_int = "{:,}".format(random_int).replace(',', '.')
        parameters = {
            "slack_alert_dev": True,
            "slack_alert_staging": True,
            "slack_alert_uat": True,
            "slack_alert_prod": True,
            "min_balance_ayoconnect": random_int
        }

        payment_gateway_alert_feature_setting = FeatureSetting.objects.update_or_create(
            feature_name=FeatureNameConst.PAYMENT_GATEWAY_ALERT
        )

        payment_gateway_alert_feature_setting = payment_gateway_alert_feature_setting[0]
        payment_gateway_alert_feature_setting.update_safely(
            parameters=parameters,
            is_active=True,
            category="payment_gateway"
        )
        check_payment_gateway_vendor_balance()
        self.assertEqual((DisbursementStatus.INSUFICIENT_BALANCE, False, '4960000.00'),
                         self.ayo_service.check_balance(1000000000))
        self.assertTrue(mock_get_slack_bot_client.called)
        self.assertIn(formatted_random_int,
                      mock_get_slack_bot_client.call_args[1].get('text'))

    @patch('juloserver.disbursement.tasks.logger')
    def test_success_check_payment_gateway_vendor_balance_with_feature_setting_off(self,
                                                                                   mock_logger):
        random_int = fake.random_int(5000000, 20000000)
        formatted_random_int = "{:,}".format(random_int).replace(',', '.')
        parameters = {
            "slack_alert_staging": True,
            "slack_alert_uat": True,
            "slack_alert_prod": True,
            "min_balance_ayoconnect": random_int
        }

        payment_gateway_alert_feature_setting = FeatureSetting.objects.update_or_create(
            feature_name=FeatureNameConst.PAYMENT_GATEWAY_ALERT
        )

        payment_gateway_alert_feature_setting = payment_gateway_alert_feature_setting[0]
        payment_gateway_alert_feature_setting.update_safely(
            parameters=parameters,
            is_active=False,
            category="payment_gateway"
        )
        check_payment_gateway_vendor_balance()
        mock_logger.info.assert_called_with({'action': 'check_payment_gateway_vendor_balance',
                                             'message': "payment_gateway_alert_feature_setting doesn't exist or inactivated"})

    def test_success_trigger_create_or_update_ayoconnect_beneficiary(self):
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.update_safely(application_status=status_lookup)
        feature_name = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
            is_active=True,
            parameters={'xfers_ratio': '50%', 'ac_ratio': '50%'},
        )
        with patch.object(AyoconnectService, 'create_or_update_beneficiary',
                          MagicMock(
                              side_effect=self.fake_create_or_update_beneficiary)) as fake_create_or_update_beneficiary:
            trigger_create_or_update_ayoconnect_beneficiary(self.customer.id)
            fake_create_or_update_beneficiary.assert_called()

    @patch.object(PaymentGatewayDisbursementProcess, 'disburse_grab', fake_PG_disburse)
    @patch('requests.post', side_effect=mocked_requests_bad_requests)
    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_failed')
    @patch('juloserver.loan.services.lender_related.update_committed_amount_for_lender_balance')
    @patch('juloserver.disbursement.services.get_new_disbursement_flow')
    @patch(
        'juloserver.loan.services.loan_related.trigger_grab_loan_sync_api_async_task.apply_async')
    def test_failure_trigger_create_or_update_ayoconnect_beneficiary_disbursement_timeout(
            self,
            mock_loan_sync,
            mock_get_new_disbursement_flow,
            mock_commit_lender_balance,
            mock_ayoconnect_loan_disbursement_failed,
            mock_request_post
    ):
        mock_get_new_disbursement_flow.return_value = DisbursementVendors.XFERS, True
        mock_commit_lender_balance.return_value = True

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, name='grab')
        customer = CustomerFactory()
        account_lookup = AccountLookupFactory(workflow=self.workflow)
        account = AccountFactory(customer=customer, account_lookup=account_lookup)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)

        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)

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
        bank_account_destination = BankAccountDestinationFactory(
            bank=bank,
            customer=customer,
            name_bank_validation=name_bank_validation,
        )

        application = ApplicationFactory(
            customer=customer,
            account=account,
            partner=partner,
            product_line=product_line,
            workflow=self.workflow,
            application_status=status_lookup,
            name_bank_validation=name_bank_validation,
        )

        PaymentGatewayBankCode.objects.create(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=bank.id,
            swift_bank_code="CENAIDJAJA",
            is_active=True,
        )

        application.update_safely(application_status=status_lookup)

        lender = LenderFactory()
        LenderBalanceCurrentFactory(lender=lender)
        loan = LoanFactory(
            lender=lender,
            application_id2=application.id,
            account=account,
            product=ProductLookupFactory(product_line=self.product_line),
            customer=customer,
            loan_status=StatusLookupFactory(status_code=212),
            bank_account_destination=bank_account_destination,
            loan_xid=fake.numerify(text="#%#%#%"),
        )
        loan_status = StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        loan.loan_status = loan_status
        disbursement = DisbursementFactory(
            method=DisbursementVendors.AYOCONNECT,
            cdate=timezone.localtime(timezone.now() - timedelta(hours=3)),
            disburse_status=DisbursementStatus.INITIATED,
            name_bank_validation=name_bank_validation,
            external_id=loan.loan_xid,
        )
        feature_name = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
            is_active=True,
            parameters={'xfers_ratio': '0%', 'ac_ratio': '100%'},
        )
        loan.disbursement_id = disbursement.id
        loan.save()
        GrabAPILog.objects.create(loan_id=loan.id,
                                  query_params=GrabPaths.LOAN_CREATION,
                                  http_status_code=HTTPStatus.OK
                                  )
        AccountLimitFactory(account=loan.account)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER,
            is_active=True
        )
        with patch.object(
                AyoconnectService, 'create_or_update_beneficiary', MagicMock(
                    side_effect=AyoconnectServiceError(
                        'TEST'))) as fake_create_or_update_beneficiary:
            trigger_create_or_update_ayoconnect_beneficiary(customer.id)
            fake_create_or_update_beneficiary.assert_called()
        loan.refresh_from_db()
        disbursement.refresh_from_db()

        self.assertEqual(disbursement.method, DisbursementVendors.PG)

    @patch('juloserver.grab.segmented_tasks.disbursement_tasks.logger')
    def test_failed_trigger_create_or_update_ayoconnect_beneficiary_with_J1_app(self, mock_logger):
        user = AuthUserFactory()
        partner = PartnerFactory(user=user)
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        name_bank_validation = NameBankValidationFactory()
        application = ApplicationFactory(
            customer=customer,
            account=account,
            partner=partner,
            product_line=product_line,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            name_bank_validation=name_bank_validation
        )
        feature_name = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
            is_active=True,
            parameters={'xfers_ratio': '50%', 'ac_ratio': '50%'},
        )
        application.update_safely(application_status=status_lookup)
        trigger_create_or_update_ayoconnect_beneficiary(customer.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'trigger_create_or_update_ayoconnect_beneficiary',
                'customer_id': customer.id,
                'message': "Customer doesn't have active GRAB application"}
        )


class TestAyoconnectDisbursementStatus(TestCase):
    def setUp(self):
        self.ayo_service = AyoconnectService()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.product = ProductLookupFactory(product_line=self.product_line)
        self.disbursement = DisbursementFactory(
            method=DisbursementVendors.AYOCONNECT,
            cdate=timezone.localtime(timezone.now() - timedelta(hours=3)),
            disburse_status=DisbursementStatus.PENDING
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account,
            disbursement_id=self.disbursement.id,
            product=self.product
        )
        self.beneficiary_id = "test123"
        self.external_customer_id = "JULO-XXI"
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.payment_gateway_customer_data = PaymentGatewayCustomerData.objects.create(
            customer_id=self.customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            beneficiary_id=self.beneficiary_id,
            external_customer_id=self.external_customer_id
        )
        self.payment_gateway_transaction = PaymentGatewayTransaction.objects.create(
            disbursement_id=self.disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id="ahdiadiaidaidhiqwin"
        )
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=5000000)

        self.response = {
            "code": 202,
            "message": "ok",
            "responseTime": "20230820032920",
            "transactionId": "vP2hrin12psrrAZC8quoQYQAKKNDMdNx",
            "referenceNumber": "618c2a2f624d4083af93c04cd7c5a7c6",
            "customerId": "JULOTF-135H11D5",
            "transaction": {
                "beneficiaryId": "BE_83c7d11daf",
                "referenceNumber": "eccaad5e721b4a58b98a7f4640a4a96c",
                "amount": "10000.0",
                "currency": "IDR",
                "remark": "Testing"
            }
        }
        self.data = {
            'application_id': self.application.id,
            'pg_customer_data_id': self.payment_gateway_customer_data.id,
            'payment_gateway_transaction_id': self.payment_gateway_transaction.id,
            'disbursement_id': self.disbursement.id
        }

    @mock.patch('juloserver.disbursement.tasks.logger.info')
    @mock.patch('django.utils.timezone.localtime')
    def test_check_disbursement_status_schedule_with_invalid_loan(
            self, mocked_time: MagicMock,
            mock_logger: MagicMock) -> None:
        datetime_now = datetime.datetime.now()
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.loan.disbursement_id = 33
        self.loan.save(update_fields=['disbursement_id'])
        check_disbursement_status_schedule()
        mock_logger.assert_called_with({'task': 'check_disbursement_status_schedule',
                                        'disbursement_id': self.disbursement.id,
                                        'status': 'loan not found'})

    @mock.patch('juloserver.disbursement.tasks.logger.info')
    @mock.patch('django.utils.timezone.localtime')
    def test_check_disbursement_status_schedule_with_invalid_pg_customer_data(
            self, mocked_time: MagicMock,
            mock_logger: MagicMock) -> None:
        datetime_now = datetime.datetime.now()
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.customer1 = CustomerFactory()
        self.payment_gateway_customer_data.customer_id = self.customer1.id
        self.payment_gateway_customer_data.save(update_fields=['customer_id'])
        check_disbursement_status_schedule()
        mock_logger.assert_called_with({'task': 'check_disbursement_status_schedule',
                                        'loan_id': self.loan.id,
                                        'status': 'pg_customer_data not found'})

    @mock.patch('juloserver.disbursement.tasks.logger.info')
    @mock.patch('django.utils.timezone.localtime')
    def test_check_disbursement_status_schedule_with_missing_payment_gateway_transaction(
            self, mocked_time: MagicMock,
            mock_logger: MagicMock) -> None:
        datetime_now = datetime.datetime.now()
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.payment_gateway_transaction.update_safely(disbursement_id=33)
        check_disbursement_status_schedule()
        if self.loan.is_j1_or_jturbo_loan():
            mock_logger.assert_called_with({'task': 'check_disbursement_status_schedule',
                                            'loan_id': self.loan.id,
                                            'status': 'skip J1 & JTurbo'})

        else:
            mock_logger.assert_called_with(
                {'task': 'check_disbursement_status_schedule', 'loan_id': self.loan.id,
                 'status': 'payment_gateway_transaction not found'})

    @freeze_time("2023-01-01 15:00:00")
    @mock.patch('juloserver.disbursement.tasks.verify_ayoconnect_loan_disbursement_status')
    def test_check_disbursement_status_schedule_with_success_status(
            self, mock_verify_ac_loan_disb_status: MagicMock) -> None:
        custom_datetime = datetime.datetime(year=2023, month=1, day=1,
                                            hour=12, minute=00, second=00)
        self.disbursement.update_safely(cdate=custom_datetime)
        check_disbursement_status_schedule()
        mock_verify_ac_loan_disb_status.delay.assert_called_with(
            {'application_id': self.application.id,
             'pg_customer_data_id': self.payment_gateway_customer_data.id,
             'payment_gateway_transaction_id': self.payment_gateway_transaction.id,
             'disbursement_id': self.disbursement.id
             }
        )

    @skip(reason="Flaky")
    @patch('juloserver.disbursement.services.get_disbursement_by_obj')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_disburse_status')
    def test_verify_ayoconnect_loan_disbursement_status_success_with_completed_status(
            self, mock_request: MagicMock,
            mock_get_disbursement_by_obj: MagicMock
    ) -> None:
        self.response['transaction']['status'] = 1
        mock_get_disbursement_by_obj.return_value = None
        mock_request.return_value = False, self.response
        verify_ayoconnect_loan_disbursement_status(self.data)
        self.disbursement.refresh_from_db()
        # still pending cos waiting for callback
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.PENDING)

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_success')
    @patch('juloserver.disbursement.services.get_disbursement_by_obj')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_disburse_status')
    def test_verify_ayoconnect_loan_disbursement_status_success_with_refunded_status(
            self, mock_request: MagicMock,
            mock_get_disbursement_by_obj: MagicMock,
            mock_ayoconnect_loan_disbursement_success: MagicMock
    ) -> None:
        self.response['transaction']['status'] = 2
        mock_get_disbursement_by_obj.return_value = None
        mock_ayoconnect_loan_disbursement_success.return_value = None
        mock_request.return_value = False, self.response
        verify_ayoconnect_loan_disbursement_status(self.data)
        self.disbursement.refresh_from_db()
        # still pending cos waiting for callback
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.PENDING)

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_success')
    @patch('juloserver.disbursement.services.get_disbursement_by_obj')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_disburse_status')
    def test_verify_ayoconnect_loan_disbursement_status_success_with_cancelled_status(
            self, mock_request: MagicMock,
            mock_get_disbursement_by_obj: MagicMock,
            mock_ayoconnect_loan_disbursement_success: MagicMock
    ) -> None:
        self.response['transaction']['status'] = 3
        mock_get_disbursement_by_obj.return_value = None
        mock_ayoconnect_loan_disbursement_success.return_value = None
        mock_request.return_value = False, self.response
        verify_ayoconnect_loan_disbursement_status(self.data)
        self.disbursement.refresh_from_db()
        # still pending cos waiting for callback
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.PENDING)

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_success')
    @patch('juloserver.disbursement.services.get_disbursement_by_obj')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_disburse_status')
    def test_verify_ayoconnect_loan_disbursement_status_success_with_failed_status(
            self, mock_request: MagicMock,
            mock_get_disbursement_by_obj: MagicMock,
            mock_ayoconnect_loan_disbursement_success: MagicMock
    ) -> None:
        self.response['transaction']['status'] = 4
        mock_get_disbursement_by_obj.return_value = None
        mock_ayoconnect_loan_disbursement_success.return_value = None
        mock_request.return_value = False, self.response
        verify_ayoconnect_loan_disbursement_status(self.data)
        self.disbursement.refresh_from_db()
        # still pending cos waiting for callback
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.PENDING)

    @patch('requests.post', side_effect=mocked_requests_transaction_not_found)
    @patch('requests.get', side_effect=mocked_requests_transaction_not_found)
    @patch('juloserver.disbursement.tasks.ayoconnect_loan_disbursement_failed')
    def test_verify_ayoconnect_loan_disbursement_status_with_transaction_not_found(
            self,
            mock_ayoconnect_loan_disbursement_failed,
            mock_requests,
            mock_request_post
    ) -> None:
        verify_ayoconnect_loan_disbursement_status(self.data)
        self.disbursement.refresh_from_db()
        self.payment_gateway_transaction.refresh_from_db()
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.FAILED)
        self.assertEqual(self.payment_gateway_transaction.status, "FAILED")
        self.assertEqual(self.payment_gateway_transaction.reason, "transaction not found")
        mock_ayoconnect_loan_disbursement_failed.assert_called_once()
        mock_ayoconnect_loan_disbursement_failed.assert_called_with(self.loan)


class TestPaymentGatewayApiLogArchival(TestCase):
    def setUp(self):
        today = timezone.now()
        older_than_30_days = (today - timedelta(days=31)).\
            replace(hour=0, minute=0, second=0, microsecond=0)

        logs = []
        self.logs_id = []
        self.n_data = 10
        self.half_n_data = int(self.n_data/2)
        for _ in range(self.half_n_data):
            log = PaymentGatewayApiLogFactory()
            log.cdate = today
            log.save()
            logs.append(log)
            PaymentGatewayLogIdentifierFactory(payment_gateway_api_log=log)
            self.logs_id.append(log.id)

        self.old_logs_id = []
        for _ in range(self.half_n_data):
            log = PaymentGatewayApiLogFactory()
            self.old_logs_id.append(log.id)
            log.cdate = older_than_30_days
            log.save()
            logs.append(log)
            PaymentGatewayLogIdentifierFactory(payment_gateway_api_log=log)
            self.logs_id.append(log.id)

    @patch("juloserver.disbursement.tasks.send_payment_gateway_vendor_api_alert_slack.delay")
    def test_archival_log(self, mock_send_payment_gateway_alert):
        logs = PaymentGatewayApiLog.objects.filter(id__in=self.logs_id)
        self.assertEqual(len(logs), self.n_data)
        logs_mapping = {}
        for log in logs.iterator():
            logs_mapping[log.id] = {'cdate': log.cdate, 'udate': log.udate}

        self.assertEqual(PaymentGatewayLogIdentifier.objects.all().count(), self.n_data)

        archive_logs = PaymentGatewayApiLogArchival.objects.all()
        self.assertEqual(len(archive_logs), 0)

        logs_archived = payment_gateway_api_log_archival_task()
        self.assertEqual(logs_archived, self.half_n_data)

        logs = PaymentGatewayApiLog.objects.filter(id__in=self.logs_id).count()
        self.assertEqual(logs, self.half_n_data)

        archive_logs = PaymentGatewayApiLogArchival.objects.filter(id__in=self.logs_id)
        self.assertEqual(len(archive_logs), self.half_n_data)

        self.assertEqual(PaymentGatewayLogIdentifier.objects.all().count(), self.half_n_data)

        # make the sure the cdate and udate is not changed
        for log in archive_logs.iterator():
            self.assertTrue(log.id in logs_mapping)
            self.assertEqual(log.cdate, logs_mapping[log.id]['cdate'])
            self.assertEqual(log.udate, logs_mapping[log.id]['udate'])

        mock_send_payment_gateway_alert.assert_called_with(
            msg_header='[Payment Gateway API logs archived] success archived 5 logs', msg_type=3)

    @patch("juloserver.disbursement.tasks.send_payment_gateway_vendor_api_alert_slack.delay")
    def test_archival_log_no_data(self, mock_send_payment_gateway_alert):
        logs = PaymentGatewayApiLog.objects.filter(id__in=self.logs_id).update(
            cdate=timezone.now())
        self.assertTrue(logs > 0)

        logs_archived = payment_gateway_api_log_archival_task()
        self.assertEqual(logs_archived, 0)

        logs = PaymentGatewayApiLog.objects.filter(id__in=self.logs_id).count()
        self.assertTrue(logs > 0)

        mock_send_payment_gateway_alert.assert_called_with(
            msg_header='[Payment Gateway API logs archived] success archived 0 logs', msg_type=3)

    def test_handle_duplicate_archival_log(self):
        n_duplicate = 3
        for index in range(n_duplicate):
            PaymentGatewayApiLogArchivalFactory(id=self.old_logs_id[index])

        api_log_qs = PaymentGatewayApiLog.objects.filter(id__in=self.old_logs_id)
        self.assertEqual(api_log_qs.count(), self.half_n_data)
        result = remove_duplicate_archive_log(list(api_log_qs))
        self.assertEqual(len(result), self.half_n_data - n_duplicate)

    @patch("juloserver.disbursement.tasks.send_payment_gateway_vendor_api_alert_slack.delay")
    def test_archival_log_duplicate_data(self, mock_send_payment_gateway_alert):
        for i in range(3):
            PaymentGatewayApiLogArchivalFactory(id=self.old_logs_id[i])

        logs_archived = payment_gateway_api_log_archival_task()
        self.assertEqual(logs_archived, self.half_n_data)

        archive_logs = PaymentGatewayApiLogArchival.objects.all()
        self.assertEqual(len(archive_logs), self.half_n_data)
