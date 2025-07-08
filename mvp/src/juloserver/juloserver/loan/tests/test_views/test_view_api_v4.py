from mock import patch
from datetime import datetime

from django.test.testcases import TestCase
from numpy.testing import assert_equal

from juloserver.julo.formulas import round_rupiah
from juloserver.julocore.python2.utils import py2round

from rest_framework.test import APIClient
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
)

from juloserver.ecommerce.tests.factories import IpriceTransactionFactory

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    ProductLookupFactory,
    CreditMatrixRepeatFactory,
    FeatureSettingFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.constants import FeatureNameConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.loan.constants import LoanTaxConst
from juloserver.julo.product_lines import ProductLineCodes


class TestJuloCareLoanDuration(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=5000000)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        TransactionMethod.objects.all().delete()
        self.account_property = AccountPropertyFactory(
            account=self.account,
            is_entry_level=False,
        )
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
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
                    "list_transaction_method_code": [1],
                },
                "whitelist_last_digit": 3,
            },
        )

    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_duration_with_julo_care(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
        mock_julo_care_eligible,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date

        self.fs_zero_interest.is_active = True
        self.fs_zero_interest.save()
        amount = 1_000_000
        IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.self_method,
            version=1,
            interest=0.05,
            provision=0.07,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        mock_julo_care_eligible.return_value = (True, {'3': 20000})

        data = {
            "loan_amount_request": 500000,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": False,
            "is_julo_care": True,
        }
        response = self.client.post('/api/loan/v4/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_failed_serializer(self):
        data = {
            "loan_amount_request": 500000,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": True,
            "is_julo_care": True,
        }
        response = self.client.post('/api/loan/v4/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Non_field_errors Multiple campaign active'])

    def test_failed_request(self):
        data = {
            "loan_amount_request": 500000,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": False,
            "is_julo_care": True,
        }
        response = self.client.post('/api/loan/v4/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()['errors'],
            [
                (
                    'Maaf, Anda tidak bisa menggunakan fitur ini.'
                    'Silakan gunakan fitur lain yang tersedia di menu utama.'
                )
            ],
        )

    @patch('juloserver.loan.views.views_api_v3.validate_max_fee_rule')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_tax_tarik_dana_julo_care(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_julo_care_eligible,
        mock_validate_max_fee_rule,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        self.fs_zero_interest.is_active = True
        self.fs_zero_interest.save()
        amount = 1_000_000
        IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.self_method,
            version=1,
            interest=0.05,
            provision=0.07,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        loan_requested = 500_000
        insurance_fee_1 = 20_000
        data = {
            "loan_amount_request": 500000,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        insurance_rate = float(insurance_fee_1) / float(loan_requested)
        mock_validate_max_fee_rule.return_value = (
            False,
            None,
            None,
            None,
            None,
            insurance_rate,
            None,
        )
        mock_julo_care_eligible.return_value = True, {'3': insurance_fee_1}
        response = self.client.post('/api/loan/v4/loan-duration/', data=data)

        assert response.status_code == 200

        loan_choices = response.json()['data']['loan_choice']
        for choice in loan_choices:
            tax = choice['tax']
            provision = choice['provision_amount']
            loan_amount = choice['loan_amount']
            disbursement_amount = choice['disbursement_amount']
            result_insurance_rate = choice.get('insurance_premium_rate', None)
            insurance_fee = loan_amount * result_insurance_rate
            provision_fee_duration = round_rupiah(loan_requested * credit_matrix_repeat.provision)
            self.assertEqual(provision, (insurance_fee + provision_fee_duration))
            self.assertEqual(insurance_rate, result_insurance_rate)
            self.assertEqual(tax, provision * 0.11)

            disbursement_calc = loan_amount - provision - tax
            self.assertEqual(disbursement_calc, disbursement_amount)

        self.assertEqual(response.status_code, HTTP_200_OK)

    @patch('juloserver.loan.views.views_api_v3.validate_max_fee_rule')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_tax_kirim_dana_julo_care(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_julo_care_eligible,
        mock_validate_max_fee_rule,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        self.fs_zero_interest.is_active = True
        self.fs_zero_interest.save()
        amount = 1_000_000
        IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.self_method,
            version=1,
            interest=0.05,
            provision=0.07,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        loan_requested = 500_000
        data = {
            "loan_amount_request": loan_requested,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": 2,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        insurance_fee = 20_000
        mock_validate_max_fee_rule.return_value = (False, None, None, None, None, None, None)
        mock_julo_care_eligible.return_value = True, {'3': insurance_fee}
        response = self.client.post('/api/loan/v4/loan-duration/', data=data)
        self.assertEqual(response.status_code, 200)
        loan_choices = response.json()['data']['loan_choice']
        for choice in loan_choices:
            tax = choice['tax']
            provision = choice['provision_amount']
            loan_amount = choice['loan_amount']
            disbursement_amount = choice['disbursement_amount']
            self.assertEqual(tax, int(py2round(provision * 0.11)))

            disbursement_calc = loan_amount - provision - tax
            self.assertEqual(disbursement_calc, disbursement_amount)

        self.assertEqual(response.status_code, HTTP_200_OK)
