from datetime import datetime
from unittest.mock import PropertyMock

from django.conf import settings
from django.test import override_settings
from django.test.testcases import TestCase
from django.utils.dateparse import parse_datetime
from mock import MagicMock, patch
from rest_framework import status
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    BindingResponseCode,
    DanaProductType,
    RepaymentResponseCodeMessage,
    RepaymentReferenceStatus,
    RefundResponseCodeMessage,
)
from juloserver.dana.models import (
    DanaLoanReference,
    DanaRepaymentReference,
    DanaRepaymentReferenceStatus,
)
from juloserver.dana.repayment.tasks import account_reactivation
from juloserver.dana.tests.factories import (
    DanaCustomerDataFactory,
    DanaPaymentBillFactory,
    DanaPaymentFactory,
    DanaAccountPaymentFactory,
    DanaLoanReferenceFactory,
    DanaRepaymentReferenceFactory,
)
from juloserver.dana.utils import create_sha256_signature, hash_body
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    AccountingCutOffDateFactory,
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LenderFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.partnership.constants import PartnershipLender


class TestDanaAuthentication(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        self.client = APIClient()

        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345

        self.payload = {"referenceNo": "90909090"}
        self.endpoint = '/v1.0/registration-account-creation'
        self.method = "POST"
        self.hashed_body = hash_body(self.payload)

        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_failed_authenticated(self, mock_verify_login: MagicMock) -> None:
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE='121212312',
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        mock_verify_login.return_value = False
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json()['responseCode'], BindingResponseCode.INVALID_SIGNATURE.code
        )


