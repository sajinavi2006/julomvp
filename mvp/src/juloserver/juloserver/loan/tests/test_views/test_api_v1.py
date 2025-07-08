from mock import ANY, patch, MagicMock
from datetime import date
from dateutil.relativedelta import relativedelta

from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.constants import CampaignConst

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    ProductLineFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
)
from juloserver.loan.constants import DBRConst
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.tests.factories import LoanDbrLogFactory
from juloserver.loan.models import LoanDbrLog
from juloserver.customer_module.models import CustomerDataChangeRequest
from juloserver.customer_module.constants import CustomerDataChangeRequestConst
from juloserver.cfs.authentication import EasyIncomeWebToken


class TestUserCampaignEligiblelityView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.account = AccountFactory(customer=self.customer)
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30000,
                    "max_loan_amount": 1000000,
                    "min_duration": 2,
                    "max_duration": 5,
                    "list_transaction_method_code": ["1"],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "customer_segments": {
                    "is_ftc": False,
                    "is_repeat": True,
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
                "campaign_content": {
                    "alert_image": "https://statics.julo.co.id/zero_interest/zero_percent_interest_icon.png",
                    "alert_description": "Nikmati <b>bunga 0%</b> untuk semua transaksi <b>maks. Rp3.000.000 dengan jangka waktu <b>1-3 bulan!<b/>",
                    "show_alert": True,
                    "show_pop_up": True,
                    "toggle_title": "Manfaatkan bunga 0%, yuk",
                    "toggle_description": "Penawaran untukmu yang ingin transaksi maks. Rp 3 juta selama 1-3 bulan!",
                    "toggle_link_text": "Pelajari lebih lanjut!",
                    "toggle_click_link": "https://www.julo.co.id",
                },
            },
            is_active=True,
        )

        self.jc_feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CARE_CONFIGURATION,
            parameters={
                'alert_image': 'https://statics.julo.co.id/julo_care/julo_care_icon.png',
                'alert_description': '',
                'show_alert': True,
            },
            is_active=False,
        )

    def test_user_campaign_eligibility_view(self):
        self.jc_feature.is_active = False
        self.jc_feature.save()
        # feature settings true
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        response = self.client.get(url, data)
        self.assertEqual(response.status_code, 200)

        # feature customer segment false
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        self.fs.is_active = False
        self.fs.save()
        response = self.client.get(url, data)
        self.assertEqual(response.json()['data'].get('campaign_name'), '')

        # feature settings false
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        self.fs.is_active = False
        self.fs.save()
        response = self.client.get(url, data)
        self.assertEqual(response.json()['data'].get('campaign_name'), '')

        # customer not have account
        self.account.delete()
        self.customer.refresh_from_db()

        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        response = self.client.get(url, data)
        self.assertEqual(response.json()['data'].get('campaign_name'), '')

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v1.is_customer_can_do_zero_interest')
    def test_get_julo_care_response(self, mock_can_do_zero_interest, mock_julo_care_eligible):
        mock_can_do_zero_interest.return_value = (False, {})
        mock_julo_care_eligible.return_value = (True, {})

        self.jc_feature.is_active = True
        self.jc_feature.save()

        AccountLimitFactory(
            account=self.account,
            latest_credit_score=CreditScoreFactory(application_id=self.application.id),
            available_limit=2000000,
        )

        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        response = self.client.get(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['campaign_name'], CampaignConst.JULO_CARE)

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v1.is_customer_can_do_zero_interest')
    def test_get_julo_care_response_with_other_methods(
        self, mock_can_do_zero_interest, mock_julo_care_eligible
    ):
        mock_can_do_zero_interest.return_value = (False, {})
        mock_julo_care_eligible.return_value = (True, {})

        self.jc_feature.is_active = True
        self.jc_feature.save()

        AccountLimitFactory(
            account=self.account,
            latest_credit_score=CreditScoreFactory(application_id=self.application.id),
            available_limit=2000000,
        )

        data = {'transaction_type_code': TransactionMethodCode.E_COMMERCE.code}
        url = '/api/loan/v1/user-campaign-eligibility'
        response = self.client.get(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['campaign_name'], '')


