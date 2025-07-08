from django.utils import timezone
from mock import patch
from datetime import datetime, timedelta

from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditMatrixRepeatFactory,
    CustomerFactory,
    FeatureSettingFactory,
    ProductLookupFactory,
    StatusLookupFactory,
)
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.loan.services.loan_creation import LoanCreditMatrices
from juloserver.loan.services.token_related import LoanTokenData, LoanTokenService
from juloserver.payment_point.constants import TransactionMethodCode


class TestLoanDurationV5(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=5000000)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
        )
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.fs_zero_interest = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 1,
                    "max_duration": 3,
                    "list_transaction_method_code": ['1', '2', '3'],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
                "customer_segments": {"is_ftc": True, "is_repeat": True},
            },
            is_active=False,
            category="Loan",
            description="All configurations for zero interest higher provision",
        )
        FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={"daily_max_fee": 0.4},
            is_active=True,
            category="credit_matrix",
            description="Test",
        )
        self.show_different_pricing_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHOW_DIFFERENT_PRICING_ON_UI,
            is_active=True,
        )
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method_id=1,
        )

        self.fs_delay_disbursement = FeatureSettingFactory(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            is_active=False,
            category='loan',
            description='Feature Setting For Delay Disbursement',
            parameters={
                "content": {
                    "tnc": "<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>"
                },
                "condition": {
                    "start_time": "00:00",
                    "cut_off": "23:59",
                    "cashback": 25000,
                    "daily_limit": 0,
                    "monthly_limit": 0,
                    "min_loan_amount": 100000,
                    "threshold_duration": 600,
                    "list_transaction_method_code": [
                        TransactionMethodCode.SELF.code,
                        TransactionMethodCode.DOMPET_DIGITAL.code,
                    ],
                },
                "whitelist_last_digit": 3,
            },
        )
        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

    @patch('juloserver.loan.views.views_api_v5.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v5.is_product_locked')
    @patch('juloserver.loan.views.views_api_v5.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v5.get_loan_matrices')
    @patch('juloserver.loan.views.views_api_v5.LoanTokenService.get_expiry_time')
    def test_loan_token_tarik_dana(
        self,
        mock_get_expiry_time,
        mock_get_loan_matrices,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
    ):
        """
        Test Loan Token in the
        """

        token_service = LoanTokenService()

        # setup mock
        mock_get_loan_matrices.return_value = LoanCreditMatrices(
            credit_matrix=self.credit_matrix,
            credit_matrix_product_line=self.credit_matrix_product_line,
            credit_matrix_repeat=None,
        )

        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 29, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_is_product_locked.return_value = False

        # set mock for LoanTokenService expiry time
        now = timezone.localtime(timezone.now())
        expiry_time = now + timedelta(minutes=5)
        mock_get_expiry_time.return_value = expiry_time.timestamp()

        requested_amount = 1_000_000
        data = {
            "loan_amount_request": requested_amount,
            "account_id": self.account.id,
            "transaction_type_code": TransactionMethodCode.SELF.code,
        }

        response = self.client.post('/api/loan/v5/loan-duration/', data=data)

        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        for loan_choice in data['loan_choice']:
            duration = loan_choice['duration']
            token = loan_choice['loan_token']

            token_data = token_service.decrypt(token=token)

            self.assertIsInstance(token_data, LoanTokenData)
            self.assertEqual(token_data.customer_id, self.customer.id)
            self.assertEqual(token_data.loan_duration, duration)
            self.assertEqual(token_data.loan_requested_amount, requested_amount)

            expiry_time = token_data.expiry_time_datetime

            self.assertEqual(expiry_time, now)