class TestDanaPaymentView(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_LATE_FEE,
            parameters={'late_fee': 0.0015},
            is_active=True,
            category='dana',
            description='This configuration is used to adjust dana late fee',
        )
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="Test")
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345
        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_factory = AccountLimitFactory(account=self.account)
        product_line_type = 'DANA'
        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=product_line_type, product_line_code=product_line_code
        )
        StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            dana_customer_identifier="12345679237",
        )
        self.name_bank_validation = NameBankValidationFactory()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()
        self.lender = LenderFactory(lender_name=PartnershipLender.IAF_JTP, user=self.user_partner)
        LenderBalanceCurrentFactory(lender=self.lender, available_balance=100000000)

        self.payload = {
            "partnerReferenceNo": "2020102900000000000001",
            "merchantId": "ijdfNijasdM",
            "amount": {
                "value": "10000.00",
                "currency": "IDR",
            },
            "additionalInfo": {
                "originalOrderAmount": {"value": "190000", "currency": "IDR"},
                "orderInfo": "{\"transactionTime\":\"2022-10-04T08:31:11+07:00\",\"merchantId\":\"216620000050888244260\",\"merchantScenario\":\"216620000050888244260\",\"scenarioSubGrouping\":\"21662000005088824426051051000101000100033\",\"orderInfo\":\"App Store & Apple Music; Purchase on12.27\",\"amount\":\"20000\",\"subMerchantId\":\"2188400000001116\",\"scenarioGrouping\":\"ONLINE\"}",
                "customerId": "12345679237",
                "transTime": "2020-12-17T14:49:00+07:00",
                "lenderProductId": DanaProductType.CICIL,
                "creditUsageMutation": {"value": "10000.00", "currency": "IDR"},
                "agreementInfo": {
                    "partnerEmail": "cs@dana.id",
                    "partnerTnc": "tncUrl.dana.id",
                    "partnerPrivacyRule": "",
                    "provisionFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "lateFeeRate": "0.15",
                    "maxLateFeeDays": "120",
                },
                "billDetailList": [
                    {
                        "billId": "0000011",
                        "periodNo": "1",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "0000012",
                        "periodNo": "2",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "0000013",
                        "periodNo": "3",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "0000014",
                        "periodNo": "4",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                ],
                'repaymentPlanList': [
                    {
                        "billId": "110000011",
                        "periodNo": "1",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "110000012",
                        "periodNo": "2",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "110000013",
                        "periodNo": "3",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                    {
                        "billId": "110000014",
                        "periodNo": "4",
                        "principalAmount": {"value": "22000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                        "totalAmount": {"value": "22000.00", "currency": "IDR"},
                        "dueDate": "20221008",
                    },
                ],
                "installmentConfig": {
                    "installmentType": "MONTHLY",
                    "installmentCount": 4,
                    "dueDateDuration": 14,
                    "principalRoundingScale": 0,
                    "dueDateConfig": "[{\"cutOffEndDate\":21,\"cutOffStartDate\":8,\"dueDate\":27},{\"cutOffEndDate\":7,\"cutOffStartDate\":22,\"dueDate\":13}]",
                    "interestConfig": {
                        "feeMode": "PERCENTAGE",
                        "feeRate": 8.0,
                        "roundingScale": 0,
                        "roundingType": "UP",
                    },
                },
            },
        }
        self.endpoint = '/v1.0/debit/payment-host-to-host'
        self.method = "POST"
        self.hashed_body = hash_body(self.payload)

        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_success_create_loan(self, info_mock: MagicMock, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_success_dana_loan_reference_cdate_equal_with_transtime(
        self, info_mock: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        mock_verify_login.return_value = True
        self.client.post(self.endpoint, data=self.payload, format='json')
        dana_loan_reference = DanaLoanReference.objects.filter(
            partner_reference_no=self.payload["partnerReferenceNo"]
        ).last()
        trans_time_dt = parse_datetime(self.payload["additionalInfo"]["transTime"])
        self.assertEqual(dana_loan_reference.cdate, trans_time_dt)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_empty_partnerReferenceNo(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        del self.payload["partnerReferenceNo"]
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_empty_additionalInfo(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        del self.payload["additionalInfo"]
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_success_create_loan_async(
        self, info_mock: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        FeatureSettingFactory(
            is_active=True,
            category='partner',
            feature_name=FeatureNameConst.DANA_ENABLE_PAYMENT_ASYNCHRONOUS,
            description="Enable or disable dana payment asynchronously process",
            parameters={},
        )
        mock_verify_login.return_value = True
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_create_loan_if_late_fee_rate_not_in_payload(
        self, info_mock: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        mock_verify_login.return_value = True
        del self.payload["additionalInfo"]["agreementInfo"]["lateFeeRate"]
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_create_loan_with_isNeedApproval(
        self, info_mock: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        mock_verify_login.return_value = True
        self.payload["additionalInfo"]['billDetailList'] = []
        self.payload["additionalInfo"]['repaymentPlanList'] = [
            {
                "billId": "0000011",
                "periodNo": "1",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000012",
                "periodNo": "2",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000013",
                "periodNo": "3",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000014",
                "periodNo": "4",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
        ]
        self.payload["additionalInfo"]["isNeedApproval"] = True
        hashed_body = hash_body(self.payload)

        string_to_sign = (
            self.method + ":" + self.endpoint + ":" + hashed_body + ":" + str(self.x_timestamp)
        )
        x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.julo.services2.appsflyer.AppsFlyerService.info_j1_loan_status')
    def test_create_loan_after_isNeedApproval(
        self, info_mock: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        mock_verify_login.return_value = True
        old_payload = self.payload["additionalInfo"]['billDetailList']
        self.payload["additionalInfo"]['billDetailList'] = []
        self.payload["additionalInfo"]['repaymentPlanList'] = [
            {
                "billId": "0000011",
                "periodNo": "1",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000012",
                "periodNo": "2",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000013",
                "periodNo": "3",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000014",
                "periodNo": "4",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
        ]
        self.payload["additionalInfo"]["isNeedApproval"] = True
        hashed_body = hash_body(self.payload)

        string_to_sign = (
            self.method + ":" + self.endpoint + ":" + hashed_body + ":" + str(self.x_timestamp)
        )
        x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Second time hit
        hashed_body = hash_body(self.payload)
        self.payload["additionalInfo"]['billDetailList'] = old_payload
        self.payload["additionalInfo"]["isNeedApproval"] = False
        string_to_sign = (
            self.method + ":" + self.endpoint + ":" + hashed_body + ":" + str(self.x_timestamp)
        )
        x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestDanaRepaymentView(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        AccountingCutOffDateFactory()
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="Test")
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345
        self.endpoint = '/v1.0/debit/repayment-host-to-host/'
        self.method = "POST"
        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        product_line_type = 'DANA'
        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=product_line_type, product_line_code=product_line_code
        )
        StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.status_220 = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.name_bank_validation = NameBankValidationFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            dana_customer_identifier="12345679237",
            lender_product_id=DanaProductType.CICIL,
            application=self.application,
        )
        self.application.account = self.account
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()
        self.dana_customer_data.application = self.application
        self.dana_customer_data.save()
        self.loan = LoanFactory(account=self.account, loan_status=self.status_220)
        self.lender = LenderFactory(lender_name=PartnershipLender.JTP, user=self.user_partner)
        LenderBalanceCurrentFactory(lender=self.lender, available_balance=100000000)
        self.account_payment = DanaAccountPaymentFactory(account=self.account)
        self.payment = DanaPaymentFactory(loan=self.loan, account_payment=self.account_payment)
        self.dana_payment_bill = DanaPaymentBillFactory(
            payment_id=self.payment.id, bill_id="1001001"
        )
        self.payload = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_blank_or_empty_customer_id(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        del self.payload["customerId"]
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_blank_or_empty_partnerReferenceNo(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        del self.payload["partnerReferenceNo"]
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_customerId_not_found(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        self.payload["customerId"] = 1
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['responseCode'], RepaymentResponseCodeMessage.BAD_REQUEST.code
        )

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_billId_not_found(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        self.payload["repaymentDetailList"][0]["billId"] = 1
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['responseCode'], RepaymentResponseCodeMessage.BAD_REQUEST.code
        )

    @patch('juloserver.dana.repayment.services.set_redis_key')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.repayment.serializers.DanaRepaymentSerializer.is_valid')
    @patch(
        'juloserver.dana.repayment.serializers.DanaRepaymentSerializer.validated_data',
        new_callable=PropertyMock,
    )
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_fail_repayment_with_status_loan_is_216(
        self,
        mock_validated_data: MagicMock,
        mock_is_valid: MagicMock,
        mock_verify_login: MagicMock,
        _: MagicMock,
    ) -> None:
        mock_verify_login.return_value = True
        mock_is_valid.return_value = True
        mock_validated_data.return_value = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

        loan_status_216 = StatusLookupFactory(status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER)
        self.loan.update_safely(loan_status=loan_status_216)
        self.loan.refresh_from_db()

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.dana.repayment.services.set_redis_key')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.repayment.serializers.DanaRepaymentSerializer.is_valid')
    @patch(
        'juloserver.dana.repayment.serializers.DanaRepaymentSerializer.validated_data',
        new_callable=PropertyMock,
    )
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_success_dana_repayment(
        self,
        mock_validated_data: MagicMock,
        mock_is_valid: MagicMock,
        mock_verify_login: MagicMock,
        _: MagicMock,
    ) -> None:
        mock_verify_login.return_value = True
        mock_is_valid.return_value = True
        mock_validated_data.return_value = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

        current_limit = self.account_limit.available_limit

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['responseCode'], RepaymentResponseCodeMessage.SUCCESS.code)

        principal_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentPrincipalAmount"]["value"]
        )
        interest_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentInterestFeeAmount"]["value"]
        )
        late_fee_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentLateFeeAmount"]["value"]
        )
        total_limit_replenish = principal_repayment + interest_repayment
        total_repayment_amount = principal_repayment + interest_repayment + late_fee_repayment
        self.account_limit.refresh_from_db()
        limit_after_repayment = self.account_limit.available_limit
        self.assertEqual(limit_after_repayment, current_limit + total_limit_replenish)

        payment_due = self.payment.due_amount
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.due_amount, payment_due - total_repayment_amount)

        current_account_payment_due = self.account_payment.due_amount
        self.account_payment.refresh_from_db()
        account_payment_due = self.account_payment.due_amount
        self.assertEqual(account_payment_due, current_account_payment_due - total_repayment_amount)

    def test_account_reactivation(self) -> None:
        # Set Account Status to 421 / active_in_grace
        self.account.update_safely(
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active_in_grace)
        )
        self.assertEqual(self.account.status_id, AccountConstant.STATUS_CODE.active_in_grace)
        # Run account_reactivation to change to 420 / active
        account_reactivation(self.account.id)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status_id, AccountConstant.STATUS_CODE.active)

    @patch('juloserver.dana.repayment.services.set_redis_key')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.repayment.serializers.DanaRepaymentSerializer.is_valid')
    @patch(
        'juloserver.dana.repayment.serializers.DanaRepaymentSerializer.validated_data',
        new_callable=PropertyMock,
    )
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_success_dana_repayment_partial(
        self,
        mock_validated_data: MagicMock,
        mock_is_valid: MagicMock,
        mock_verify_login: MagicMock,
        _: MagicMock,
    ) -> None:
        mock_verify_login.return_value = True
        mock_is_valid.return_value = True
        mock_validated_data.return_value = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

        current_limit = self.account_limit.available_limit

        self.payload['repaymentDetailList'] = [
            {
                "billId": "1001001",
                "billStatus": "INIT",
                "repaymentPrincipalAmount": {"value": "150000.00", "currency": "IDR"},
                "repaymentInterestFeeAmount": {"value": "10000.00", "currency": "IDR"},
                "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                "totalRepaymentAmount": {"value": "160000.00", "currency": "IDR"},
            }
        ]

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['responseCode'], RepaymentResponseCodeMessage.SUCCESS.code)

        principal_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentPrincipalAmount"]["value"]
        )
        interest_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentInterestFeeAmount"]["value"]
        )
        late_fee_repayment = float(
            self.payload["repaymentDetailList"][0]["repaymentLateFeeAmount"]["value"]
        )
        total_limit_replenish = principal_repayment + interest_repayment
        total_repayment_amount = principal_repayment + interest_repayment + late_fee_repayment
        self.account_limit.refresh_from_db()
        limit_after_repayment = self.account_limit.available_limit

        payment_due = self.payment.due_amount
        self.payment.refresh_from_db()

        current_account_payment_due = self.account_payment.due_amount
        self.account_payment.refresh_from_db()
        account_payment_due = self.account_payment.due_amount

        # Check Status Payment no in PaymentStatusCodes
        status_payment = False
        if self.payment.status not in PaymentStatusCodes.paid_status_codes():
            status_payment = True
        self.assertEqual(False, status_payment)

    @patch('juloserver.dana.repayment.services.set_redis_key')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.repayment.serializers.DanaRepaymentSerializer.is_valid')
    @patch(
        'juloserver.dana.repayment.serializers.DanaRepaymentSerializer.validated_data',
        new_callable=PropertyMock,
    )
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_success_dana_repayment_to_recalculate_payment_and_account_payment(
        self,
        mock_validated_data: MagicMock,
        mock_is_valid: MagicMock,
        mock_verify_login: MagicMock,
        _: MagicMock,
    ) -> None:
        mock_verify_login.return_value = True
        mock_is_valid.return_value = True
        mock_validated_data.return_value = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

        """
            We assume Case Like this:
            Payment 1 (INIT) -> Fail
            Payment 2 (PAID) -> Success
            Payment 1 (INIT) -> Hit again -> Success
        """
        # Hit endpoint /v1.0/debit/repayment-host-to-host/ with bill status PAID
        self.payload['repaymentDetailList'] = [
            {
                "billId": "1001001",
                "billStatus": "PAID",
                "repaymentPrincipalAmount": {"value": "100000.00", "currency": "IDR"},
                "repaymentInterestFeeAmount": {"value": "10000.00", "currency": "IDR"},
                "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                "totalRepaymentAmount": {"value": "110000.00", "currency": "IDR"},
            }
        ]

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['responseCode'], RepaymentResponseCodeMessage.SUCCESS.code)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.due_amount, 0)

        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.due_amount, 0)

        # Hit endpoint /v1.0/debit/repayment-host-to-host/ with bill status INIT
        self.payload['partnerReferenceNo'] = "RPYMNT0107"
        self.payload['repaymentDetailList'] = [
            {
                "billId": "1001001",
                "billStatus": "INIT",
                "repaymentPrincipalAmount": {"value": "150000.00", "currency": "IDR"},
                "repaymentInterestFeeAmount": {"value": "10000.00", "currency": "IDR"},
                "repaymentLateFeeAmount": {"value": "20000.00", "currency": "IDR"},
                "totalRepaymentAmount": {"value": "180000.00", "currency": "IDR"},
            }
        ]

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')

        self.payment.refresh_from_db()
        total_payment = self.payment.paid_interest + self.payment.paid_principal
        payment_due_amount = self.payment.installment_principal + self.payment.installment_interest
        self.assertEqual(self.payment.due_amount, 0)
        self.assertEqual(payment_due_amount, total_payment)
        self.assertEqual(self.payment.paid_late_fee, self.payment.late_fee_amount)

        self.account_payment.refresh_from_db()
        total_account_payment = (
            self.account_payment.paid_interest + self.account_payment.paid_principal
        )
        account_payment_due_amount = (
            self.account_payment.principal_amount + self.account_payment.interest_amount
        )
        self.assertEqual(self.account_payment.due_amount, 0)
        self.assertEqual(account_payment_due_amount, total_account_payment)
        self.assertEqual(self.account_payment.paid_late_fee, self.account_payment.late_fee_amount)

    @patch('juloserver.dana.repayment.views.run_repayment_async_process.delay')
    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.repayment.serializers.DanaRepaymentSerializer.is_valid')
    @patch(
        'juloserver.dana.repayment.serializers.DanaRepaymentSerializer.validated_data',
        new_callable=PropertyMock,
    )
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_async_process_repayment(
        self,
        mock_validated_data: MagicMock,
        mock_is_valid: MagicMock,
        mock_verify_auth: MagicMock,
        mock_repayment_process: MagicMock,
    ) -> None:
        mock_is_valid.return_value = True
        mock_validated_data.return_value = {
            "partnerReferenceNo": "RPYMNT0106",
            "customerId": "12345679237",
            "repaidTime": "2023-01-23T09:50:00+07:00",
            "creditUsageMutation": {"value": "370000.00", "currency": "IDR"},
            "lenderProductId": DanaProductType.CICIL,
            "repaymentDetailList": [
                {
                    "billId": "1001001",
                    "billStatus": "PAID",
                    "repaymentPrincipalAmount": {"value": "250000.00", "currency": "IDR"},
                    "repaymentInterestFeeAmount": {"value": "20000.00", "currency": "IDR"},
                    "repaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                    "totalRepaymentAmount": {"value": "270000.00", "currency": "IDR"},
                }
            ],
            "additionalInfo": {"repaymentId": "2023081221372139"},
        }

        FeatureSettingFactory(
            is_active=True,
            category='partner',
            feature_name=FeatureNameConst.DANA_ENABLE_REPAYMENT_ASYNCHRONOUS,
            description="Enable or disable dana repayment asynchronously process",
            parameters={},
        )

        mock_verify_auth.return_value = True

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['responseCode'], RepaymentResponseCodeMessage.SUCCESS.code)

        dana_repayment_reference = DanaRepaymentReference.objects.last()
        dana_repayment_reference_status = DanaRepaymentReferenceStatus.objects.filter(
            dana_repayment_reference_id=dana_repayment_reference.id
        ).last()

        self.assertTrue(dana_repayment_reference)
        self.assertEqual(dana_repayment_reference_status.status, RepaymentReferenceStatus.PENDING)
        self.assertEqual(mock_repayment_process.call_count, 1)