class TestProductListView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 2,
                    "max_duration": 5,
                    "list_transaction_method_code": ["1"],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
            },
            is_active=False,
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_show_interest_icon(self, mock_proven_graduate):
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/loan/v1/product-list')
        self.assertEqual(response.status_code, 200, response.content)


class TestLoanDbrAPI(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )

    def test_loan_dbr_success(self):
        monthly_income = 10_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        data = {'monthly_installment': 3_000_000, 'duration': 5}
        url = '/api/loan/v1/loan-dbr'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['popup_banner']['is_active'])

    def test_loan_dbr_first_monthly_exceeding(self):
        monthly_income = 10_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        data = {
            'monthly_installment': 3_000_000,
            'duration': 5,
            'first_monthly_installment': 6_000_000,
        }
        url = '/api/loan/v1/loan-dbr'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['popup_banner']['is_active'])

        date_loan = date.today()
        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_CREATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 1)

    def test_loan_dbr_blocked(self):
        monthly_income = 4_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        # feature settings true
        date_loan = date.today()
        LoanDbrLogFactory(
            log_date=date_loan,
            application=application,
            source=DBRConst.LOAN_CREATION,
            transaction_method_id=TransactionMethodCode.SELF.code,
        )
        data = {
            'monthly_installment': 3_000_000,
            'duration': 5,
            'transaction_type_code': TransactionMethodCode.SELF.code,
        }
        url = '/api/loan/v1/loan-dbr'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['popup_banner']['is_active'])

        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_CREATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 2)

    def test_loan_dbr_application_application_status_100(self):
        monthly_income = 4_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 100
        application.save()
        # feature settings true
        data = {'monthly_installment': 3_000_000, 'duration': 5}
        url = '/api/loan/v1/loan-dbr'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['popup_banner']['is_active'])

        date_loan = date.today()
        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_CREATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 0)

    def test_loan_dbr_application_response_status_400(self):
        monthly_income = 4_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        # feature settings true
        data = {
            'monthly_installment': 0,
            'duration': 5,
            'first_monthly_installment': 0,
        }
        url = '/api/loan/v1/loan-dbr'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_get_monthly_salary(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        self.user_token = EasyIncomeWebToken.generate_token_from_user(self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.user_token)
        monthly_income = 4_000_000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        data = {
            'self_bank_account': True,
            'transaction_type_code': 1,
        }
        url = '/api/loan/v1/loan-dbr/get-new-salary/'

        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = None, None
        # test error product not found
        response = self.client.get(url, data)
        self.assertEqual(response.status_code, 404)

        AccountLimitFactory(
            account=self.account,
            latest_credit_score=CreditScoreFactory(application_id=application.id),
            available_limit=20_000_000,
            set_limit=20_000_000,
        )
        product_lookup = ProductLookupFactory(interest_rate=0.48)
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        response = self.client.get(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['monthly_salary'], monthly_income)
        # (20_000_000 / 2 + 20_000_000 * 4%) * 2 + round up nearest 500k
        self.assertEqual(response.json()['data']['new_monthly_salary'], 22_000_000)

    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    def test_update_monthly_salary(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        self.user_token = EasyIncomeWebToken.generate_token_from_user(self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.user_token)
        monthly_income = 4_000_000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        data = {
            'self_bank_account': True,
            'transaction_type_code': 1,
        }
        url = '/api/loan/v1/loan-dbr/get-new-salary/'

        AccountLimitFactory(
            account=self.account,
            latest_credit_score=CreditScoreFactory(application_id=application.id),
            available_limit=20_000_000,
            set_limit=20_000_000,
        )
        product_lookup = ProductLookupFactory(interest_rate=0.48)
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['monthly_salary'], monthly_income)
        self.assertEqual(response.json()['data']['new_monthly_salary'], 22_000_000)

        customer_data = CustomerDataChangeRequest.objects.filter(
            application=application,
            customer=self.customer,
            source=CustomerDataChangeRequestConst.Source.DBR,
            status=CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
        ).last()
        self.assertEqual(customer_data.monthly_income, 22_000_000)


class TestTransactionResultView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)

        self.loan = LoanFactory(
            customer=self.customer,
            product=product_lookup,
        )
        self.account = AccountFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.base_url = '/api/loan/v1/transaction-result'

    def test_loan_not_found(self):
        non_exist_loan_xid = 0
        url = "{}/{}".format(self.base_url, non_exist_loan_xid)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertTrue("Loan not found" in response_data['errors'])

    def test_user_not_allowed(self):
        # user2 attempts to get loan data from another user
        user2 = AuthUserFactory()
        CustomerFactory(user=user2)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user2.auth_expiry_token.key)

        url = "{}/{}".format(self.base_url, self.loan.loan_xid)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 403)
        response_data = response.json()
        self.assertTrue("User not allowed" in response_data['errors'])

    def test_product_not_allowed(self):
        # for example, grab
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        product_lookup = ProductLookupFactory(product_line=product_line)
        self.loan.product = product_lookup
        self.loan.save()

        url = "{}/{}".format(self.base_url, self.loan.loan_xid)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 403)
        response_data = response.json()
        self.assertTrue("Product not allowed" in response_data['errors'])

    @patch("juloserver.loan.views.views_api_v1.TransactionResultAPIService")
    def test_ok(self, mock_service):
        expected_return = {"test": "test"}
        mock_service_instance = MagicMock()
        mock_service.return_value = mock_service_instance

        mock_service_instance.construct_response_data.return_value = expected_return

        url = "{}/{}".format(self.base_url, self.loan.loan_xid)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(expected_return, response_data['data'])