class TestDanaRefundView(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="Test")
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345
        self.endpoint = '/v1.0/debit/refund/'
        self.method = 'POST'
        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        product_line_type = 'DANA'
        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=product_line_type, product_line_code=product_line_code
        )
        StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.status_220 = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            dana_customer_identifier="12345679237",
        )
        self.name_bank_validation = NameBankValidationFactory()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()
        self.loan = LoanFactory(account=self.account, loan_status=self.status_220)
        self.lender = LenderFactory(lender_name=PartnershipLender.JTP, user=self.user_partner)
        LenderBalanceCurrentFactory(lender=self.lender, available_balance=100000000)
        self.account_payment = DanaAccountPaymentFactory(account=self.account)
        self.payment = DanaPaymentFactory(loan=self.loan, account_payment=self.account_payment)
        self.dana_payment_bill = DanaPaymentBillFactory(
            payment_id=self.payment.id, bill_id="1001001"
        )
        self.dana_loan_reference = DanaLoanReferenceFactory(
            partner_reference_no="DLRRFND0103",
            customer_id=self.customer.id,
            loan=self.loan,
            reference_no="9d8cc404-5a0f-454b-bde4-4f482916402c",
        )
        self.dana_repayment_reference = DanaRepaymentReferenceFactory(
            partner_reference_no="RFND0103",
            customer_id=self.customer.id,
            payment=self.payment,
            bill_id="1001001",
        )
        self.payload = {
            "originalPartnerReferenceNo": "DLRRFND0103",
            "originalReferenceNo": "",
            "originalExternalId": "",
            "partnerRefundNo": "RF9876",
            "refundAmount": {"value": "10000.00", "currency": "IDR"},
            "reason": "Customer complain",
            "additionalInfo": {
                "customerId": "12345679237",
                "refundTime": "2022-12-17T14:49:00+07:00",
                "lenderProductId": DanaProductType.CICIL,
                "creditUsageMutation": {"value": "10000.00", "currency": "IDR"},
                "refundedOriginalOrderAmount": {"value": "10000.00", "currency": "IDR"},
                "disburseBackAmount": {"value": "10000.00", "currency": "IDR"},
                "refundedTransaction": {
                    "refundedPartnerReferenceNo": "DLRRFND0103",
                    "refundedBillDetailList": [
                        {
                            "billId": "1001001",
                            "dueDate": "20230313",
                            "interestFeeAmount": {"currency": "IDR", "value": "120.00"},
                            "lateFeeAmount": {"currency": "IDR", "value": "0.00"},
                            "paidInterestFeeAmount": {"currency": "IDR", "value": "0.00"},
                            "paidLateFeeAmount": {"currency": "IDR", "value": "0.00"},
                            "paidPrincipalAmount": {"currency": "IDR", "value": "0.00"},
                            "periodNo": "1",
                            "principalAmount": {"currency": "IDR", "value": "1500.00"},
                            "totalAmount": {"currency": "IDR", "value": "1620.00"},
                            "totalPaidAmount": {"currency": "IDR", "value": "0.00"},
                        }
                    ],
                },
                "refundedRepaymentDetailList": [
                    {
                        "billId": "1001001",
                        "repaymentPartnerReferenceNo": "RFND0103",
                        "refundedRepaymentPrincipalAmount": {
                            "value": "20000.00",
                            "currency": "IDR",
                        },
                        "refundedRepaymentInterestFeeAmount": {
                            "value": "1000.00",
                            "currency": "IDR",
                        },
                        "refundedRepaymentLateFeeAmount": {"value": "0.00", "currency": "IDR"},
                        "refundedTotalRepaymentAmount": {"currency": "IDR", "value": "21000.00"},
                    }
                ],
            },
        }

    @patch('juloserver.dana.security.is_valid_signature')
    @patch('juloserver.dana.models.DanaPaymentBill.objects.filter')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_success_dana_refund(
        self, mock_dana_payment_bill_filter: MagicMock, mock_verify_login: MagicMock
    ) -> None:
        mock_verify_login.return_value = True
        mock_values_list = MagicMock()
        mock_values_list.order_by.return_value = ['1001001']
        mock_dana_payment_bill_filter.return_value.values_list.return_value = mock_values_list

        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )

        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['responseCode'], RefundResponseCodeMessage.SUCCESS.code)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_failed_blank_or_empty_customer_id(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        del self.payload["additionalInfo"]["customerId"]
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_failed_customerId_not_found(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        self.payload["additionalInfo"]["customerId"] = "12345"
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['responseCode'], RefundResponseCodeMessage.BAD_REQUEST.code
        )

    @patch('juloserver.dana.security.is_valid_signature')
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def test_failed_billId_not_found(self, mock_verify_login: MagicMock) -> None:
        mock_verify_login.return_value = True
        self.payload["additionalInfo"]["refundedTransaction"]["refundedBillDetailList"][0][
            "billId"
        ] = "1"
        self.hashed_body = hash_body(self.payload)
        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['responseCode'], RefundResponseCodeMessage.BAD_REQUEST.code
        )