class TestAvailableLimitInfoView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        self.account = AccountFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.base_url = '/api/loan/v1/available-limit-info'

    @patch("juloserver.loan.views.views_api_v1.AvailableLimitInfoAPIService")
    def test_ok(self, mock_service):
        expected_return = {"test": "test"}
        mock_service_instance = MagicMock()
        mock_service.return_value = mock_service_instance

        mock_service_instance.construct_response_data.return_value = expected_return

        url = "{}/{}".format(self.base_url, self.account.id)
        response = self.client.post(
            path=url,
        )
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(expected_return, response_data['data'])

        # with get_cashloan_available_limit param
        # re init mock
        mock_service.reset_mock()
        mock_service.return_value = mock_service_instance

        url = "{}/{}?get_cashloan_available_limit=false".format(self.base_url, self.account.id)
        response = self.client.post(
            path=url,
        )
        mock_service.assert_called_once_with(
            get_cashloan_available_limit=False,
            account_id=self.account.id,
            input=ANY,
        )
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(expected_return, response_data['data'])

        # reinit
        mock_service.reset_mock()
        mock_service.return_value = mock_service_instance
        url = "{}/{}?get_cashloan_available_limit=true".format(self.base_url, self.account.id)
        response = self.client.post(
            path=url,
        )
        self.assertEqual(response.status_code, 200)
        mock_service.assert_called_once_with(
            get_cashloan_available_limit=True,
            account_id=self.account.id,
            input=ANY,
        )

        response_data = response.json()
        self.assertEqual(expected_return, response_data['data'])


class TestLockedProductPageView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        self.account = AccountFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.base_url = '/api/loan/v1/locked-product-page'

    @patch("juloserver.loan.views.views_api_v1.LockedProductPageService")
    def test_ok_mercury_lock(self, mock_service):
        mercury_lock_page = CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY
        expected_return = {"test": "test"}
        mock_service_instance = MagicMock()
        mock_service.return_value = mock_service_instance

        mock_service_instance.construct_response_data.return_value = expected_return
        url = "{}/?page={}".format(self.base_url, mercury_lock_page)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(expected_return, response_data['data'])

        mock_service.assert_called_once_with(
            customer=self.customer,
            input_data=ANY,
        )

        # assert input data's content
        _, kwargs = mock_service.call_args
        input_data = kwargs['input_data']
        self.assertEqual(input_data['page'], mercury_lock_page)

    @patch("juloserver.loan.views.views_api_v1.LockedProductPageService")
    def test_invalid_page(self, mock_service):
        mock_service_instance = MagicMock()
        mock_service.return_value = mock_service_instance

        non_existing_page = "hello_world"

        url = "{}/?page={}".format(self.base_url, non_existing_page)
        response = self.client.get(
            path=url,
        )
        self.assertEqual(response.status_code, 400)

        response_data = response.json()
        self.assertTrue("Invalid page" in response_data['errors'][0])
