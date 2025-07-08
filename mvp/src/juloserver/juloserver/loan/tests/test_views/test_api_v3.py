from unittest.mock import MagicMock, call, ANY
from django.conf import settings
from rest_framework.response import Response

from past.utils import old_div
from spyne import application
from juloserver.julocore.python2.utils import py2round
from mock import patch
import math
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from django.contrib.contenttypes.models import ContentType
from django.test.testcases import TestCase
from rest_framework.test import APIClient
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
)

from juloserver.disbursement.constants import NameBankValidationStatus, NameBankValidationVendors
from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationVerificationFactory,
    BalanceConsolidationFactory,
    FintechFactory,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.ecommerce.tests.factories import (
    IpriceTransactionFactory,
    JuloShopTransactionFactory,
)
from juloserver.ecommerce.constants import JuloShopTransactionStatus
from juloserver.education.tests.factories import (
    LoanStudentRegisterFactory,
    SchoolFactory,
    StudentRegisterFactory,
)
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.healthcare.models import HealthcareUser
from juloserver.julo.models import Loan, Payment, SepulsaTransaction, Bank
from juloserver.julo.partners import PartnerConstant

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerFactory,
    DocumentFactory,
    PaymentFactory,
    ProductLookupFactory,
    LoanFactory,
    CreditMatrixRepeatFactory,
    PartnerFactory,
    LenderFactory,
    ProductProfileFactory,
    FeatureSettingFactory,
    LenderDisburseCounterFactory,
    StatusLookupFactory,
    ProductLineFactory,
    SepulsaProductFactory,
    WorkflowFactory, MobileFeatureSettingFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
)
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from juloserver.loan.constants import (
    LoanPurposeConst,
    LoanFeatureNameConst,
    DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST,
    LoanJuloOneConstant,
    LoanDigisignFeeConst,
)
from juloserver.loan.services.feature_settings import AnaTransactionModelSetting
from juloserver.loan.tests.factories import (
    TransactionMethodFactory,
    TransactionModelCustomerFactory,
    TransactionRiskyDecisionFactory,
    LoanDbrLogFactory,
    LoanAdditionalFeeFactory,
    LoanAdditionalFeeTypeFactory,
    LoanTransactionDetailFactory,
)
from juloserver.payment_point.constants import (
    TransactionMethodCode,
    SepulsaProductCategory,
    SepulsaProductType,
)
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.julo.constants import FeatureNameConst, ApplicationStatusCodes, WorkflowConst
from juloserver.payment_point.models import (
    TransactionMethod,
    AYCProduct,
    AYCEWalletTransaction,
    XfersEWalletTransaction,
    XfersProduct,
)
from juloserver.julocore.python2.utils import py2round
from django.db.models import Sum
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.models import (
    AdditionalLoanInformation,
    LoanZeroInterest,
    LoanAdditionalFeeType,
    LoanJuloCare,
    LoanDbrLog,
    LoanAdditionalFee,
    TenorBasedPricing,
    LoanTransactionDetail,
    LoanDelayDisbursementFee,
    TransactionModelCustomerLoan,
)
from juloserver.loan.services.loan_related import (
    adjust_loan_with_zero_interest,
    get_loan_amount_by_transaction_type,
)
from juloserver.loan.services.adjusted_loan_matrix import (
    get_adjusted_total_interest_rate,
    validate_max_fee_rule,
    calculate_loan_amount_non_tarik_dana_delay_disbursement,
    get_adjusted_loan_non_tarik_dana,
    get_adjusted_monthly_interest_rate_case_exceed,
)
from juloserver.julo.formulas import round_rupiah
from juloserver.account.constants import AccountConstant
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan.constants import DBRConst
from juloserver.loan.constants import LoanTaxConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.healthcare.factories import HealthcareUserFactory
from juloserver.grab.models import PaymentGatewayVendor, PaymentGatewayBankCode
from juloserver.payment_point.constants import FeatureNameConst as PaymentPointFeatureName
from juloserver.ana_api.services import (
    LoanSelectionAnaAPIPayload,
)
from juloserver.digisign.tests.factories import DigisignRegistrationFactory
from juloserver.digisign.constants import RegistrationStatus
from juloserver.promo.constants import PromoCodeBenefitConst, PromoCodeTypeConst, \
    PromoCodeCriteriaConst, PromoCodeTimeConst, PromoCodeVersion
from juloserver.promo.models import PromoCodeUsage
from juloserver.promo.tests.factories import PromoCodeBenefitFactory, PromoCodeFactory, \
    PromoCodeCriteriaFactory


class TestSubmitLoan(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.user.set_password('123456')
        self.user.save()
        self.pin = CustomerPinFactory(user=self.user)
        self.ecommerce_method = TransactionMethodFactory(
            method=TransactionMethodCode.E_COMMERCE,
            id=8,
        )
        amount = 2000000
        self.account_limit.available_limit = amount + 1000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        self.iprice_transaction = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        self.juloshop_transaction = JuloShopTransactionFactory(
            status=JuloShopTransactionStatus.DRAFT, customer=self.customer
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.ECOMMERCE,
            parent_category_id=1,
        )
        self.bank_account_destination = BankAccountDestinationFactory()

        # iprice -------
        self.iprice_user = AuthUserFactory(
            username=PartnerConstant.IPRICE,
        )
        self.iprice_customer = CustomerFactory(
            user=self.iprice_user,
        )
        self.iprice_name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='0867412734',
            attempt=0,
        )
        self.iprice_bank_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.iprice_customer,
            bank=self.bank,
            name_bank_validation=self.iprice_name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        self.user_partner = AuthUserFactory()
        self.lender = LenderFactory(
            lender_name='jtp', lender_status='active', user=self.user_partner
        )
        self.lender_ballance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=999999999
        )
        self.partner = PartnerFactory(user=self.user_partner, name="JULO")
        self.product_line = self.application.product_line
        self.product_profile = ProductProfileFactory(code='123')
        self.product_line.product_profile = self.product_profile
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category="followthemoney",
            is_active=True,
            parameters={'lender_name': 'jtp'},
        )
        LenderDisburseCounterFactory(lender=self.lender)
        # ------ iprice
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )
        self.fs_zero_interest = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 1,
                    "max_duration": 3,
                    "list_transaction_method_code": ['1', '2'],
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
            description="Test",
        )
        self.daily_fee_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={"daily_max_fee": 0.4},
            is_active=True,
            category="credit_matrix",
            description="Test",
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
        self.delay_disbursement_fee = LoanDelayDisbursementFee()

    def test_submit_loan_iprice_wrong_transac_method(self):
        ecommerce_method = TransactionMethodFactory(
            method=TransactionMethodCode.E_COMMERCE,
            id=10230,  # random
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        # test wrong transaction id
        data['iprice_transaction_id'] = 1238210938

        response = self.client.post('/api/loan/v3/loan', data=data, format='json')
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_iprice(self, mock_is_product_locked, mock_calculate_loan_amount):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan = Loan.objects.filter(customer=self.customer).last()
        self.assertEqual(loan.bank_account_destination, self.iprice_bank_destination)

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_iprice_phone_validation(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
            "mobile_number": "081234",
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 400
        assert response.json()['errors'][0] == ErrorMessageConst.PHONE_INVALID

        response = self.client.post('/api/loan/v2/loan', data=data)
        assert response.status_code == 400
        assert response.json()['errors'][0] == ErrorMessageConst.PHONE_INVALID

        data['mobile_number'] = "081216986633"
        res = self.client.post('/api/loan/v3/loan', data=data, format='json')
        assert res.status_code == 200

        res = self.client.post('/api/loan/v2/loan', data=data, format='json')
        assert res.json()['errors'][0] == ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_no_bank_destination_error(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': True,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "bank_account_destination_id": "-123091",  # nonsense string
            "loan_purpose": 'testing',
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        json_response = response.json()
        self.assertEqual(json_response['errors'][0], "Bank account not found")

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.ATODeviceChangeLoanChecker')
    def test_check_ato_device_change(
        self,
        mock_ato_loan_checker_class,
        mock_is_product_locked,
        mock_calculate_loan_amount,
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_ato_loan_checker = MagicMock()
        mock_ato_loan_checker.is_fraud.return_value = True
        mock_ato_loan_checker_class.return_value = mock_ato_loan_checker
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': True,
            'transaction_type_code': TransactionMethodCode.SELF.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_401_UNAUTHORIZED, response.content)

        loan = Loan.objects.filter(customer=self.customer).last()
        mock_ato_loan_checker_class.assert_called_once_with(
            loan=loan,
            android_id="65e67657568",
        )
        mock_ato_loan_checker.is_fraud.assert_called_once_with()
        mock_ato_loan_checker.block.assert_called_once_with()

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_juloshop(self, mock_is_product_locked, mock_calculate_loan_amount):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "bank_account_destination_id": self.bank_account_destination.id,
            'juloshop_transaction_xid': self.juloshop_transaction.transaction_xid,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan = Loan.objects.filter(customer=self.customer).last()
        self.juloshop_transaction.refresh_from_db()
        self.assertEqual(self.juloshop_transaction.loan, loan)

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_response_message_error(self, mock_is_product_locked, mock_calculate_loan_amount):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        AccountPropertyFactory(account=self.account)
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "bank_account_destination_id": self.bank_account_destination.id,
            'juloshop_transaction_xid': self.juloshop_transaction.transaction_xid,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.json()['errors'][0] == ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_response_message_error_not_show_with_jfinancing_product(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        AccountPropertyFactory(account=self.account)
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)
        self.loan.transaction_method_id = TransactionMethodCode.JFINANCING.code
        self.loan.save()
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "bank_account_destination_id": self.bank_account_destination.id,
            'juloshop_transaction_xid': self.juloshop_transaction.transaction_xid,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.json()['errors'] == []
        assert response.json()['data'] != None

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_purpose_for_balance_consolidation(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, loan_outstanding_amount=285000
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
            name_bank_validation=self.name_bank_validation,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": True,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "bpjs_times": 0,
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(id=loan_id)

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(loan.loan_purpose, LoanPurposeConst.PERPINDAHAN_LIMIT)

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_credit_matrix_repeat(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
        )
        credit_matrix_repeat.save()

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)

        mock_credit_matrix_repeat.return_value = []
        response_without_credit_matrix = self.client.post('/api/loan/v3/loan', data=data)

        self.assertNotEqual(
            response.json()['data']['loan_amount'],
            data['loan_amount_request'],
        )
        self.assertNotEqual(
            response.json()['data']['monthly_interest'],
            response_without_credit_matrix.json()['data']['monthly_interest'],
        )
        self.assertNotEqual(
            response.json()['data']['disbursement_amount'],
            response_without_credit_matrix.json()['data']['disbursement_amount'],
        )

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_negative_duration(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': -3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
        )
        credit_matrix_repeat.save()

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)

        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Pilihan tenor tidak ditemukan' in response.json()['errors'][0])

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_negative_duration(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 100,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
        )
        credit_matrix_repeat.save()

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)

        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Pilihan tenor tidak ditemukan' in response.json()['errors'][0])

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_assign_lender(self, mock_is_product_locked, mock_calculate_loan_amount):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan = Loan.objects.filter(customer=self.customer).last()
        assert loan.lender == self.lender

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.transaction_web_location_blocked_check')
    def test_submit_loan_with_location_blocked(
        self,
        mock_transaction_web_location_blocked_check,
        mock_is_product_locked,
        mock_calculate_loan_amount,
    ):
        TransactionRiskyDecisionFactory()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
            'is_web_location_blocked': True,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan = Loan.objects.filter(customer=self.customer).last()
        mock_transaction_web_location_blocked_check.assert_called_once_with(
            loan=loan,
            latitude=None,
            longitude=None,
        )

    def test_submit_loan_with_wrong_latitude_or_longitude(self):
        data = {
            'loan_amount_request': 3000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': '65e67657568',
            'gcm_reg_id': '574534867',
            'iprice_transaction_id': self.iprice_transaction.id,
        }

        # Case 1: is_web_location_blocked=False, and missing latitude & longitude
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Wrong latitude or longitude' in response.json()['errors'][0])

        # Case 2: is_web_location_blocked=False, and missing latitude
        data['longitude'] = 108.2772
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Wrong latitude or longitude' in response.json()['errors'][0])

        # Case 3: is_web_location_blocked=False, and missing longitude
        del data['longitude']
        data['latitude'] = 14.0583
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Wrong latitude or longitude' in response.json()['errors'][0])

        # Case 4: is_web_location_blocked=True, and latitude is not none
        data['is_web_location_blocked'] = True
        data['latitude'] = 14.0583
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Wrong latitude or longitude' in response.json()['errors'][0])

        # Case 5: is_web_location_blocked=True, and longitude is not none
        data['is_web_location_blocked'] = True
        del data['latitude']
        data['latitude'] = 108.2772
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Wrong latitude or longitude' in response.json()['errors'][0])

    def test_invalid_validate_sepulsa_payment_point_inquire(self):
        amount = 541565
        transaction_type_id = TransactionMethodCode.PASCA_BAYAR.code

        data = {
            'loan_amount_request': amount,
            'self_bank_account': False,
            'is_payment_point': True,
            'transaction_type_code': transaction_type_id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
        }

        # no sepulsa payment point inquire tracking
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Loan amount request is invalid' in response.json()['errors'][0])

        # wrong sepulsa_payment_point_inquire_tracking_id
        data['sepulsa_payment_point_inquire_tracking_id'] = 0
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertTrue('Loan amount request is invalid' in response.json()['errors'][0])

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_different_bank_account_destination(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': True,
            'transaction_type_code': TransactionMethodCode.SELF.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST, response.content)
        self.assertTrue('Bank account does not belong to you' in response.json()['errors'][0])

        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': TransactionMethodCode.OTHER.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST, response.content)
        self.assertTrue('Bank account does not belong to you' in response.json()['errors'][0])

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_different_bank_account_destination_others(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.INSTALLMENT,
            display_label='Cicilan',
            parent_category_id=2,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': TransactionMethodCode.OTHER.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK, response.content)

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_with_zero_interest(
        self,
        mock_is_product_locked,
        mock_get_credit_matrix_repeat,
        mock_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_validate_loan_concurrency,
        mock_time_zone_loan_related,
        mock_get_credit_matrix_api,
    ):
        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        amount = 1_000_000
        self.fs_zero_interest.is_active = True
        self.fs_zero_interest.save()
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_time_zone_loan_related.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_validate_loan_concurrency.return_value = True, False

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=0.05,
            provision=0.07,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        mock_get_credit_matrix_api.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        # 1. self method: move total interest in loan_disbursement_amount
        # :: payments: total_principal  == loan.loan_amount, total interest == 0
        # :: payments: total_due_amount == loan.loan_amount, total interest == 0
        data = {
            'loan_amount_request': amount,  # doesn't matter
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Zero interest',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_zero_interest": True,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)

        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        payments = Payment.objects.filter(loan_id=loan.pk).aggregate(
            total_principal=Sum('installment_principal'),
            total_interest=Sum('installment_interest'),
        )
        loan.status_id = LoanStatusCodes.CURRENT
        loan.save()
        loan_zt = LoanZeroInterest.objects.filter(loan_id=loan.pk).last()

        # API
        data = response.json()['data']
        assert data['monthly_interest'] == 0
        assert data['disbursement_amount'] == loan.loan_disbursement_amount
        assert data['installment_amount'] == loan.installment_amount

        # data
        assert payments['total_principal'] == loan.loan_amount
        assert payments['total_interest'] == 0
        assert loan_zt.original_loan_amount == loan.loan_amount

        # disbursement amount = loan_amount - (provision fee + interest fee)
        assert loan.loan_disbursement_amount == loan.loan_amount - (
            loan.loan_amount * loan_zt.adjusted_provision_rate
        )
        assert loan_zt.original_monthly_interest_rate == credit_matrix_repeat.interest
        assert loan.interest_percent_monthly() == 0
        assert loan.interest_rate_monthly == 0
        assert loan.loan_disbursement_amount == loan.loan_amount - (
            py2round(loan_zt.adjusted_provision_rate * amount)
        )
        assert loan.disbursement_fee == py2round(
            (loan.loan_amount * loan.loanzerointerest.adjusted_provision_rate)
            - loan.provision_fee()
        )

        # 2. other method: plus total interest to loan amount => increase principal
        # :: payments: total_principal  == loan.loan_amount
        # :: payments: total_due_amount == loan.loan_amount
        amount = 1_000_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": other_method.pk,
            "is_zero_interest": True,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        data_response = response.json()['data']

        duration = 3
        loan_amount_duration = None
        disbursement_amount_duration = None
        provision_duration = None
        disbursement_fee_duration = None
        for loan_choice in data_response['loan_choice']:
            if loan_choice['duration'] == duration:
                loan_amount_duration = loan_choice['loan_amount']
                disbursement_amount_duration = loan_choice['disbursement_amount']
                provision_duration = loan_choice['provision_amount']
                disbursement_fee_duration = loan_choice['disbursement_fee']

        data = {
            'loan_amount_request': disbursement_amount_duration,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': other_method.id,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'Zero interest',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_zero_interest": True,
        }
        self.bank_account_category.category = BankAccountCategoryConst.OTHER
        self.bank_account_category.save()
        response = self.client.post('/api/loan/v3/loan', data=data)

        loan = Loan.objects.filter(account_id=self.account.pk).last()
        payments = Payment.objects.filter(loan_id=loan.pk).aggregate(
            total_principal=Sum('installment_principal'),
            total_due_amount=Sum('due_amount'),
            total_interest=Sum('installment_interest'),
        )
        loan_zt = LoanZeroInterest.objects.filter(loan_id=loan.pk).last()

        # API
        data = response.json()['data']
        assert data['monthly_interest'] == 0
        assert data['disbursement_amount'] == loan.loan_disbursement_amount
        assert data['installment_amount'] == loan.installment_amount

        # data
        assert payments['total_principal'] == loan.loan_amount
        assert payments['total_interest'] == 0
        assert loan_zt.original_monthly_interest_rate == credit_matrix_repeat.interest
        assert loan.interest_percent_monthly() == 0
        assert loan.interest_rate_monthly == 0
        assert loan.loan_disbursement_amount == loan.loan_amount - (
            py2round(loan_zt.adjusted_provision_rate * loan.loan_amount)
        )
        assert loan.disbursement_fee == py2round(
            (loan.loan_amount * loan.loanzerointerest.adjusted_provision_rate)
            - loan.provision_fee()
        )
        assert loan.loan_amount == loan_amount_duration
        assert loan.loan_disbursement_amount == disbursement_amount_duration
        assert loan.disbursement_fee == disbursement_fee_duration

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_with_zero_interest_with_exceed(
        self,
        mock_is_product_locked,
        mock_get_credit_matrix_repeat,
        mock_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_validate_loan_concurrency,
        mock_time_zone_loan_related,
    ):
        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        amount = 1_000_000
        self.fs_zero_interest.is_active = True
        self.fs_zero_interest.save()
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_time_zone_loan_related.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_validate_loan_concurrency.return_value = True, False

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=0.5,
            provision=0.07,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        # 1. self method: move total interest in loan_disbursement_amount
        # :: payments: total_principal  == loan.loan_amount, total interest == 0
        # :: payments: total_due_amount == loan.loan_amount, total interest == 0
        data = {
            'loan_amount_request': amount,  # doesn't matter
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Zero interest',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_zero_interest": True,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)

        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate
        payments = Payment.objects.filter(loan_id=loan.pk).aggregate(
            total_principal=Sum('installment_principal'),
            total_interest=Sum('installment_interest'),
        )
        loan.status_id = LoanStatusCodes.CURRENT
        loan.save()
        loan_zt = LoanZeroInterest.objects.filter(loan_id=loan.pk).last()

        # API
        data = response.json()['data']
        assert data['monthly_interest'] == 0
        assert data['disbursement_amount'] == loan.loan_disbursement_amount
        assert data['installment_amount'] == loan.installment_amount

        # data
        assert payments['total_principal'] == loan.loan_amount
        assert payments['total_interest'] == 0
        assert loan_zt.original_loan_amount == loan.loan_amount

        # disbursement amount = loan_amount - (provision fee + interest fee)
        assert loan_adjusted_rate.adjusted_provision_rate == loan_zt.adjusted_provision_rate
        assert loan.loan_disbursement_amount == loan.loan_amount - (
            loan.loan_amount * loan_zt.adjusted_provision_rate
        )
        assert loan_zt.original_monthly_interest_rate == credit_matrix_repeat.interest
        assert loan.interest_percent_monthly() == 0
        assert loan.interest_rate_monthly == 0
        assert loan.loan_disbursement_amount == loan.loan_amount - (
            py2round(loan_zt.adjusted_provision_rate * amount)
        )
        assert loan.disbursement_fee == round_rupiah(
            loan.loan_amount * (loan.loanzerointerest.adjusted_provision_rate - loan.provision_rate)
        )
        for payment in Payment.objects.filter(loan_id=loan.pk):
            assert payment.due_amount == payment.installment_principal
            assert payment.installment_interest == 0

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_dbr(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
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
        monthly_income = 10_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=1_000_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()

        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)

        mock_credit_matrix_repeat.return_value = []
        response_without_credit_matrix = self.client.post('/api/loan/v3/loan', data=data)

        self.assertNotEqual(
            response.json()['data']['loan_amount'],
            data['loan_amount_request'],
        )
        self.assertNotEqual(
            response.json()['data']['monthly_interest'],
            response_without_credit_matrix.json()['data']['monthly_interest'],
        )
        self.assertNotEqual(
            response.json()['data']['disbursement_amount'],
            response_without_credit_matrix.json()['data']['disbursement_amount'],
        )

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_dbr_exception(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
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
        monthly_income = 2_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=1_000_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()

        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        date_loan = date.today()
        LoanDbrLogFactory(
            log_date=date_loan,
            application=self.application,
            source=DBRConst.LOAN_CREATION,
            transaction_method_id=self.ecommerce_method.id,
        )
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        res = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST, res.content)

        # Check if there's log
        # Also make Sure log inserted even there's already a log before
        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=self.application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_CREATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 2)

    @patch(
        'juloserver.loan.views.views_api_v3.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.is_apply_check_other_active_platforms_using_fdc')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_other_active_platforms')
    def test_check_other_active_platforms(
        self,
        mock_is_eligible_other_active_platforms,
        mock_is_apply_check_other_active_platforms_using_fdc,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule,
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=BankAccountCategoryFactory(
                category=BankAccountCategoryConst.INSTALLMENT,
                display_label='Cicilan',
                parent_category_id=2,
            ),
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        data = {
            'loan_amount_request': 3000,  # doesn't matter
            'self_bank_account': False,
            'transaction_type_code': TransactionMethodCode.OTHER.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': bank_account_destination.id,
        }
        fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "number_of_allowed_platforms": 3,
                "fdc_data_outdated_threshold_days": 7,
                "whitelist": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "bypass": {
                    "is_active": False,
                    "list_application_id": [],
                    "list_customer_segment_cmr": [],
                },
                "ineligible_message_for_old_application": "ineligible_message_for_old_application",
                "popup": {},
                "ineligible_alert_after_fdc_checking": {},
            },
        )

        # Case 1: is_apply_check_other_active_platforms_using_fdc=True, but ineligible
        mock_is_apply_check_other_active_platforms_using_fdc.return_value = True
        mock_is_eligible_other_active_platforms.return_value = False
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            fs.parameters['ineligible_message_for_old_application'], response.json()['errors'][0]
        )
        mock_send_user_attributes_to_moengage_for_active_platforms_rule.assert_called_once_with(
            customer_id=self.customer.id, is_eligible=False
        )

        # Case 2: is_apply_check_other_active_platforms_using_fdc=True, but eligible
        mock_is_apply_check_other_active_platforms_using_fdc.return_value = True
        mock_is_eligible_other_active_platforms.return_value = True
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        # Case 3: is_apply_check_other_active_platforms_using_fdc=False
        Loan.objects.filter(customer=self.customer).delete()  # prevent to raise only 1 active loan
        mock_is_apply_check_other_active_platforms_using_fdc.return_value = False
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_tax_active(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']
        loan_id = response_data['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        self.assertNotEqual(response_data['loan_amount'], data['loan_amount_request'])
        self.assertNotEqual(response_data['tax'], 0)

        payments = loan.payment_set.all().aggregate(total_principal=Sum('installment_principal'))
        assert payments['total_principal'] == loan.loan_amount

        installment_amount = response_data['installment_amount']
        response_agreement = self.client.get('/api/loan/v2/agreement/loan/{}'.format(loan.loan_xid))
        response_installment_amount = response_agreement.json()['data']['loan'][
            'installment_amount'
        ]
        assert response_installment_amount == installment_amount

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_tax_inactive(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=False,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        self.assertNotEqual(
            response.json()['data']['loan_amount'],
            data['loan_amount_request'],
        )
        self.assertEqual(
            response.json()['data']['tax'],
            0,
        )
        payments = loan.payment_set.all().aggregate(total_principal=Sum('installment_principal'))
        assert payments['total_principal'] == loan.loan_amount

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_tax_with_julo_care(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
        mock_julo_care_eligible,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_calculate_loan_amount.return_value = (
            2000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 2000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
            'is_tax': True,
            'is_julo_care': True,
        }
        mock_julo_care_eligible.return_value = (True, {'3': 20000})
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        provision_fee = loan.provision_fee()
        tax = response.json()['data']['tax']
        disbursement_amount = response.json()['data']['disbursement_amount']
        self.assertEqual(
            tax,
            loan.get_loan_tax_fee(),
        )
        self.assertEqual(disbursement_amount, self.iprice_transaction.iprice_total_amount)
        total_amount = provision_fee + disbursement_amount + tax
        loan_amount = response.json()['data']['loan_amount']
        self.assertEqual(loan_amount, total_amount)
        payments = loan.payment_set.all().aggregate(total_principal=Sum('installment_principal'))
        assert payments['total_principal'] == loan.loan_amount

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_tax_self_with_julo_care(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
        mock_julo_care_eligible,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': True,
            'transaction_type_code': TransactionMethodCode.SELF.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'is_tax': True,
            'is_julo_care': True,
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        mock_julo_care_eligible.return_value = (True, {'3': 20000})
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        provision_fee = loan.provision_fee()
        tax = response.json()['data']['tax']
        disbursement_amount = response.json()['data']['disbursement_amount']
        self.assertEqual(
            tax,
            loan.get_loan_tax_fee(),
        )
        loan_amount = response.json()['data']['loan_amount']
        self.assertEqual(loan_amount, 5_000_000)
        total_amount = disbursement_amount + provision_fee + tax
        self.assertEqual(loan_amount, total_amount)
        payments = loan.payment_set.all().aggregate(total_principal=Sum('installment_principal'))
        assert payments['total_principal'] == loan.loan_amount
        assert tax > 0

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_tax_other_method(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
        mock_julo_care_eligible,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.OTHER
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        self.daily_fee_fs.parameters = {"daily_max_fee": 0.01}
        self.daily_fee_fs.save()
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': TransactionMethodCode.OTHER.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'is_tax': True,
            'is_julo_care': True,
            'loan_purpose': 'testing',
            'bank_account_destination_id': self.bank_account_destination.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = None
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        provision_fee = loan.provision_fee()

        tax = response.json()['data']['tax']
        disbursement_amount = response.json()['data']['disbursement_amount']
        self.assertEqual(
            tax,
            loan.get_loan_tax_fee(),
        )
        loan_amount = response.json()['data']['loan_amount']
        total_amount = disbursement_amount + provision_fee + tax
        self.assertEqual(loan_amount, total_amount)

        payments = loan.payment_set.all().aggregate(total_principal=Sum('installment_principal'))
        assert payments['total_principal'] == loan.loan_amount
        assert (
            loan.loanadjustedrate.adjusted_provision_rate
            < self.credit_matrix.product.origination_fee_pct
        )

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.services.loan_related.process_check_gtl_inside')
    @patch('juloserver.loan.services.loan_related.process_check_gtl_outside')
    def test_check_gtl(
        self,
        mock_process_check_gtl_outside,
        mock_process_check_gtl_inside,
        mock_is_product_locked,
        mock_calculate_loan_amount,
    ):
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            3300,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=BankAccountCategoryFactory(
                category=BankAccountCategoryConst.INSTALLMENT,
                display_label='Cicilan',
                parent_category_id=2,
            ),
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        loan_amount_request = 3000  # doesn't matter
        transaction_type_code = TransactionMethodCode.SELF.code
        data = {
            'loan_amount_request': loan_amount_request,
            'self_bank_account': False,
            'transaction_type_code': transaction_type_code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'bank_account_destination_id': bank_account_destination.id,
        }

        # Case 1: not pass GTL inside
        mock_process_check_gtl_inside.return_value = Response(status=HTTP_400_BAD_REQUEST, data={})
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        mock_process_check_gtl_inside.assert_called_with(
            transaction_method_id=transaction_type_code,
            loan_amount=loan_amount_request,
            application=self.application,
            customer_id=self.customer.id,
            account_limit=self.account_limit,
        )
        mock_process_check_gtl_outside.assert_not_called()

        # test loan_amount_request get from sepulsa product in case prepaid product
        # because currently FE sent wrong amount, don't follow other transaction method
        sepulsa_product = SepulsaProductFactory(
            is_active=True,
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            customer_price_regular=22000,
        )
        response = self.client.post(
            '/api/loan/v3/loan',
            data={
                'loan_amount_request': sepulsa_product.customer_price_regular,
                'self_bank_account': False,
                'transaction_type_code': TransactionMethodCode.LISTRIK_PLN.code,
                'pin': '123456',
                'loan_duration': 3,
                'account_id': self.account.id,
                'android_id': "65e67657568",
                'latitude': -6.175499,
                'longitude': 106.820512,
                'gcm_reg_id': "574534867",
                'loan_purpose': 'testing',
                'is_payment_point': True,
                'payment_point_product_id': sepulsa_product.id,
            },
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        mock_process_check_gtl_inside.assert_called_with(
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            loan_amount=sepulsa_product.customer_price_regular,
            application=self.application,
            customer_id=self.customer.id,
            account_limit=self.account_limit,
        )

        # Case 2: pass GTL inside, not pass GTL outside
        mock_process_check_gtl_inside.return_value = None
        mock_process_check_gtl_outside.return_value = Response(status=HTTP_400_BAD_REQUEST, data={})
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        mock_process_check_gtl_inside.assert_called()
        mock_process_check_gtl_outside.assert_called_with(
            transaction_method_id=transaction_type_code,
            loan_amount=loan_amount_request,
            application=self.application,
            customer_id=self.customer.id,
            account_limit=self.account_limit,
        )

        # Case 3: pass GTL inside, pass GTL outside
        mock_process_check_gtl_outside.return_value = None
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        mock_process_check_gtl_inside.return_value = False
        mock_process_check_gtl_outside.return_value = False

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_purpose_for_healthcare_product(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        healthcare_method = TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        mock_is_product_locked.return_value = False
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": healthcare_user.pk,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(id=loan_id)

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(loan.loan_purpose, LoanPurposeConst.BIAYA_KESEHATAN)
        healthcare_user.refresh_from_db()
        assert healthcare_user.loans.all().count() > 0

    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    def test_submit_loan_purpose_for_healthcare_product_ios(
            self, mock_calculate_loan_amount
    ):
        TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": healthcare_user.pk,
        }

        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(app_version='1.1.1', status=self.status_code)
        MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "healthcare": {
                    "ios_app_version": "6.4.0",
                    "locked": True
                }, },
        )
        ios_header = {
            "HTTP_X_DEVICE_ID": "E78E234E-4981-4BB7-833B-2B6CEC2F56DF",
            "HTTP_X_PLATFORM": "iOS",
            "HTTP_X_PLATFORM_VERSION": '18.1',
            "HTTP_X_APP_VERSION": '6.3.0',
        }
        response = self.client.post('/api/loan/v3/loan', data=data, **ios_header)
        # product is locked
        self.assertEqual(
            response.json()['errors'],
            ['Maaf, Anda tidak bisa menggunakan fitur ini.Silakan gunakan fitur lain yang '
             'tersedia di menu utama.']
        )

        # upgrade account app version then can create loan
        ios_header['HTTP_X_APP_VERSION'] = '6.5.0'
        response = self.client.post('/api/loan/v3/loan', data=data, **ios_header)
        self.assertEqual(response.status_code, HTTP_200_OK)
        loan_id = response.json()['data']['loan_id']
        loan = Loan.objects.get(id=loan_id)
        self.assertEqual(loan.loan_purpose, LoanPurposeConst.BIAYA_KESEHATAN)


    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_purpose_for_healthcare_product_not_found(
        self, mock_is_product_locked, mock_calculate_loan_amount
    ):
        healthcare_method = TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        mock_is_product_locked.return_value = False
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": -1,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        # the Healthcare user is deleted
        data['healthcare_user_id'] = healthcare_user.pk
        healthcare_user.is_deleted = True
        healthcare_user.save()
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_with_prorate_installment_with_exceed(
        self,
        mock_is_product_locked,
        mock_get_credit_matrix_repeat,
        mock_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_validate_loan_concurrency,
        mock_time_zone_loan_related,
        mock_get_daily_max_fee,
    ):
        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_zero_interest.is_active = False
        self.fs_zero_interest.save()
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = today_date.date() + relativedelta(days=20)

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_time_zone_loan_related.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_validate_loan_concurrency.return_value = True, False

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )

        provision_rate = interest_rate = 0.09
        product_lookup = ProductLookupFactory(
            origination_fee_pct=provision_rate,
            interest_rate=interest_rate,
        )
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        mock_get_loan_duration.return_value = [2, 3, 4, 5, 6]
        mock_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        mock_get_daily_max_fee.return_value = 0.004
        amount = 4_000_000
        duration = 2
        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'test',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
        }

        expected_first_month_rate = 0.044
        expected_rest_month_rate = 0.066
        expected_max_fee = 0.2
        expected_total_fee = 0.24

        # make sure the numbers are correct
        assert (
            expected_first_month_rate + expected_rest_month_rate + provision_rate
        ) == expected_max_fee

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200

        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate

        assert loan is not None
        assert loan.provision_fee() == py2round(
            loan.loan_amount * loan_adjusted_rate.adjusted_provision_rate
        )
        assert loan_adjusted_rate is not None
        assert loan_adjusted_rate.adjusted_first_month_interest_rate == expected_first_month_rate
        assert loan_adjusted_rate.adjusted_monthly_interest_rate == expected_rest_month_rate
        assert loan_adjusted_rate.max_fee == expected_max_fee
        assert loan_adjusted_rate.simple_fee == expected_total_fee

        # payments
        payments = Payment.objects.filter(loan_id=loan.pk)

        assert len(payments) == duration
        for payment in payments:
            assert payment.installment_principal == 2_000_000
            if payment.payment_number == 1:
                assert payment.installment_interest == 176_000
                assert payment.due_date == first_payment_date
            else:
                assert payment.installment_interest == 264_000

            assert (
                payment.due_amount == payment.installment_principal + payment.installment_interest
            )

        # case interest reduction, duration is one
        duration = 1
        amount = 100_000
        interest_rate = 0.09
        provision_rate = 0.07
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'test',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200
        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate

        expected_first_month_rate = 0.01
        expected_max_fee = 0.08
        expected_total_fee = 0.13
        first_month_delta_days = (first_payment_date - today_date.date()).days
        expected_adjusted_monthly_rate = expected_first_month_rate / first_month_delta_days * 30

        assert loan is not None
        assert loan_adjusted_rate is not None
        assert loan.provision_fee() == py2round(
            loan.loan_amount * loan_adjusted_rate.adjusted_provision_rate
        )
        assert loan_adjusted_rate.adjusted_first_month_interest_rate == expected_first_month_rate
        assert loan_adjusted_rate.adjusted_monthly_interest_rate == expected_adjusted_monthly_rate
        assert loan_adjusted_rate.max_fee == expected_max_fee
        assert loan_adjusted_rate.simple_fee == expected_total_fee

        # payments
        payments = Payment.objects.filter(loan_id=loan.pk)

        assert len(payments) == duration
        assert payments[0].installment_principal == 100_000
        assert payments[0].installment_interest == 1_000
        assert payments[0].due_date == first_payment_date
        assert (
            payments[0].due_amount
            == payments[0].installment_principal + payments[0].installment_interest
        )

    @patch('juloserver.loan.services.loan_related.get_loan_amount_by_transaction_type')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_loan_with_prorate_installment_with_exceed_case_negative_with_insurance(
        self,
        mock_is_product_locked,
        mock_get_credit_matrix_repeat,
        mock_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_validate_loan_concurrency,
        mock_time_zone_loan_related,
        mock_get_daily_max_fee,
        mock_get_eligibility_status,
        mock_loan_amount_by_transaction_type,
    ):
        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_zero_interest.is_active = False
        self.fs_zero_interest.save()
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = today_date.date() + relativedelta(days=20)

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_time_zone_loan_related.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_validate_loan_concurrency.return_value = True, False

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        dompet_method = TransactionMethodFactory(
            id=TransactionMethodCode.DOMPET_DIGITAL.code,
            method=TransactionMethodCode.DOMPET_DIGITAL,
        )
        # case 1, total interest is negative, so provision is deducted
        original_interest_rate = 0.09
        original_provision_rate = 0.09
        product_lookup = ProductLookupFactory(
            origination_fee_pct=original_provision_rate,
            interest_rate=original_interest_rate,
        )
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=original_interest_rate,
            provision=original_provision_rate,
            max_tenure=6,
        )
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        mock_get_loan_duration.return_value = [2, 3, 4, 5, 6]
        mock_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        duration = 1
        origin_insurance = 10_000
        mock_get_eligibility_status.return_value = (True, {str(duration): origin_insurance})

        daily_max_fee = 0.004
        mock_get_daily_max_fee.return_value = daily_max_fee
        amount = 1_000_000
        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'test',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            'is_julo_care': True,
        }

        total_days = 20
        expected_adjusted_first_month_rate = 0
        expected_max_fee = daily_max_fee * total_days  # 20 days = 0.08
        expected_insurance_rate = 0
        expected_provision_rate = 0.08
        total_interest = original_interest_rate / 30 * total_days
        expected_total_fee = original_provision_rate + total_interest + expected_insurance_rate

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200

        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate

        assert loan is not None
        assert loan.loan_amount == amount
        assert loan_adjusted_rate is not None
        assert (
            loan_adjusted_rate.adjusted_first_month_interest_rate
            == expected_adjusted_first_month_rate
        )
        assert (
            loan_adjusted_rate.adjusted_monthly_interest_rate == expected_adjusted_first_month_rate
        )
        assert loan_adjusted_rate.max_fee == expected_max_fee
        assert loan_adjusted_rate.adjusted_provision_rate == expected_provision_rate
        assert loan_adjusted_rate.simple_fee == expected_total_fee

        julocare = LoanJuloCare.objects.filter(loan_id=loan.id).last()
        assert julocare is None

        # payments
        payments = Payment.objects.filter(loan_id=loan.pk)

        assert len(payments) == duration
        assert payments[0].installment_interest == 0
        assert payments[0].due_date == first_payment_date

        assert (
            payments[0].due_amount
            == payments[0].installment_principal + payments[0].installment_interest
        )

        # case not self bank account, julo care is False
        total_days = 20
        expected_adjusted_first_month_rate = 0
        expected_max_fee = daily_max_fee * total_days  # 20 days = 0.08
        expected_insurance_rate = 0
        expected_provision_rate = 0.08
        total_interest = original_interest_rate / 30 * total_days
        expected_total_fee = original_provision_rate + total_interest + expected_insurance_rate

        new_amount = 800_000  # any
        mock_loan_amount_by_transaction_type.return_value = new_amount  # any
        data = {
            'loan_amount_request': amount,
            'self_bank_account': False,
            'transaction_type_code': dompet_method.pk,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'test',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            'is_julo_care': False,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200

        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate

        assert loan is not None
        assert loan.loan_amount == new_amount
        assert loan_adjusted_rate is not None
        assert (
            loan_adjusted_rate.adjusted_first_month_interest_rate
            == expected_adjusted_first_month_rate
        )
        assert (
            loan_adjusted_rate.adjusted_monthly_interest_rate == expected_adjusted_first_month_rate
        )
        assert loan_adjusted_rate.max_fee == expected_max_fee
        assert loan_adjusted_rate.adjusted_provision_rate == expected_provision_rate
        assert loan_adjusted_rate.simple_fee == expected_total_fee

    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_tax_active_calculate_interest_from_tax(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
        mock_time_zone,
        mock_first_payment_date,
    ):
        cycle_day = 7
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, cycle_day, 0, 0, 0).date()
        mock_time_zone.return_value = today_date
        mock_first_payment_date.return_value = first_payment_date
        self.account.cycle_day = cycle_day
        self.account.save()
        tax_percent = 0.11
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        self.iprice_transaction.iprice_total_amount = 5000000
        self.iprice_transaction.save()
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.pk,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']
        loan_id = response_data['loan_id']
        loan = Loan.objects.get(pk=loan_id)
        payments = Payment.objects.filter(loan_id=loan.pk)
        for payment in payments:
            assert (
                payment.due_amount == payment.installment_principal + payment.installment_interest
            )
        additional_fee = LoanAdditionalFee.objects.filter(loan_id=loan.pk).last()
        last_payment = payments.order_by('payment_number').last()
        interest_fee = round_rupiah(
            loan.loan_amount * loan.loanadjustedrate.adjusted_monthly_interest_rate
        )
        # due to round down in installment calculation, the diff will be diff 1000
        assert interest_fee - 1000 == round_rupiah(last_payment.installment_interest)
        assert additional_fee != None

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_submit_loan_with_new_tenor_pricing(
        self,
        mock_credit_matrix_repeat,
        mock_is_product_locked,
        mock_calculate_loan_amount,
        mock_validate_loan_concurrency,
    ):
        self.account_limit.available_limit = 15000000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        mock_is_product_locked.return_value = False
        mock_calculate_loan_amount.return_value = (
            5000000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            'loan_amount_request': 5000000,
            'self_bank_account': False,
            'transaction_type_code': self.ecommerce_method.id,
            'pin': '123456',
            'loan_duration': 6,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'iprice_transaction_id': self.iprice_transaction.id,
        }
        mock_validate_loan_concurrency.return_value = "", None
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.08,
            provision=0.1,
            max_tenure=8,
        )
        credit_matrix_repeat.save()

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        response = self.client.post('/api/loan/v3/loan', data=data)

        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        parameters = {
            'thresholds': {
                'data': {
                    6: 0.01,
                    9: 0.02,
                    12: 0.05,
                },
                'is_active': True,
            },
            'minimum_pricing': {
                'data': 0.04,
                'is_active': True,
            },
            'cmr_segment': {
                'data': ['activeus_a'],
                'is_active': True,
            },
            'transaction_methods': {
                'data': [1, 2, 8],
                'is_active': True,
            }
        }
        self.new_tenor_feature_setting = FeatureSettingFactory(
            is_active=False,
            feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
            parameters=parameters
        )
        self.new_tenor_feature_setting.is_active = True
        self.new_tenor_feature_setting.save()
        response_with_credit_matrix_and_new_tenor_fs_on = self.client.post('/api/loan/v3/loan', data=data)
        # checking if tenor_based_price table row created
        loan_id = response_with_credit_matrix_and_new_tenor_fs_on.json()['data']['loan_id']
        tenor_based_price = TenorBasedPricing.objects.filter(loan_id=loan_id).first()
        self.assertEqual(
            response_with_credit_matrix_and_new_tenor_fs_on.json()['data']['monthly_interest'],
            tenor_based_price.new_pricing
        )

        self.assertNotEqual(
            response.json()['data']['loan_amount'],
            data['loan_amount_request'],
        )
        self.assertNotEqual(
            response.json()['data']['monthly_interest'],
            response_with_credit_matrix_and_new_tenor_fs_on.json()['data']['monthly_interest'],
        )

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_submit_loan_with_delay_disbursement_success(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
        mock_julo_care_eligible,
    ):

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        insurance_rate = 0
        dd_premium = 3_000
        dd_rate = dd_premium / amount
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        original_insurance = 6500

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium
        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_calculate_loan_amount.return_value = (
            amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': 1,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Delay Disbursement',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_julo_care": True,
            "is_zero_interest": False,
        }

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']

        provision_amount = (
            (provision_rate * amount) + (insurance_rate * amount) + (dd_rate * amount)
        )
        expected_tax = tax_percent * provision_amount
        expected_disbursement_amount = amount - provision_amount - expected_tax
        expected_loan_status = 210

        # assert
        expected_monthly_interest_rate = monthly_interest_rate
        expected_installment_amount = round_rupiah(
            amount / 3 + amount * expected_monthly_interest_rate
        )
        self.assertEqual(expected_installment_amount, response_data['installment_amount'])
        self.assertEqual(expected_monthly_interest_rate, response_data['monthly_interest'])

        self.assertEqual(amount, response_data['loan_amount'])
        self.assertEqual(expected_disbursement_amount, response_data['disbursement_amount'])
        self.assertEqual(expected_tax, response_data['tax'])
        self.assertEqual(expected_loan_status, response_data['loan_status'])
        self.assertEqual(3, response_data['loan_duration'])

        self.assertEqual(response.status_code, HTTP_200_OK)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_submit_loan_with_delay_disbursement_exceeded(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
        mock_julo_care_eligible,
        mock_daily_max_fee,
    ):

        amount = 100_000
        monthly_interest_rate = 0.06
        daily_max_fee_rate = 0.0002
        provision_rate = 0.08
        insurance_rate = 0
        dd_premium = 3_000
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        original_insurance = 6500
        expected_provision_rate = 0
        expected_dd_rate = 0

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_calculate_loan_amount.return_value = (
            amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_daily_max_fee.return_value = daily_max_fee_rate

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': 1,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Delay Disbursement',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_julo_care": True,
            "is_zero_interest": False,
        }

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']

        (
            _,
            _,
            max_fee_rate,
            provision_fee_rate,
            monthly_interest_rate,
            _,
            dd_fee_rate,
        ) = validate_max_fee_rule(
            first_payment_date,
            0,
            3,
            provision_rate,
            0,
            (dd_premium / amount),
        )

        provision_amount = (
            (expected_provision_rate * amount)
            + (insurance_rate * amount)
            + (expected_dd_rate * amount)
        )
        expected_tax = tax_percent * provision_amount
        expected_disbursement_amount = amount - provision_amount - expected_tax
        expected_loan_status = 210

        # assert
        expected_monthly_interest_rate = 0
        expected_installment_amount = 33333
        self.assertEqual(expected_installment_amount, response_data['installment_amount'])
        self.assertEqual(expected_monthly_interest_rate, response_data['monthly_interest'])

        self.assertEqual(expected_provision_rate, provision_fee_rate)
        self.assertEqual(expected_dd_rate, dd_fee_rate)

        self.assertEqual(amount, response_data['loan_amount'])
        self.assertEqual(expected_disbursement_amount, response_data['disbursement_amount'])
        self.assertEqual(expected_tax, response_data['tax'])
        self.assertEqual(expected_loan_status, response_data['loan_status'])
        self.assertEqual(3, response_data['loan_duration'])

        self.assertEqual(response.status_code, HTTP_200_OK)

        # assert db
        loan = Loan.objects.filter(customer_id=self.customer.pk).last()
        loan_adjusted_rate = loan.loanadjustedrate

        assert loan is not None
        assert loan_adjusted_rate is not None
        assert (
            loan_adjusted_rate.adjusted_first_month_interest_rate == expected_monthly_interest_rate
        )
        assert loan_adjusted_rate.adjusted_monthly_interest_rate == expected_monthly_interest_rate
        assert loan_adjusted_rate.max_fee == max_fee_rate
        assert loan_adjusted_rate.adjusted_provision_rate == expected_provision_rate

    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_submit_loan_non_tarik_dana_with_delay_disbursement_success(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
    ):

        loan_amount_request = 1_000_000  # product sku price
        sepulsa_product = SepulsaProductFactory(
            is_active=True,
            type=SepulsaProductType.EWALLET,
            category=SepulsaProductCategory.DANA,
            customer_price_regular=loan_amount_request,
        )

        monthly_interest_rate = 0.06
        provision_rate = 0.08
        dd_premium = 3_000
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium
        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_calculate_loan_amount.return_value = (
            get_loan_amount_by_transaction_type(
                loan_amount=loan_amount_request,
                origination_fee_percentage=provision_rate,
                is_withdraw_funds=False,
            ),
            self.credit_matrix,
            self.credit_matrix_product_line,
        )

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        ewallet_method = TransactionMethodFactory(
            id=TransactionMethodCode.DOMPET_DIGITAL.code,
            method=TransactionMethodCode.DOMPET_DIGITAL,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=ewallet_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)

        # request
        data = {
            'loan_amount_request': sepulsa_product.customer_price_regular,
            'self_bank_account': False,
            'transaction_type_code': ewallet_method.id,
            'pin': '123456',
            'loan_duration': 6,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'mobile_number': "081232141231",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'is_payment_point': True,
            'payment_point_product_id': sepulsa_product.pk,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']

        # assert
        expected_loan_status = 210

        expected_loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
            disbursement_amount=loan_amount_request,
            provision_rate=provision_rate,
            dd_premium=dd_premium,
        )

        provision_amount = int(py2round((provision_rate * expected_loan_amount) + dd_premium))

        expected_tax = int(py2round(tax_percent * provision_amount))

        loan_amount_after_tax = expected_loan_amount + expected_tax
        expected_installment_amount = round_rupiah(
            loan_amount_after_tax / 6 + loan_amount_after_tax * monthly_interest_rate
        )

        self.assertEqual(expected_installment_amount, response_data['installment_amount'])
        self.assertEqual(monthly_interest_rate, response_data['monthly_interest'])
        self.assertEqual(loan_amount_after_tax, response_data['loan_amount'])
        self.assertEqual(loan_amount_request, response_data['disbursement_amount'])
        self.assertEqual(expected_tax, response_data['tax'])
        self.assertEqual(expected_loan_status, response_data['loan_status'])
        self.assertEqual(6, response_data['loan_duration'])

        self.assertEqual(response.status_code, HTTP_200_OK)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_submit_loan_non_tarik_dana_with_delay_disbursement_exceeded(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
        mock_daily_max_fee,
    ):

        loan_amount_request = 1_000_000  # product sku price
        sepulsa_product = SepulsaProductFactory(
            is_active=True,
            type=SepulsaProductType.EWALLET,
            category=SepulsaProductCategory.DANA,
            customer_price_regular=loan_amount_request,
        )

        daily_max_fee = 0.2 / 100
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        dd_premium = 3_000
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium
        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_daily_max_fee.return_value = daily_max_fee
        mock_calculate_loan_amount.return_value = (
            get_loan_amount_by_transaction_type(
                loan_amount=loan_amount_request,
                origination_fee_percentage=provision_rate,
                is_withdraw_funds=False,
            ),
            self.credit_matrix,
            self.credit_matrix_product_line,
        )

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        ewallet_method = TransactionMethodFactory(
            id=TransactionMethodCode.DOMPET_DIGITAL.code,
            method=TransactionMethodCode.DOMPET_DIGITAL,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=ewallet_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)

        # request
        loan_duration = 6
        data = {
            'loan_amount_request': sepulsa_product.customer_price_regular,
            'self_bank_account': False,
            'transaction_type_code': ewallet_method.id,
            'pin': '123456',
            'loan_duration': loan_duration,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'mobile_number': "081232141231",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'is_payment_point': True,
            'payment_point_product_id': sepulsa_product.pk,
        }

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']

        # assert
        expected_loan_status = 210

        delta_days = (first_payment_date - today_date.date()).days
        max_fee_rate = (((loan_duration - 1) * 30) + delta_days) * daily_max_fee
        first_month_interest = (monthly_interest_rate / 30) * delta_days
        rest_months_interest = monthly_interest_rate * (loan_duration - 1)

        (
            is_exceeded,
            total_fee_rate,
            max_fee_rate,
            provision_fee_rate,
            adjusted_interest_rate,
            _,
            dd_premium_rate,
        ) = get_adjusted_loan_non_tarik_dana(
            max_fee_rate=max_fee_rate,
            disbursement_amount=loan_amount_request,
            interest_rate=first_month_interest + rest_months_interest,
            provision_rate=provision_rate,
            loan_duration=loan_duration,
            dd_premium=dd_premium,
        )

        expected_loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
            disbursement_amount=loan_amount_request,
            provision_rate=provision_fee_rate,
            dd_premium=0,  # adjusted
        )

        provision_amount = int(py2round((provision_rate * expected_loan_amount)))

        expected_tax = int(py2round(tax_percent * provision_amount))

        loan_amount_after_tax = expected_loan_amount + expected_tax

        (
            first_month_interest_rate,
            adjusted_monthly_interest_rate,
        ) = get_adjusted_monthly_interest_rate_case_exceed(
            adjusted_total_interest_rate=adjusted_interest_rate * loan_duration,
            first_month_delta_days=delta_days,
            loan_duration=loan_duration,
        )

        expected_installment_amount = round_rupiah(
            loan_amount_after_tax / loan_duration
            + loan_amount_after_tax * adjusted_monthly_interest_rate
        )

        self.assertEqual(expected_installment_amount, response_data['installment_amount'])
        self.assertEqual(
            py2round(adjusted_monthly_interest_rate, 3), response_data['monthly_interest']
        )
        self.assertEqual(loan_amount_after_tax, response_data['loan_amount'])
        self.assertEqual(loan_amount_request, response_data['disbursement_amount'])
        self.assertEqual(expected_tax, response_data['tax'])
        self.assertEqual(expected_loan_status, response_data['loan_status'])
        self.assertEqual(loan_duration, response_data['loan_duration'])

        self.assertEqual(response.status_code, HTTP_200_OK)

    @patch('juloserver.loan.views.views_api_v3.MercuryCustomerService')
    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_submit_tarik_for_ana_mercury(
        self,
        mock_is_product_locked,
        mock_get_credit_matrix_repeat,
        mock_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_validate_loan_concurrency,
        mock_time_zone_loan_related,
        mock_get_daily_max_fee,
        mock_mercury_service,
    ):
        available_limit = 10_000_000
        self.account_limit.available_limit = available_limit
        self.account_limit.save()
        self.fs_zero_interest.is_active = False
        self.fs_zero_interest.save()
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = today_date.date() + relativedelta(days=20)

        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_time_zone_loan_related.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_validate_loan_concurrency.return_value = True, False

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )

        provision_rate = interest_rate = 0.09
        product_lookup = ProductLookupFactory(
            origination_fee_pct=provision_rate,
            interest_rate=interest_rate,
        )
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=interest_rate,
            provision=provision_rate,
            max_tenure=6,
            min_tenure=3,
        )
        mock_get_credit_matrix_repeat.return_value = credit_matrix_repeat
        mock_get_loan_duration.return_value = [2, 3, 4, 5, 6]
        mock_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        mock_get_daily_max_fee.return_value = 0.004
        requested_amount = 4_000_000
        duration = 3
        data = {
            'loan_amount_request': requested_amount,
            'self_bank_account': True,
            'transaction_type_code': self_method.id,
            'pin': '123456',
            'loan_duration': duration,
            'loan_purpose': 'test',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
        }

        # set up mercury
        FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.ANA_TRANSACTION_MODEL,
            is_active=True,
            parameters={
                "cooldown_time_in_seconds": AnaTransactionModelSetting.DEFAULT_COOLDOWN_TIME,
                "request_to_ana_timeout_in_seconds": AnaTransactionModelSetting.DEFAULT_REQUEST_TIMEOUT,
                "whitelist_settings": {
                    "is_whitelist_active": False,
                    "whitelist_by_customer_id": [],
                    "whitelist_by_last_digit": [],
                },
                "is_hitting_ana": False,
            },
        )
        # set up J1
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()

        mock_mercury_object = MagicMock()
        mock_mercury_object.get_mercury_status_and_loan_tenure.return_value = False, []
        mock_mercury_service.return_value = mock_mercury_object

        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200

        response_data = response.json()['data']
        loan_id = response_data['loan_id']

        self.assertIsNone(TransactionModelCustomerLoan.objects.filter(loan_id=loan_id).last())

        # ana tenures are in range, but not enough limit
        max_cashloan_amount = requested_amount
        loan_range_from_ana = [duration]
        mock_mercury_object.get_mercury_status_and_loan_tenure.return_value = (
            True,
            loan_range_from_ana,
        )
        transaction_model = TransactionModelCustomerFactory(
            is_mercury=True,
            customer_id=self.customer.id,
            allowed_loan_duration=loan_range_from_ana,
            max_cashloan_amount=max_cashloan_amount,
        )
        mock_mercury_object.calculate_ana_available_cashloan_amount.return_value = (
            requested_amount - 1
        )
        mock_mercury_object.transaction_model_customer = transaction_model
        response = self.client.post('/api/loan/v3/loan', data=data)
        json_data = response.json()

        assert response.status_code == 400

        response_data = json_data['data']

        self.assertIn(
            "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia", json_data['errors'][0]
        )

        # ana tenures are in range, enough limit => ok
        loan_range_from_ana = [duration]

        mock_mercury_object.get_mercury_status_and_loan_tenure.return_value = (
            True,
            loan_range_from_ana,
        )
        mock_mercury_object.calculate_ana_available_cashloan_amount.return_value = requested_amount
        mock_mercury_object.transaction_model_customer = transaction_model
        response = self.client.post('/api/loan/v3/loan', data=data)
        assert response.status_code == 200
        json_data = response.json()
        response_data = json_data['data']

        loan_id = response_data['loan_id']
        model_loan = TransactionModelCustomerLoan.objects.filter(loan_id=loan_id).last()

        self.assertIsNotNone(model_loan)
        model_data = model_loan.transaction_model_data
        self.assertEqual(model_data['allowed_loan_duration'], loan_range_from_ana)
        self.assertEqual(model_data['max_available_cashloan_amount'], max_cashloan_amount)
        self.assertEqual(model_data['available_cashloan_limit_at_creation_time'], requested_amount)
        self.assertEqual(
            model_data['cm_max_tenure_at_creation_time'], credit_matrix_repeat.max_tenure
        )
        self.assertEqual(
            model_data['cm_min_tenure_at_creation_time'], credit_matrix_repeat.min_tenure
        )

    @patch('juloserver.loan.views.views_api_v3.can_charge_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_registration_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_loan_fee_with_self_transaction(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
        mock_julo_care_eligible,
        mock_calc_digisign_fee,
        mock_calc_registration_fee,
        mock_can_charge_digisign_fee
    ):

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        dd_premium = 3_000
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        original_insurance = 6500
        digisign_fee = 4000
        registration_fees_dict = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium
        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_calculate_loan_amount.return_value = (
            amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_can_charge_digisign_fee.return_value = True
        mock_calc_digisign_fee.return_value = digisign_fee
        mock_calc_registration_fee.return_value = registration_fees_dict

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': 1,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Delay Disbursement',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_julo_care": True,
            "is_zero_interest": False,
        }

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE)

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']
        loan = Loan.objects.filter(id=response_data['loan_id']).last()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNotNone(loan)

        transaction_detail = LoanTransactionDetail.objects.filter(loan_id=response_data['loan_id']).last()
        total_fees = response_data['loan_amount'] - response_data['disbursement_amount']
        detail = transaction_detail.detail
        self.assertIsNotNone(detail)

        provision_fee_rate = detail['provision_fee_rate']
        dd_premium = detail['dd_premium']
        insurance_premium = detail['insurance_premium']
        digisign_fee = detail['digisign_fee']
        total_registration_fee = detail['total_registration_fee']
        tax_fee = detail['tax_fee']

        sum_detail_fee = (
            int(py2round(loan.loan_amount * provision_fee_rate))
            + dd_premium
            + insurance_premium
            + total_registration_fee
            + digisign_fee
            + tax_fee
        )

        self.assertEqual(total_fees, sum_detail_fee)

    @patch('juloserver.loan.views.views_api_v3.can_charge_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_registration_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_loan_fee_with_non_self_transaction(
        self,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_credit_matrix_repeat,
        mock_calculate_loan_amount,
        mock_is_product_locked,
        mock_dd_premium,
        mock_dd_eligible,
        mock_julo_care_eligible,
        mock_calc_digisign_fee,
        mock_calc_registration_fee,
        mock_can_charge_digisign_fee
    ):

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        dd_premium = 3_000
        tax_percent = 0.11
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        original_insurance = 6500
        digisign_fee = 4000
        registration_fees_dict = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        self.account_limit.available_limit = 10_000_000
        self.account_limit.save()
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()
        self.application.product_line = product_line
        self.application.save()

        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        mock_dd_eligible.return_value = True
        mock_dd_premium.return_value = dd_premium
        mock_is_product_locked.return_value = False
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_calculate_loan_amount.return_value = (
            amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        mock_can_charge_digisign_fee.return_value = True
        mock_calc_digisign_fee.return_value = digisign_fee
        mock_calc_registration_fee.return_value = registration_fees_dict

        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.SELF
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )

        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()

        data = {
            'loan_amount_request': amount,
            'self_bank_account': True,
            'transaction_type_code': 2,
            'pin': '123456',
            'loan_duration': 3,
            'loan_purpose': 'Delay Disbursement',
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'bank_account_destination_id': self.bank_account_destination.id,
            "is_julo_care": True,
            "is_zero_interest": False,
        }

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE)

        response = self.client.post('/api/loan/v3/loan', data=data)
        response_data = response.json()['data']
        loan = Loan.objects.filter(id=response_data['loan_id']).last()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNotNone(loan)

        transaction_detail = LoanTransactionDetail.objects.filter(loan_id=response_data['loan_id']).last()
        total_fees = response_data['loan_amount'] - response_data['disbursement_amount']
        detail = transaction_detail.detail
        self.assertIsNotNone(detail)

        provision_fee_rate = detail['provision_fee_rate']
        dd_premium = detail['dd_premium']
        insurance_premium = detail['insurance_premium']
        digisign_fee = detail['digisign_fee']
        total_registration_fee = detail['total_registration_fee']
        tax_fee = detail['tax_fee']

        sum_detail_fee = (
            int(py2round(loan.loan_amount * provision_fee_rate))
            + dd_premium
            + insurance_premium
            + total_registration_fee
            + digisign_fee
            + tax_fee
        )

        self.assertEqual(total_fees, sum_detail_fee)


class TestLoanDuration(TestCase):
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

    def test_iprice_case_invalid_amount(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount + 1,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_iprice_case_invalid_id(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id + 2343,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_iprice_case_wrong_transaction_type(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": 7,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_credit_matrix_repeat(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                method=TransactionMethodCode.E_COMMERCE,
                id=10230,  # random
            ),
            version=1,
            interest=0.05,
            provision=0.1,
            max_tenure=3,
            min_tenure=1,
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_show_saving_amount": True,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        # CMR > CM => not show crossed_provision_amount
        for tenor in response.json()['data']['loan_choice']:
            assert tenor['crossed_provision_amount'] == 0
            assert tenor['crossed_loan_disbursement_amount'] == 0
            assert tenor['crossed_installment_amount'] == 0
            assert tenor['saving_information']['crossed_monthly_interest_rate'] == 0

        # CM > CMR => show crossed_provision_amount
        credit_matrix.product.origination_fee_pct = 0.2
        credit_matrix.product.interest_rate = 0.8
        credit_matrix.product.save()
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        for tenor in response.json()['data']['loan_choice']:
            assert tenor['crossed_provision_amount'] > tenor['provision_amount']
            assert tenor['crossed_loan_disbursement_amount'] < tenor['disbursement_amount']
            assert tenor['crossed_installment_amount'] > tenor['monthly_installment']
            assert (
                tenor['saving_information']['crossed_monthly_interest_rate']
                > tenor['saving_information']['monthly_interest_rate']
            )

        # CMR None => Not show crossed_proivsion_amount
        mock_credit_matrix_repeat.return_value = []
        response_without_credit_matrix = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertNotEqual(
            response.json()['data']['loan_choice'][0]['monthly_installment'],
            response_without_credit_matrix.json()['data']['loan_choice'][0]['monthly_installment'],
        )
        for tenor in response_without_credit_matrix.json()['data']['loan_choice']:
            assert tenor['crossed_provision_amount'] == 0
            assert tenor['crossed_loan_disbursement_amount'] == 0
            assert tenor['crossed_installment_amount'] == 0
            assert tenor['saving_information']['crossed_monthly_interest_rate'] == 0

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_show_saving_amount(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        amount = 3_000_000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_show_saving_amount": True,
        }

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        for loan_choice in response.json()['data']['loan_choice']:
            self.assertIn('saving_information', loan_choice)

    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_duration_with_zero_interest(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date

        TransactionMethod.objects.all().delete()
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
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
        # test with self method
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": True,
        }
        duration = 3
        _, _, disbursement_amount_zt, _ = adjust_loan_with_zero_interest(
            credit_matrix_repeat.interest,
            duration,
            credit_matrix_repeat.provision,
            self.application,
            data['loan_amount_request'],
            data['self_bank_account'],
            self.account_limit.available_limit,
        )
        loan_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, data['self_bank_account']
        )

        (
            adjusted_loan_amount,
            adjusted_origination_fee_pct,
            adjusted_disbursement_amount,
            adjusted_interest_rate,
        ) = adjust_loan_with_zero_interest(
            credit_matrix_repeat.interest,
            duration,
            credit_matrix_repeat.provision,
            self.application,
            data['loan_amount_request'],
            data['self_bank_account'],
            self.account_limit.available_limit,
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        data = response.json()['data']
        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['provision_amount'] == (
                    adjusted_loan_amount - adjusted_disbursement_amount
                )
            else:
                assert (
                    loan_choice['provision_amount'] == loan_amount * credit_matrix_repeat.provision
                )

        # test for other methods
        amount = 1_000_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.other_method.pk,
            "is_zero_interest": True,
        }
        loan_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, data['self_bank_account']
        )
        loan_amount_zt, provision_rate, disbursement_amount_zt, _ = adjust_loan_with_zero_interest(
            credit_matrix_repeat.interest,
            duration,
            credit_matrix_repeat.provision,
            self.application,
            data['loan_amount_request'],
            data['self_bank_account'],
            self.account_limit.available_limit,
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        data = response.json()['data']

        provision = credit_matrix_repeat.provision
        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['loan_amount'] == loan_amount_zt
                assert loan_choice['disbursement_amount'] == disbursement_amount_zt
                assert loan_choice['provision_amount'] == py2round(
                    provision_rate * (amount / (1 - provision_rate))
                )
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
            else:
                assert loan_choice['provision_amount'] == py2round(
                    provision * (amount / (1 - provision))
                )
                assert loan_choice['disbursement_amount'] == amount

        # test with loan_amount > available_limit => don't apply zero interest
        amount = 4_500_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.other_method.pk,
            "is_zero_interest": True,
        }
        loan_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, data['self_bank_account']
        )
        loan_amount_zt, provision_fee, disbursement_amount_zt, _ = adjust_loan_with_zero_interest(
            credit_matrix_repeat.interest,
            duration,
            credit_matrix_repeat.provision,
            self.application,
            data['loan_amount_request'],
            data['self_bank_account'],
            self.account_limit.available_limit,
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            assert loan_choice['provision_amount'] == py2round(
                loan_amount * credit_matrix_repeat.provision
            )
            assert loan_choice['disbursement_amount'] == amount

    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_duration_with_zero_interest_with_exceed(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date

        TransactionMethod.objects.all().delete()
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
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
            provision=0.7,
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
        # test with self method
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": True,
        }
        duration = 3
        _, provision_rate, _, _ = adjust_loan_with_zero_interest(
            credit_matrix_repeat.interest,
            duration,
            credit_matrix_repeat.provision,
            self.application,
            data['loan_amount_request'],
            data['self_bank_account'],
            self.account_limit.available_limit,
        )
        loan_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, data['self_bank_account']
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        data = response.json()['data']
        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                _, _, _, provision_fee_rate, monthly_interest_rate, _, _ = validate_max_fee_rule(
                    first_payment_date, 0, duration, provision_rate
                )
                assert loan_choice['provision_amount'] == int(py2round(amount * provision_fee_rate))
                assert monthly_interest_rate == 0
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
                assert (
                    loan_choice['disbursement_fee']
                    == py2round(amount * provision_fee_rate) - loan_choice['provision_amount']
                )
            else:
                _, _, _, provision_fee_rate, monthly_interest_rate, _, _ = validate_max_fee_rule(
                    first_payment_date,
                    credit_matrix_repeat.interest,
                    loan_choice['duration'],
                    credit_matrix_repeat.provision,
                )
                assert loan_choice['provision_amount'] == loan_amount * provision_fee_rate
                assert loan_choice['disbursement_fee'] == 0
                assert loan_choice['loan_campaign'] == ''

    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_duration_with_show_toggle_zero_interest(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 7, 0, 0, 0).date()
        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date

        TransactionMethod.objects.all().delete()
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        self.non_cash = TransactionMethodFactory(
            id=TransactionMethodCode.PULSA_N_PAKET_DATA.code,
            method=TransactionMethodCode.PULSA_N_PAKET_DATA,
        )
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
        self.fs_zero_interest.parameters['customer_segments'].update(is_repeat=True, is_ftc=False)
        self.fs_zero_interest.save()
        # 1. Repeat customer - cash
        # Input: cash method, is_zero_interest = True
        # output: is_show_toggle = True if duration is zero interest and vice versa
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        request = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
            "is_zero_interest": True,
        }
        duration = 3
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']
        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == True
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
            else:
                assert loan_choice['is_show_toggle'] == False

        # 2. Repeat customer - cash
        # Input: cash method, is_zero_interest = False
        # output: is_show_toggle = True if duration is zero interest and vice versa
        request["is_zero_interest"] = False
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == True
                assert loan_choice['loan_campaign'] == ''
            else:
                assert loan_choice['is_show_toggle'] == False

        # 3. Repeat customer - non cash
        # Input: non-cash method, is_zero_interest = True
        # output: is_show_toggle = False for all, zero interest is active
        request = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.non_cash.pk,
            "is_zero_interest": True,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == False
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
            else:
                assert loan_choice['is_show_toggle'] == False

        # 4. FTC customer - cash
        # Input: non-cash method, is_zero_interest = True
        # output: is_show_toggle = False for all, zero interest is active
        loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER)
        loan.save()
        request = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.other_method.pk,
            "is_zero_interest": True,
        }
        self.fs_zero_interest.parameters['customer_segments'].update(is_repeat=False, is_ftc=True)
        self.fs_zero_interest.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == False
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
            else:
                assert loan_choice['is_show_toggle'] == False

        # 5. FTC customer - non cash
        # Input: non-cash method, is_zero_interest = True
        # output: is_show_toggle = False for all, zero interest is active
        request = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.non_cash.pk,
            "is_zero_interest": True,
        }
        self.fs_zero_interest.parameters['customer_segments'].update(is_repeat=False, is_ftc=True)
        self.fs_zero_interest.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == False
                assert loan_choice['loan_campaign'] == DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
            else:
                assert loan_choice['is_show_toggle'] == False

        # 5. not FTC or repeat customer
        # Input: is_zero_interest = False
        # output: is_show_toggle = False, No apply zero interest
        request = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": self.non_cash.pk,
            "is_zero_interest": False,
        }
        self.fs_zero_interest.parameters['customer_segments'].update(is_repeat=False, is_ftc=False)
        self.fs_zero_interest.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=request)
        data = response.json()['data']

        for loan_choice in data['loan_choice']:
            if loan_choice['duration'] == duration:
                assert loan_choice['is_show_toggle'] == False
                assert loan_choice['loan_campaign'] == ''
            else:
                assert loan_choice['is_show_toggle'] == False

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_dbr_ratio_success(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
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
        monthly_income = 10_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=2_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=2_400_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=2_300_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()
        amount = 3_000_000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_dbr": True,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        mock_credit_matrix_repeat.return_value = []
        response_without_credit_matrix = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertNotEqual(
            response.json()['data']['loan_choice'][0]['monthly_installment'],
            response_without_credit_matrix.json()['data']['loan_choice'][0]['monthly_installment'],
        )

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_dbr_ratio_exception(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
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
        monthly_income = 10_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=5_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=5_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=5_500_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()
        amount = 3_000_000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_dbr": True,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }

        date_loan = date.today()
        # mock yesterday loan
        LoanDbrLogFactory(
            log_date=date_loan - relativedelta(days=1),
            application=self.application,
            source=DBRConst.LOAN_DURATION,
            transaction_method_id=TransactionMethodCode.E_COMMERCE.code,
        )
        # mock loan creation today
        LoanDbrLogFactory(
            log_date=date_loan,
            application=self.application,
            source=DBRConst.LOAN_DURATION,
            transaction_method_id=TransactionMethodCode.E_COMMERCE.code,
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        popup_banner = response.json()['data']['popup_banner']
        self.assertEqual(popup_banner['is_active'], True)

        # Check if there's log
        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=self.application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_DURATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 1)

        # check URL is updated properly
        self.feature_setting.parameters["popup_banner"][DBRConst.ADDITIONAL_INFORMATION][
            DBRConst.LINK
        ] = (
            "https://cms-staging.julo.co.id/app/update_income/forms/?token=[token]"
            "&transaction_type_code=[transaction_type_code]&self_bank_account=[self_bank_account]"
        )
        self.feature_setting.save()
        # rehit the API
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        popup_banner = response.json()['data']['popup_banner']
        self.assertEqual(popup_banner['is_active'], True)
        new_link = popup_banner[DBRConst.ADDITIONAL_INFORMATION][DBRConst.LINK]
        self.assertEqual(new_link.find("[token]"), -1)
        self.assertEqual(new_link.find("[self_bank_account]"), -1)
        self.assertEqual(new_link.find("[transaction_type_code]"), -1)

        # log only record once
        loan_dbr_log_count = LoanDbrLog.objects.filter(
            application_id=self.application.id,
            log_date=date_loan,
            source=DBRConst.LOAN_DURATION,
        ).count()
        self.assertEqual(loan_dbr_log_count, 1)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_dbr_ratio_change_loan_duration(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
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
        monthly_income = 6_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=2_300_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=2_300_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=2_300_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()
        amount = 1_500_000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        min_tenure = 1
        max_tenure = 9
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.1,
            provision=0.05,
            max_tenure=max_tenure,
            min_tenure=min_tenure,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [4, 5]
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_dbr": True,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        loan_choices = response.json()['data']['loan_choice']
        for loan in loan_choices:
            duration = loan['duration']
            monthly_installment = loan['monthly_installment']
            first_monthly_installment = loan['first_monthly_installment']
            if first_monthly_installment > monthly_installment:
                monthly_installment = first_monthly_installment

            max_value = monthly_income / 2 - 2_300_000
            self.assertTrue(monthly_installment <= max_value)
            self.assertTrue(duration <= max_tenure)

        # test feature setting max tenure, start from 6 month
        amount = 2_500_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_dbr": True,
            "transaction_type_code": TransactionMethodCode.SELF.code,
        }
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_MAX_ALLOWED_DURATION,
            description="Enable Credit Matrix Repeat",
            parameters=[
                {"duration": 1, "max_amount": 100_000, "min_amount": 0},
                {"duration": 3, "max_amount": 450_000, "min_amount": 100_000},
                {"duration": 7, "max_amount": 6_000_000, "min_amount": 450_000},
            ],
        )
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        loan_choices = response.json()['data']['loan_choice']
        for loan in loan_choices:
            # make sure duration is not exceed FS
            duration = loan['duration']
            self.assertTrue(duration <= 7)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_dbr_ratio_change_loan_duration_2(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
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
        monthly_income = 6_000_000
        date_loan = date.today()
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=1),
            due_amount=2_300_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=2),
            due_amount=2_300_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date_loan + relativedelta(months=3),
            due_amount=2_300_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.payday = 30
        self.application.save()
        amount = 2_500_000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        max_tenure = 8
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.1,
            provision=0.05,
            max_tenure=max_tenure,
            min_tenure=1,
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
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_dbr": False,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        loan_choices = response.json()['data']['loan_choice']
        self.assertEqual(len(loan_choices), 4)
        is_exceeding_dbr_rule = False
        for loan in loan_choices:
            monthly_installment = loan['monthly_installment']
            first_monthly_installment = loan['first_monthly_installment']
            if first_monthly_installment > monthly_installment:
                monthly_installment = first_monthly_installment

            max_value = monthly_income / 2 - 2_300_000
            if monthly_installment >= max_value:
                is_exceeding_dbr_rule = True

        self.assertTrue(is_exceeding_dbr_rule)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_loan_tax(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        # cash: transaction method 1
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        for loan_choice in response_data['loan_choice']:
            self.assertNotEqual(
                loan_choice['tax'],
                0,
            )
            assert loan_choice['loan_amount'] == amount + loan_choice['tax']
            self.assertEqual(
                loan_choice['available_limit_after_transaction'],
                loan_choice['available_limit'] - loan_choice['loan_amount'],
            )

        # test with non-cash: other transactions
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        adjusted_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, False
        )
        for loan_choice in response_data['loan_choice']:
            self.assertNotEqual(
                loan_choice['tax'],
                0,
            )
            assert loan_choice['loan_amount'] == adjusted_amount + loan_choice['tax']

        tax_feature_setting.is_active = False
        tax_feature_setting.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        for loan_choice in response_data['loan_choice']:
            self.assertEqual(
                loan_choice['tax'],
                0,
            )

        tax_feature_setting.is_active = True
        tax_feature_setting.save()
        adjusted_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, False
        )
        self.account_limit.available_limit = adjusted_amount
        self.account_limit.save()
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        assert len(response_data['loan_choice']) == 0

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_loan_tax_installment(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=product_line,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.E_COMMERCE.code,
                method=TransactionMethodCode.E_COMMERCE,
            ),
            version=1,
            interest=0.5,
            provision=0.1,
            max_tenure=6,
            min_tenure=1,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3, 4, 5, 6]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
        }

        tax_feature_setting.is_active = False
        tax_feature_setting.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        no_tax_response = dict()
        for loan_choice in response_data['loan_choice']:
            self.assertEqual(loan_choice['tax'], 0)
            no_tax_response[loan_choice['duration']] = loan_choice

        # test with non-cash: other transactions
        tax_feature_setting.is_active = True
        tax_feature_setting.save()
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        response_data = response.json()['data']
        adjusted_amount = get_loan_amount_by_transaction_type(
            amount, credit_matrix_repeat.provision, False
        )
        for loan_choice in response_data['loan_choice']:
            self.assertNotEqual(
                loan_choice['tax'],
                0,
            )
            data_choice = no_tax_response[loan_choice['duration']]
            assert loan_choice['loan_amount'] == adjusted_amount + loan_choice['tax']
            assert loan_choice['monthly_installment'] > data_choice['monthly_installment']
            assert (
                loan_choice['first_monthly_installment'] > data_choice['first_monthly_installment']
            )

    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.calculate_installment_amount')
    @patch('juloserver.loan.views.views_api_v3.get_adjusted_monthly_interest_rate_case_exceed')
    @patch('juloserver.loan.views.views_api_v3.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.refiltering_cash_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_loan_duration_with_exceed_prorate(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_refiltering_cash_loan_duration,
        mock_is_product_locked,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_get_monthly_interest_rate_exceed,
        mock_calculate_installment_amount,
        mock_get_loan_duration,
    ):
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date

        TransactionMethod.objects.all().delete()
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.self_method,
            version=1,
            interest=0.05,
            provision=0.7,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        available_duration = [3, 4, 5]
        mock_get_loan_duration.return_value = available_duration
        mock_refiltering_cash_loan_duration.return_value = available_duration
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
        mock_get_monthly_interest_rate_exceed.return_value = 0.1, 0.2  # any

        amount = 4_000_000
        calculate_installment_amount = 20000  # any
        mock_calculate_installment_amount.return_value = calculate_installment_amount
        # test with self method
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self.self_method.pk,
        }
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        assert response.status_code == 200

        result_data = response.json()['data']
        for loan_choice in result_data['loan_choice']:
            # this breaks if monthly installment is not value from calculate_installment_amount
            assert loan_choice['monthly_installment'] == calculate_installment_amount

        args_list = mock_calculate_installment_amount.call_args_list
        assert len(args_list) == len(available_duration)

        assert args_list == [
            call(ANY, ANY, 0.2),
            call(ANY, ANY, 0.2),
            call(ANY, ANY, 0.2),
        ]

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_julo_care_case_exceeded(
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
        mock_daily_max_fee,
    ):
        """
        insurance rate is 0 when exceeded
        """
        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 3
        mock_get_loan_duration.return_value = [tenure]
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
                "tax_percentage": 0.1,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        original_insurance = 6500
        expected_insurance_rate = 0
        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        daily_max_fee_rate = 0.002
        mock_daily_max_fee.return_value = daily_max_fee_rate
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, expected_insurance_rate)

        # provison asserting
        expected_provision_rate = provision_rate
        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee, (amount * expected_provision_rate + amount * expected_insurance_rate)
        )

        tax = choice['tax']
        self.assertEqual(tax, (amount * expected_provision_rate) * 0.1)

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount - admin_fee - tax)

        # assert due amount
        total_days = 20 + 30 * 2
        max_fee_rate = daily_max_fee_rate * total_days  # total days
        expected_total_interest_rate = (
            max_fee_rate - expected_provision_rate - expected_insurance_rate
        )
        expected_monthly_interest_rate = expected_total_interest_rate / total_days * 30
        due_amount = choice['monthly_installment']
        expected_due_amount = round_rupiah(
            amount / tenure + amount * expected_monthly_interest_rate
        )
        self.assertEqual(due_amount, expected_due_amount)

        # CASE MAX FEE IS REALLY SMALL
        # adjuste variables
        daily_max_fee_rate = 0.00005
        mock_daily_max_fee.return_value = daily_max_fee_rate
        max_fee_rate = daily_max_fee_rate * total_days  # total days

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, expected_insurance_rate)

        _, expected_provision_rate, _ = get_adjusted_total_interest_rate(
            max_fee=max_fee_rate,
            provision_fee=provision_rate,
            insurance_premium_rate=0,
        )
        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee, (amount * expected_provision_rate + amount * expected_insurance_rate)
        )

        tax = choice['tax']
        self.assertEqual(tax, (amount * expected_provision_rate) * 0.1)

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount - admin_fee - tax)

        # assert due amount
        expected_total_interest_rate = (
            max_fee_rate - expected_provision_rate - expected_insurance_rate
        )
        expected_monthly_interest_rate = expected_total_interest_rate / total_days * 30
        due_amount = choice['monthly_installment']

        # interest rate == 0, no rounding
        expected_due_amount = int(
            math.floor(amount / tenure + amount * expected_monthly_interest_rate)
        )
        self.assertEqual(due_amount, expected_due_amount)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_delayed_disbursement_exceeded(
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
        mock_dd_eligible,
        mock_dd_premium,
        mock_daily_max_fee,
    ):

        # toggle dd active
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()

        mock_dd_eligible.return_value = True
        dd_premium = 3_000
        mock_dd_premium.return_value = dd_premium
        """
        insurance rate is 0 when exceeded
        """
        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 3
        mock_get_loan_duration.return_value = [tenure]
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
                "tax_percentage": 0.1,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        original_insurance = 6500
        expected_insurance_rate = 0
        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        daily_max_fee_rate = 0.002
        mock_daily_max_fee.return_value = daily_max_fee_rate

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, expected_insurance_rate)

        dd_rate = choice['delayed_disbursement_premium_rate']
        self.assertEqual(dd_rate, dd_premium / amount)

        # provision asserting
        expected_provision_rate = provision_rate
        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee,
            ((amount * expected_provision_rate + amount * expected_insurance_rate) + dd_premium),
        )

        tax = choice['tax']
        self.assertEqual(tax, (amount * (expected_provision_rate + dd_rate) * 0.1))

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount - admin_fee - tax)

        # assert due amount
        total_days = 20 + 30 * 2
        max_fee_rate = daily_max_fee_rate * total_days  # total days
        expected_total_interest_rate = (
            max_fee_rate - expected_provision_rate - expected_insurance_rate - dd_rate
        )
        expected_monthly_interest_rate = expected_total_interest_rate / total_days * 30
        due_amount = choice['monthly_installment']
        expected_due_amount = round_rupiah(
            amount / tenure + amount * expected_monthly_interest_rate
        )
        self.assertEqual(due_amount, expected_due_amount)

        # CASE MAX FEE IS REALLY SMALL, and loan_amount small
        # adjust variables
        daily_max_fee_rate = 0.00005
        mock_daily_max_fee.return_value = daily_max_fee_rate
        max_fee_rate = daily_max_fee_rate * total_days  # total days

        amount = 100_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, expected_insurance_rate)

        dd_rate = choice['delayed_disbursement_premium_rate']
        expected_dd_rate = 0
        self.assertEqual(expected_dd_rate, dd_rate)

        # use validate_max_fee_rule instead of get_adjusted_total_interest_rate
        _, _, _, provision_fee_rate, monthly_interest_rate, _, _ = validate_max_fee_rule(
            first_payment_date,
            0,
            tenure,
            provision_rate,
            0,
            (dd_premium / amount),
        )

        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee, (amount * (expected_insurance_rate + provision_fee_rate + expected_dd_rate))
        )

        tax = choice['tax']
        self.assertEqual(tax, (amount * provision_fee_rate) * 0.1)

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount - admin_fee - tax)

        # assert due amount
        expected_monthly_interest_rate = 0
        due_amount = choice['monthly_installment']
        expected_due_amount = int(
            math.floor(amount / choice['duration'] + amount * expected_monthly_interest_rate)
        )

        self.assertEqual(due_amount, expected_due_amount)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_delayed_disbursement_non_tarik_dana(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
        mock_dd_eligible,
        mock_dd_premium,
        mock_daily_max_fee,
    ):

        # toggle dd active
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()

        mock_dd_eligible.return_value = True
        dd_premium = 3_000
        mock_dd_premium.return_value = dd_premium

        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        ewallet_method = TransactionMethodFactory(
            id=TransactionMethodCode.DOMPET_DIGITAL.code,
            method=TransactionMethodCode.DOMPET_DIGITAL,
        )

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=ewallet_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 3
        mock_get_loan_duration.return_value = [tenure]
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

        tax_percentage = 0.1
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percentage,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        data = {
            "account_id": self.account.id,
            "loan_amount_request": amount,
            "transaction_type_code": ewallet_method.id,
            "is_payment_point": True,
            "self_bank_account": False,
            "is_tax": True,
            "is_zero_interest": False,
        }

        daily_max_fee_rate = 0.7
        mock_daily_max_fee.return_value = daily_max_fee_rate

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, False)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, 0)  # should be 0

        # provision assert
        expected_provision_rate = provision_rate
        admin_fee = choice['provision_amount']
        ewallet_loan_amount = get_loan_amount_by_transaction_type(
            amount + dd_premium, expected_provision_rate, False
        )

        self.assertEqual(
            admin_fee, py2round(ewallet_loan_amount * expected_provision_rate) + dd_premium
        )

        final_loan_amount_with_tax = amount + admin_fee + choice['tax']
        self.assertEqual(choice['loan_amount'], final_loan_amount_with_tax)

        dd_rate = choice['delayed_disbursement_premium_rate']
        self.assertEqual(dd_rate, py2round(dd_premium / ewallet_loan_amount, 7))

        tax = choice['tax']
        self.assertEqual(
            tax,
            py2round(
                ((ewallet_loan_amount * expected_provision_rate) + dd_premium) * tax_percentage, 0
            ),
        )

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount)

        # assert due amount
        due_amount = choice['monthly_installment']
        expected_due_amount = round_rupiah(
            math.floor(final_loan_amount_with_tax / tenure)
            + py2round(final_loan_amount_with_tax * monthly_interest_rate)
        )

        self.assertEqual(due_amount, expected_due_amount)

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_delayed_disbursement_non_tarik_dana_exceeded(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
        mock_dd_eligible,
        mock_dd_premium,
        mock_daily_max_fee,
    ):

        # toggle dd active
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()

        mock_dd_eligible.return_value = True
        dd_premium = 3_000
        mock_dd_premium.return_value = dd_premium

        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 100_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        ewallet_method = TransactionMethodFactory(
            id=TransactionMethodCode.DOMPET_DIGITAL.code,
            method=TransactionMethodCode.DOMPET_DIGITAL,
        )

        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=ewallet_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 1
        mock_get_loan_duration.return_value = [tenure]
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

        tax_percentage = 0.11
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": tax_percentage,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        data = {
            "account_id": self.account.id,
            "loan_amount_request": amount,
            "transaction_type_code": ewallet_method.id,
            "is_payment_point": True,
            "self_bank_account": False,
            "is_tax": True,
            "is_zero_interest": False,
        }

        daily_max_fee_rate = 0.2 / 100  # OJK 2025
        mock_daily_max_fee.return_value = daily_max_fee_rate

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, False)

        insurance_rate = choice['insurance_premium_rate']
        self.assertEqual(insurance_rate, 0)  # should be 0

        # provision assert
        adjusted_provision_rate = 20 * daily_max_fee_rate
        admin_fee = choice['provision_amount']
        ewallet_loan_amount = get_loan_amount_by_transaction_type(
            amount, adjusted_provision_rate, False
        )

        self.assertEqual(admin_fee, py2round(ewallet_loan_amount * adjusted_provision_rate))

        final_loan_amount_with_tax = amount + admin_fee + choice['tax']
        self.assertEqual(choice['loan_amount'], final_loan_amount_with_tax)

        dd_rate = choice['delayed_disbursement_premium_rate']
        self.assertEqual(dd_rate, 0)

        tax = choice['tax']
        self.assertEqual(
            tax,
            py2round(((ewallet_loan_amount * adjusted_provision_rate)) * tax_percentage, 0),
        )

        campaign = choice['loan_campaign']
        self.assertEqual(campaign, '')

        disbursement_fee = choice['disbursement_fee']
        self.assertEqual(disbursement_fee, 0)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount)

        # assert due amount
        due_amount = choice['monthly_installment']
        expected_due_amount = choice['loan_amount']
        self.assertEqual(due_amount, expected_due_amount)

        first_month_installment = choice['first_monthly_installment']
        self.assertEqual(due_amount, first_month_installment)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_campaign_tenor_recommendation(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        amount = 3000000
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": TransactionMethodCode.SELF.code,
        }

        # set up FS
        min_tenure = 4
        max_tenure = 10
        campaign_tag = "ABC"
        fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.LOAN_TENURE_RECOMMENDATION,
            is_active=True,
            parameters={
                'experiment_config': {
                    'is_active': False,
                    'experiment_customer_id_last_digits': [],
                },
                'general_config': {
                    'min_tenure': min_tenure,
                    'max_tenure': max_tenure,
                    'campaign_tag': campaign_tag,
                    'transaction_methods': [
                        TransactionMethodCode.SELF.code,
                    ],
                },
            },
        )

        mock_get_loan_duration.return_value = [5, 6]
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, 200)
        response_data = response.json()['data']
        self.assertEqual(len(response_data['loan_choice']), 2)
        self.assertEqual(
            response_data['loan_choice'][0]['loan_campaign'],
            "",
        )
        self.assertEqual(
            response_data['loan_choice'][1]['loan_campaign'],
            campaign_tag,
        )

        # under min tenure FS
        mock_get_loan_duration.return_value = [2]
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, 200)
        response_data = response.json()['data']
        self.assertEqual(len(response_data['loan_choice']), 1)
        self.assertEqual(
            response_data['loan_choice'][0]['loan_campaign'],
            "",
        )

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_thor_tenure_intervention(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                method=TransactionMethodCode.E_COMMERCE,
                id=10230,  # random
            ),
            version=1,
            interest=0.08,
            provision=0.1,
            max_tenure=9,
            min_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [8, 9]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=12,
            min_duration=6,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_show_saving_amount": True,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code
        }
        parameters = {
            'thresholds': {
                'data': {
                    6: 0.01,
                    9: 0.02,
                    12: 0.05,
                },
                'is_active': True,
            },
            'minimum_pricing': {
                'data': 0.04,
                'is_active': True,
            },
            'cmr_segment': {
                'data': ['activeus_a'],
                'is_active': True,
            },
            'transaction_methods': {
                'data': [1, 2, 8],
                'is_active': True,
            }
        }
        self.new_tenor_feature_setting = FeatureSettingFactory(
            is_active=False,
            feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
            parameters=parameters
        )

        min_tenure = 6
        max_tenure = 9
        campaign_tag = "Paling Murah!"
        self.loan_tenure_recommendation_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.LOAN_TENURE_RECOMMENDATION,
            is_active=True,
            parameters={
                'experiment_config': {
                    'is_active': False,
                    'experiment_customer_id_last_digits': [],
                },
                'general_config': {
                    'min_tenure': min_tenure,
                    'max_tenure': max_tenure,
                    'campaign_tag': campaign_tag,
                    'intervention_campaign': campaign_tag,
                    'transaction_methods': [
                        TransactionMethodCode.SELF.code,
                        TransactionMethodCode.E_COMMERCE.code,
                    ],
                },
            },
        )

        thor_parameters = {
            'delay_intervention': 20,
            'tenor_option': [6, 9, 12]
        }
        self.thor_fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.THOR_TENOR_INTERVENTION,
            parameters=thor_parameters
        )
        expected_tenure_intervention = {
            'delay_intervention': 20,
            'duration_intervention': [6, 9, 12]
        }
        # with cmr
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, 200)
        result_tenure_intervention = response.json()['data']['tenure_intervention']
        # check if tenure intervention exists
        self.assertEqual(expected_tenure_intervention, result_tenure_intervention)
        loan_choices_cmr = response.json()['data']['loan_choice']

        # with new_tenor_based_pricing fs on
        self.new_tenor_feature_setting.is_active = True
        self.new_tenor_feature_setting.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        loan_choices_tenor_based = response.json()['data']['loan_choice']

        # tag_campaign will only show on tenor based pricing for recommended tenor
        self.assertEqual(loan_choices_cmr[-1]['tag_campaign'], "")
        self.assertEqual(loan_choices_tenor_based[-1]['tag_campaign'], "Cicilan Termurah")

        # intervention campaign will be empty if not max tenor
        self.assertEqual(loan_choices_cmr[0]['intervention_campaign'], "")
        self.assertEqual(loan_choices_tenor_based[0]['intervention_campaign'], "")

        # intervention campaign show on tenor based pricing and max_tenure
        self.assertEqual(loan_choices_tenor_based[-1]['intervention_campaign'], campaign_tag)

        # is_show_intervention false for cmr
        self.assertEqual(loan_choices_cmr[0]['is_show_intervention'], False)

        # is_show_intervention true for tenor based pricing
        self.assertEqual(loan_choices_tenor_based[0]['is_show_intervention'], True)

        # is_show_intervention false for tenor based pricing if duration == max_tenure
        self.assertEqual(loan_choices_tenor_based[-1]['is_show_intervention'], False)

        # campaign_tag will show for max_tenure for cmr(only campaign_tag) and tenor based pricing
        self.assertEqual(loan_choices_cmr[-1]['loan_campaigns'], [campaign_tag])
        self.assertEqual(loan_choices_tenor_based[-1]['loan_campaigns'], [campaign_tag, "Lihat Detail"])

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_tenor_based_pricing(
        self,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
    ):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line=self.application.product_line,
            transaction_method=TransactionMethodFactory(
                method=TransactionMethodCode.E_COMMERCE,
                id=10230,  # random
            ),
            version=1,
            interest=0.08,
            provision=0.1,
            max_tenure=9,
            min_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [8, 9]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=12,
            min_duration=6,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "is_show_saving_amount": True,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code
        }
        parameters = {
            'thresholds': {
                'data': {
                    6: 0.01,
                    9: 0.02,
                    12: 0.05,
                },
                'is_active': True,
            },
            'minimum_pricing': {
                'data': 0.04,
                'is_active': True,
            },
            'cmr_segment': {
                'data': ['activeus_a'],
                'is_active': True,
            },
            'transaction_methods': {
                'data': [1, 2, 8],
                'is_active': True,
            }
        }
        self.new_tenor_feature_setting = FeatureSettingFactory(
            is_active=False,
            feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
            parameters=parameters
        )
        # with cmr
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, 200)
        loan_choices_cmr = response.json()['data']['loan_choice']

        # with new_tenor_based_pricing fs on
        self.new_tenor_feature_setting.is_active = True
        self.new_tenor_feature_setting.save()
        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        loan_choices_tenor_based = response.json()['data']['loan_choice']
        for tenor, tenor_fs in zip(loan_choices_cmr, loan_choices_tenor_based):
            assert (
                tenor['saving_information']['monthly_interest_rate']
                > tenor_fs['saving_information']['monthly_interest_rate']
            )

    @patch('juloserver.loan.views.views_api_v3.can_charge_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_digisign_fee')
    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_digisign_fee(
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
        mock_dd_eligible,
        mock_dd_premium,
        mock_daily_max_fee,
        mock_calc_digisign_fee,
        mock_can_charge_digisign_fee
    ):

        # toggle dd active
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()

        mock_can_charge_digisign_fee.return_value = True
        mock_dd_eligible.return_value = True
        dd_premium = 0
        digisign_fee = 4000
        mock_dd_premium.return_value = dd_premium
        """
        insurance rate is 0 when exceeded
        """
        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 3
        mock_get_loan_duration.return_value = [tenure]
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
        mock_calc_digisign_fee.return_value = digisign_fee

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.1,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        DigisignRegistrationFactory(
            customer_id=self.customer.id,
            reference_number='111',
            registration_status=RegistrationStatus.INITIATED,
            verification_results={
                'dukcapil_present': True,
                'fr_present': True,
                'liveness_present': True,
            }
        )

        original_insurance = 6500
        expected_insurance_rate = 0
        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        daily_max_fee_rate = 0.002
        mock_daily_max_fee.return_value = daily_max_fee_rate

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        self.assertEqual(choice['digisign_fee'], digisign_fee)

        # provision asserting
        expected_provision_rate = provision_rate
        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee,
            ((amount * expected_provision_rate + amount * expected_insurance_rate)),
        )

        tax = choice['tax']
        self.assertEqual(tax, (amount*expected_provision_rate + digisign_fee) * 0.1)

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount - admin_fee - tax - digisign_fee)

        self.assertEqual(choice['loan_amount'], amount)

        # assert due amount
        total_days = 20 + 30 * 2
        max_fee_rate = daily_max_fee_rate * total_days  # total days
        expected_total_interest_rate = (
            max_fee_rate - expected_provision_rate - expected_insurance_rate
        )
        expected_monthly_interest_rate = expected_total_interest_rate / total_days * 30
        due_amount = choice['monthly_installment']
        expected_due_amount = round_rupiah(
            amount / tenure + amount * expected_monthly_interest_rate
        )
        self.assertEqual(due_amount, expected_due_amount)

        # CASE self_bank_account is False
        amount = 1_000_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": other_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']
        adjust_amount = int(py2round(old_div(amount, (1 - provision_rate))))

        tax = choice['tax']
        self.assertEqual(tax, int(py2round((adjust_amount * provision_rate + digisign_fee) * 0.1)))

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount)

        loan_amount = choice['loan_amount']
        self.assertEqual(loan_amount, adjust_amount + tax + digisign_fee)

    @patch('juloserver.loan.views.views_api_v3.can_charge_digisign_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_registration_fee')
    @patch('juloserver.loan.views.views_api_v3.calc_digisign_fee')
    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.views.views_api_v3.get_delayed_disbursement_premium')
    @patch('juloserver.loan.views.views_api_v3.is_eligible_for_delayed_disbursement')
    @patch('juloserver.loan.views.views_api_v3.get_eligibility_status')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    def test_with_registration_fee(
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
        mock_dd_eligible,
        mock_dd_premium,
        mock_daily_max_fee,
        mock_calc_digisign_fee,
        mock_calc_registration_fee,
        mock_can_charge_digisign_fee
    ):

        # toggle dd active
        self.fs_delay_disbursement.is_active = True
        self.fs_delay_disbursement.save()

        mock_can_charge_digisign_fee.return_value = True
        mock_dd_eligible.return_value = True
        dd_premium = 0
        digisign_fee = 4000
        registration_fees_dict = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }
        total_registration_fee = 8000
        mock_dd_premium.return_value = dd_premium
        """
        insurance rate is 0 when exceeded
        """
        # first month: 20 days due date
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        amount = 1_000_000
        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        tenure = 3
        mock_get_loan_duration.return_value = [tenure]
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
        mock_calc_digisign_fee.return_value = digisign_fee
        mock_calc_registration_fee.return_value = registration_fees_dict

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.1,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        original_insurance = 6500
        expected_insurance_rate = 0
        mock_julo_care_eligible.return_value = (True, {'3': original_insurance})
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": self_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }
        daily_max_fee_rate = 0.002
        mock_daily_max_fee.return_value = daily_max_fee_rate

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']

        is_toggle = choice['is_show_toggle']
        self.assertEqual(is_toggle, False)

        device_eligible = response_data['is_device_eligible']
        self.assertEqual(device_eligible, True)

        self.assertEqual(choice['digisign_fee'], digisign_fee + total_registration_fee)

        # provision asserting
        expected_provision_rate = provision_rate
        admin_fee = choice['provision_amount']
        self.assertEqual(
            admin_fee,
            ((amount * expected_provision_rate)),
        )

        tax = choice['tax']
        self.assertEqual(
            tax,
            (amount*expected_provision_rate + digisign_fee + total_registration_fee) * 0.1
        )

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(
            disbursement_amount, amount - admin_fee - tax - digisign_fee - total_registration_fee
        )

        self.assertEqual(choice['loan_amount'], amount)

        # assert due amount
        total_days = 20 + 30 * 2
        max_fee_rate = daily_max_fee_rate * total_days  # total days
        expected_total_interest_rate = (
            max_fee_rate - expected_provision_rate - expected_insurance_rate
        )
        expected_monthly_interest_rate = expected_total_interest_rate / total_days * 30
        due_amount = choice['monthly_installment']
        expected_due_amount = round_rupiah(
            amount / tenure + amount * expected_monthly_interest_rate
        )
        self.assertEqual(due_amount, expected_due_amount)

        # CASE self_bank_account is False
        amount = 1_000_000
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "transaction_type_code": other_method.id,
            "is_zero_interest": False,
            "is_julo_care": True,
            "is_tax": True,
        }

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        choice = response.json()['data']['loan_choice'][0]
        response_data = response.json()['data']
        adjust_amount = int(py2round(old_div(amount, (1 - provision_rate))))

        tax = choice['tax']
        self.assertEqual(
            tax,
            int(py2round(
                (adjust_amount * provision_rate + digisign_fee + total_registration_fee) * 0.1
            ))
        )

        disbursement_amount = choice['disbursement_amount']
        self.assertEqual(disbursement_amount, amount)

        loan_amount = choice['loan_amount']
        self.assertEqual(loan_amount, adjust_amount + tax + digisign_fee + total_registration_fee)

    @patch('juloserver.loan.views.views_api_v3.filter_loan_choice')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.MercuryCustomerService')
    def test_kirim_dana_mercury_status(
        self,
        mock_mercury_service,
        mock_get_loan_duration,
        mock_get_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_is_product_locked,
        mock_filter_loan_choice,
    ):
        # set up, app 190 J1
        mock_get_credit_matrix_repeat.return_value = None
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.application_status_id = 190
        self.application.save()
        mock_is_product_locked.return_value = False
        expected_provision_rate = 0.08
        product_lookup = ProductLookupFactory(origination_fee_pct=expected_provision_rate)
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        amount = 3000000
        transaction_method_id = TransactionMethodCode.OTHER.code
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": True,
            "transaction_type_code": transaction_method_id,
        }

        get_loan_duration_result = [3]
        # case mercury status False
        mock_mercury_object = MagicMock()
        mock_mercury_object.get_mercury_status_and_loan_tenure.return_value = False, []
        mock_mercury_service.return_value = mock_mercury_object
        mock_get_loan_duration.return_value = get_loan_duration_result

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, 200)

        mock_get_loan_duration.assert_called_once_with(
            loan_amount_request=amount,
            max_duration=credit_matrix_product_line.max_duration,
            min_duration=credit_matrix_product_line.min_duration,
            set_limit=self.account_limit.set_limit,
            customer=self.customer,
            application=self.application,
        )

        # case mercury status True
        mock_get_loan_duration.reset_mock()
        mock_mercury_object.reset_mock()

        expected_max_duration = 7
        expected_min_duration = 3
        expected_ana_loan_tenure = [3, 4, 5]
        mock_filter_loan_choice.return_value = {
            3: {
                'data': 'data',
            }
        }

        mock_mercury_object = MagicMock()
        mock_mercury_object.get_mercury_status_and_loan_tenure.return_value = (
            True,
            expected_ana_loan_tenure,
        )
        compute_mercury_tenures_value = range(
            expected_min_duration,
            expected_max_duration + 1,
        )
        mock_mercury_object.compute_mercury_tenures.return_value = compute_mercury_tenures_value
        mock_mercury_service.return_value = mock_mercury_object
        mock_get_loan_duration.return_value = [3]

        response = self.client.post('/api/loan/v3/loan-duration/', data=data)
        self.assertEqual(response.status_code, 200)

        mock_mercury_object.compute_mercury_tenures.assert_called_once_with(
            final_tenures=get_loan_duration_result,
            mercury_loan_tenures=expected_ana_loan_tenure,
        )
        mock_filter_loan_choice.assert_called_once_with(
            original_loan_choice=ANY,
            displayed_tenures=compute_mercury_tenures_value,
            customer_id=self.customer.id,
        )


class TestRangeLoanAmountV3(TestCase):
    def setUp(self):
        super().setUp()
        self.available_limit = 15000000
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(
            account=self.account, available_limit=self.available_limit
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.dbr_fs = FeatureSettingFactory(
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
        FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={"daily_max_fee": 0.3},
            is_active=True,
            category="credit_matrix",
            description="Test",
        )
        parameters = {
            "whitelist": {"is_active": False, "customer_ids": []},
            "dbr_loan_amount_default": 2_000_000,
            "min_amount_threshold": 300_000,
        }
        self.loan_amount_config = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_AMOUNT_DEFAULT_CONFIG,
            is_active=True,
            parameters=parameters,
        )

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
    ):
        self.product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
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
        self.application.application_status_id = 420
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(200, response.status_code, response.content)
        self.assertIsNotNone(response.json()['data']['default_amount'])

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_exception(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
    ):
        credit_matrix = CreditMatrixFactory(product=None)
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (credit_matrix, None)
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)
        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual('Product tidak ditemukan.', response.json()['errors'][0])

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_default_amount(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
    ):
        self.product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
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
        self.application.monthly_income = 5_000_000
        self.application.application_status_id = 420
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(200, response.status_code, response.content)
        default_amount = response.json()['data']['default_amount']
        min_amount = response.json()['data']['min_amount']
        max_amount = response.json()['data']['max_amount']

        self.assertTrue(default_amount <= max_amount)
        self.assertTrue(default_amount >= min_amount)
        # default value is 2 million
        self.assertTrue(default_amount == 2_000_000)

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_default_amount_with_fs_config(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
    ):
        dbr_amount = 3_000_000
        loan_amount_default = 200_000
        parameters = {
            "whitelist": {"is_active": False, "customer_ids": []},
            "dbr_loan_amount_default": dbr_amount,
            "min_amount_threshold": loan_amount_default,
        }
        self.loan_amount_config.parameters = parameters
        self.loan_amount_config.save()

        self.product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
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
        self.application.monthly_income = 5_000_000
        self.application.application_status_id = 420
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(200, response.status_code, response.content)
        default_amount = response.json()['data']['default_amount']
        min_amount_threshold = response.json()['data']['min_amount_threshold']

        self.assertTrue(default_amount == dbr_amount)
        self.assertTrue(min_amount_threshold == loan_amount_default)

        # check Whitelist
        # the customer doesn't exist in whitelist
        parameters['whitelist']['is_active'] = True
        self.loan_amount_config.parameters = parameters
        self.loan_amount_config.save()

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)
        default_amount = response.json()['data']['default_amount']
        min_amount_threshold = response.json()['data']['min_amount_threshold']

        self.assertTrue(default_amount == LoanJuloOneConstant.DBR_LOAN_AMOUNT_DEFAULT)
        self.assertTrue(min_amount_threshold == LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD)

        # the customer exists in whitelist
        parameters['whitelist']['customer_ids'] = [self.account.customer_id]
        self.loan_amount_config.parameters = parameters
        self.loan_amount_config.save()

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)
        default_amount = response.json()['data']['default_amount']
        min_amount_threshold = response.json()['data']['min_amount_threshold']

        self.assertTrue(default_amount == dbr_amount)
        self.assertTrue(min_amount_threshold == loan_amount_default)

    def test_range_loan_amount_prevent_inactive_account_access(self):
        self.application.monthly_income = None
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        self.account.status_id = AccountConstant.STATUS_CODE.inactive
        self.account.save()
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual(response.json()['errors'][0], "Account tidak ditemukan")

    @patch('juloserver.loan.services.views_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_minimum_value(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_first_date,
    ):
        self.product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=6,
            min_duration=3,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        self.application.monthly_income = 5_000_000
        self.application.application_status_id = 420
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        first_payment_date = date.today() + relativedelta(days=20)
        mock_get_first_date.return_value = first_payment_date
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today(),
            due_amount=3_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=3_500_000,
        )
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(200, response.status_code, response.content)
        default_amount = response.json()['data']['default_amount']
        min_amount = response.json()['data']['min_amount']
        max_amount = response.json()['data']['max_amount']

        self.assertTrue(default_amount <= max_amount)
        self.assertTrue(default_amount == min_amount)

    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_minimum_value_healthcare(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
    ):
        self.dbr_fs.is_active = False
        self.dbr_fs.save()
        self.product_lookup = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.07)
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=6,
            min_duration=3,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        self.application.application_status_id = 190
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        TransactionMethodFactory(
            id=TransactionMethodCode.HEALTHCARE.code, method=TransactionMethodCode.HEALTHCARE.name
        )
        data = {'transaction_type_code': TransactionMethodCode.HEALTHCARE.code}
        AccountPropertyFactory(account=self.account)

        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)
        self.assertEqual(200, response.status_code, response.content)
        default_amount = response.json()['data']['default_amount']
        min_amount = response.json()['data']['min_amount']
        max_amount = response.json()['data']['max_amount']

        self.assertTrue(default_amount <= max_amount)
        self.assertTrue(min_amount == LoanJuloOneConstant.MIN_LOAN_AMOUNT_HEALTHCARE)

    @patch('juloserver.loan.services.views_related.MercuryCustomerService')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_mercury_service(
        self,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_mercury_service,
    ):
        # set up
        self.dbr_fs.is_active = False
        self.dbr_fs.save()

        provision_fee = 0.05
        cm_max_duration = 6
        cm_min_duration = 3
        self.product_lookup = ProductLookupFactory(
            origination_fee_pct=provision_fee, interest_rate=0.07
        )
        credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=cm_max_duration,
            min_duration=cm_min_duration,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )
        self.application.application_status_id = 190
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        AccountPropertyFactory(account=self.account)
        mock_mercury_object = MagicMock()
        mock_mercury_service.return_value = mock_mercury_object

        # hit with method 1
        new_available_limit = 2_000_000
        mock_mercury_object.is_method_name_valid.return_value = True
        mock_mercury_object.is_customer_eligible.return_value = True
        mock_mercury_object.get_mercury_available_limit.return_value = True, new_available_limit
        data = {
            'transaction_type_code': TransactionMethodCode.SELF.code,
            'self_bank_account': "true",
        }
        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)
        self.assertEqual(200, response.status_code)

        # assert
        mock_mercury_object.is_method_name_valid.assert_called_once_with(
            method_name=TransactionMethodCode.SELF.name,
        )
        mock_mercury_object.is_customer_eligible.assert_called_once()
        mock_mercury_object.get_mercury_available_limit.assert_called_once_with(
            account_limit=self.account_limit,
            min_duration=cm_min_duration,
            max_duration=cm_max_duration,
            transaction_type=TransactionMethodCode.SELF.name,
        )
        json_data = response.json()
        self.assertEqual(json_data['data']['is_show_information_icon'], True)
        self.assertEqual(json_data['data']['max_amount'], new_available_limit)
        self.assertEqual(
            json_data['data']['min_amount'], LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        )
        self.assertEqual(
            json_data['data']['min_amount_threshold'], LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        )

        # hit with method 2
        new_available_limit = 2_000_000
        mock_mercury_object.is_method_name_valid.reset_mock()
        mock_mercury_object.is_customer_eligible.reset_mock()
        mock_mercury_object.get_mercury_available_limit.reset_mock()

        mock_mercury_object.is_method_name_valid.return_value = True
        mock_mercury_object.is_customer_eligible.return_value = True
        mock_mercury_object.get_mercury_available_limit.return_value = False, new_available_limit
        data = {
            'transaction_type_code': TransactionMethodCode.OTHER.code,
            'self_bank_account': "false",
        }
        url = '/api/loan/v3/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)
        self.assertEqual(200, response.status_code)

        # assert
        mock_mercury_object.is_method_name_valid.assert_called_once_with(
            method_name=TransactionMethodCode.OTHER.name,
        )
        mock_mercury_object.is_customer_eligible.assert_called_once()
        mock_mercury_object.get_mercury_available_limit.assert_called_once_with(
            account_limit=self.account_limit,
            min_duration=cm_min_duration,
            max_duration=cm_max_duration,
            transaction_type=TransactionMethodCode.OTHER.name,
        )
        json_data = response.json()
        self.assertEqual(json_data['data']['is_show_information_icon'], False)
        self.assertEqual(
            json_data['data']['max_amount'], int(new_available_limit * (1 - provision_fee))
        )
        self.assertEqual(
            json_data['data']['min_amount'], LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        )
        self.assertEqual(
            json_data['data']['min_amount_threshold'], LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        )


class TestAYCEWalletTransction(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.user.set_password('123456')
        self.user.save()
        self.pin = CustomerPinFactory(user=self.user)
        amount = 2000000
        self.account_limit.available_limit = amount + 1000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.user_partner = AuthUserFactory()
        self.lender = LenderFactory(
            lender_name='jtp', lender_status='active', user=self.user_partner
        )
        self.lender_ballance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=999999999
        )
        self.partner = PartnerFactory(user=self.user_partner, name="JULO")
        self.product_line = self.application.product_line
        self.product_profile = ProductProfileFactory(code='123')
        LenderDisburseCounterFactory(lender=self.lender)
        params = {
            "is_active_prod_testing": False,
            'prod_testing_customer_ids': [],
        }
        FeatureSettingFactory(
            feature_name=PaymentPointFeatureName.SEPULSA_AYOCONNECT_EWALLET_SWITCH,
            is_active=True,
            category='payment_point',
            description='Configurations for switching sepulsa and ayoconnect ewallet',
            parameters=params,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            id=10,
            category=BankAccountCategoryConst.EWALLET,
            display_label=BankAccountCategoryConst.EWALLET.title(),
            parent_category_id=10,
        )
        self.list_new_banks = {
            "ShopeePay": "APIDIDJ1",
            "OVO": "ACRIOVO1",
            "GoPay": "ACRIGPY1",
            "DANA": "DANAIDJ1",
        }
        list_created_banks = []
        for new_bank in self.list_new_banks:
            bank = BankFactory(
                bank_code=self.list_new_banks[new_bank],
                bank_name=new_bank,
                swift_bank_code=self.list_new_banks[new_bank],
                is_active=True,
                bank_name_frontend=new_bank,
            )
            list_created_banks.append(bank)

        payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="ayoconnect")
        for bank in list_created_banks:
            PaymentGatewayBankCode.objects.get_or_create(
                bank_id=bank.pk,
                is_active=True,
                swift_bank_code=bank.bank_code,
                payment_gateway_vendor_id=payment_gateway_vendor.pk,
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

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_ayc_ewallet_transaction(
        self, mock_is_product_locked, mock_calculate_loan_amount, mock_concurrency
    ):
        for bank in self.list_new_banks:
            sepulsa_product = SepulsaProductFactory(
                is_active=True,
                type=SepulsaProductType.EWALLET,
                category=bank,
                customer_price_regular=22000,
            )
            mock_is_product_locked.return_value = False
            mock_concurrency.return_value = None, None
            mock_calculate_loan_amount.return_value = (
                123123,
                self.credit_matrix,
                self.credit_matrix_product_line,
            )
            bank_name = bank
            ayc_product = AYCProduct.objects.create(
                product_id=1,
                product_name='test',
                product_nominal=100_000,
                type=SepulsaProductType.EWALLET,
                category=bank,
                is_active=True,
                partner_price=100_000,
                customer_price=100_000,
                customer_price_regular=110_000,
                sepulsa_product_id=sepulsa_product.pk,
            )
            phone_number = "081232141231"
            data = {
                'loan_amount_request': ayc_product.customer_price_regular,
                'self_bank_account': False,
                'transaction_type_code': TransactionMethodCode.DOMPET_DIGITAL.code,
                'pin': '123456',
                'loan_duration': 3,
                'account_id': self.account.id,
                'android_id': "65e67657568",
                'mobile_number': phone_number,
                'latitude': -6.175499,
                'longitude': 106.820512,
                'gcm_reg_id': "574534867",
                'loan_purpose': 'testing',
                'is_payment_point': True,
                'payment_point_product_id': sepulsa_product.pk,
            }

            # 1. First time
            response = self.client.post('/api/loan/v3/loan', data=data)
            self.assertEqual(response.status_code, HTTP_200_OK)
            loan_id = response.json()['data']['loan_id']
            loan_1 = Loan.objects.get(pk=loan_id)
            ayc_wallet_transaction = AYCEWalletTransaction.objects.filter(
                loan_id=loan_id, customer_id=self.customer.pk, ayc_product=ayc_product
            ).first()
            bank_account_destination = loan_1.bank_account_destination
            name_bank_validation = bank_account_destination.name_bank_validation
            bank_account_category = bank_account_destination.bank_account_category
            bank = Bank.objects.filter(bank_name=bank_name).last()

            # don't create Seuplsa Transaction
            assert SepulsaTransaction.objects.filter(loan_id=loan_id).exists() == False
            # create AYCEWalletTransaction
            assert ayc_wallet_transaction != None
            assert ayc_wallet_transaction.partner_price == ayc_product.partner_price
            assert (
                ayc_wallet_transaction.customer_price_regular == ayc_product.customer_price_regular
            )
            assert ayc_wallet_transaction.customer_price == ayc_product.customer_price
            assert bank_account_destination.account_number == phone_number
            assert bank_account_destination.customer_id == self.customer.pk

            # Check NameBankValidation
            assert name_bank_validation.validation_status == NameBankValidationStatus.SUCCESS
            assert name_bank_validation.account_number == phone_number
            assert name_bank_validation.method == NameBankValidationVendors.XFERS
            assert name_bank_validation.mobile_phone == self.customer.phone
            assert name_bank_validation.name_in_bank == self.customer.fullname
            assert name_bank_validation.bank_code == bank.bank_code

            assert self.bank_account_category.pk == bank_account_category.pk
            assert bank_account_destination.bank_id == bank.pk
            loan_1.loan_status_id = 220
            loan_1.save()

        # 2. Create in the second time
        # don't create BankAccountDestination
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan_id = response.json()['data']['loan_id']
        loan_2 = Loan.objects.get(pk=loan_id)

        # don't create Seuplsa Transaction
        assert SepulsaTransaction.objects.filter(loan_id=loan_id).exists() == False
        assert (
            AYCEWalletTransaction.objects.filter(
                customer_id=self.customer.pk, ayc_product=ayc_product
            ).count()
            == 2
        )
        assert loan_1.bank_account_destination_id == loan_2.bank_account_destination_id
        assert (
            loan_1.bank_account_destination.name_bank_validation_id
            == loan_2.bank_account_destination.name_bank_validation_id
        )


class TestXfersEWalletTransction(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.user.set_password('123456')
        self.user.save()
        self.pin = CustomerPinFactory(user=self.user)
        amount = 2000000
        self.account_limit.available_limit = amount + 1000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.user_partner = AuthUserFactory()
        self.lender = LenderFactory(
            lender_name='jtp', lender_status='active', user=self.user_partner
        )
        self.lender_ballance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=999999999
        )
        self.partner = PartnerFactory(user=self.user_partner, name="JULO")
        self.product_line = self.application.product_line
        self.product_profile = ProductProfileFactory(code='123')
        LenderDisburseCounterFactory(lender=self.lender)
        params = {
            "is_whitelist_active": False,
            'whitelist_customer_ids': [],
        }
        FeatureSettingFactory(
            feature_name=PaymentPointFeatureName.SEPULSA_XFERS_EWALLET_SWITCH,
            is_active=True,
            category='payment_point',
            description='Configurations for switching sepulsa and ayoconnect ewallet',
            parameters=params,
        )
        self.bank_account_category = BankAccountCategoryFactory(
            id=10,
            category=BankAccountCategoryConst.EWALLET,
            display_label=BankAccountCategoryConst.EWALLET.title(),
            parent_category_id=10,
        )
        bank = BankFactory(
            bank_code="013",
            bank_name="BANK PERMATA, Tbk",
            xfers_bank_code="PERMATA",
            is_active=True,
            bank_name_frontend="Permata",
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

    @patch('juloserver.loan.views.views_api_v3.validate_loan_concurrency')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_xfers_ewallet_transaction(
        self, mock_is_product_locked, mock_calculate_loan_amount, mock_concurrency
    ):
        sepulsa_product = SepulsaProductFactory(
            is_active=True,
            type=SepulsaProductType.EWALLET,
            category=SepulsaProductCategory.DANA,
            customer_price_regular=22000,
        )
        mock_is_product_locked.return_value = False
        mock_concurrency.return_value = None, None
        mock_calculate_loan_amount.return_value = (
            123123,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        xfers_product = XfersProduct.objects.create(
            product_id=1,
            product_name='test',
            product_nominal=100_000,
            type=SepulsaProductType.EWALLET,
            category=SepulsaProductCategory.DANA,
            is_active=True,
            partner_price=100_000,
            customer_price=100_000,
            customer_price_regular=110_000,
            sepulsa_product_id=sepulsa_product.pk,
        )
        phone_number = "081232141231"
        data = {
            'loan_amount_request': xfers_product.customer_price_regular,
            'self_bank_account': False,
            'transaction_type_code': TransactionMethodCode.DOMPET_DIGITAL.code,
            'pin': '123456',
            'loan_duration': 3,
            'account_id': self.account.id,
            'android_id': "65e67657568",
            'mobile_number': phone_number,
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            'loan_purpose': 'testing',
            'is_payment_point': True,
            'payment_point_product_id': sepulsa_product.pk,
        }

        # 1. First time
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        loan_id = response.json()['data']['loan_id']
        loan_1 = Loan.objects.get(pk=loan_id)
        xfers_wallet_transaction = XfersEWalletTransaction.objects.filter(
            loan_id=loan_id, customer_id=self.customer.pk, xfers_product=xfers_product
        ).first()
        bank_account_destination = loan_1.bank_account_destination

        # don't create Seuplsa Transaction
        assert SepulsaTransaction.objects.filter(loan_id=loan_id).exists() == False
        assert AYCEWalletTransaction.objects.filter(loan_id=loan_id).exists() == False
        # create XfersEWalletTransaction
        assert xfers_wallet_transaction != None
        assert xfers_wallet_transaction.partner_price == xfers_product.partner_price
        assert (
            xfers_wallet_transaction.customer_price_regular == xfers_product.customer_price_regular
        )
        assert xfers_wallet_transaction.customer_price == xfers_product.customer_price
        assert bank_account_destination == None

        # 2. Create in the second time
        # don't create BankAccountDestination
        loan_1.loan_status_id = 220
        loan_1.save()
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        loan_id = response.json()['data']['loan_id']

        # don't create Seuplsa Transaction
        assert SepulsaTransaction.objects.filter(loan_id=loan_id).exists() == False
        assert (
            XfersEWalletTransaction.objects.filter(
                customer_id=self.customer.pk, xfers_product=xfers_product
            ).count()
            == 2
        )


class TestLoanAgreementDetailViewV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line, email='test_email@gmail.com'
        )
        self.application.dob = datetime(1994, 6, 10)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.account_limit = AccountLimitFactory(
            latest_credit_score=self.credit_score,
            account=self.account,
        )
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=None,
            loan_xid=1000023456,
        )
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        parameters_digital_signature = {'digital_signature_loan_amount_threshold': 500000}
        parameters_voice_record = {'voice_recording_loan_amount_threshold': 500000}
        self.feature_voice = FeatureSettingFactory(
            feature_name=FeatureNameConst.VOICE_RECORDING_THRESHOLD,
            parameters=parameters_voice_record,
        )
        self.feature_signature = FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGITAL_SIGNATURE_THRESHOLD,
            parameters=parameters_digital_signature,
        )
        self.application.account = self.account
        self.application.save()
        self.loan.loan_amount = 100000

    def test_loan_details(self):
        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(self.loan.loan_xid))
        self.assertIs(res.status_code, 200)

    def test_loan_details_fintech_name(self):
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan=self.loan,
        )

        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()

        res = self.client.get('/api/loan/v3/agreement/loan/1000023456/')
        self.assertEqual(res.status_code, 200)

        body = res.json()
        self.assertIsNot(body['data']["loan"]["fintech_name"], None)

    def test_loan_details_juloshop(self):
        productName = 'yaiba'
        juloshop_transaction = JuloShopTransactionFactory(
            loan=self.loan,
            checkout_info={
                "items": [
                    {"productName": productName},
                ],
            },
        )

        res = self.client.get('/api/loan/v3/agreement/loan/1000023456/')
        self.assertEqual(res.status_code, 200)

        body = res.json()
        self.assertEqual(body['data']["loan"]["product_name"], productName)
        self.assertEqual(body['data']["loan"]["bank_name"], settings.JULOSHOP_BANK_NAME)
        self.assertEqual(body['data']["loan"]["bank_account_name"], settings.JULOSHOP_ACCOUNT_NAME)
        self.assertEqual(
            body['data']["loan"]["bank_account_number"], settings.JULOSHOP_BANK_ACCOUNT_NUMBER
        )

    def test_loan_details_due_date(self):
        date_str = '2023-02-25'

        # create first payment
        PaymentFactory(loan=self.loan, due_date=datetime.strptime(date_str, "%Y-%m-%d"))

        expected_date = '25 Feb 2023'
        res = self.client.get('/api/loan/v3/agreement/loan/1000023456/')
        self.assertEqual(res.status_code, 200)

        body = res.json()
        self.assertIsNot(body['data']["loan"]["due_date"], expected_date)

    def test_authenticate_fail(self):
        fake_id = 123021470970234
        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(fake_id))
        self.assertEqual(res.status_code, 400)

        strange_user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + strange_user.auth_expiry_token.key)

        # other users get 403
        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(self.loan.loan_xid))
        self.assertEqual(res.status_code, 403)

    def test_loan_agreement_ok(self):
        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(self.loan.loan_xid))
        json_response = res.json()
        self.assertEqual(res.status_code, 200)

        # result
        main_title = "Lihat Dokumen SKRTP dan RIPLAY"
        default_img = (
            settings.STATIC_ALICLOUD_BUCKET_URL + 'loan_agreement/default_document_logo.png'
        )
        expected_result = {
            "title": main_title,
            "types": [
                {
                    "type": LoanAgreementType.TYPE_SKRTP,
                    "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                    "text": LoanAgreementType.TEXT_SKRTP,
                    "image": default_img,
                },
                {
                    "type": LoanAgreementType.TYPE_RIPLAY,
                    "displayed_title": LoanAgreementType.TYPE_RIPLAY.upper(),
                    "text": LoanAgreementType.TEXT_RIPLAY,
                    "image": default_img,
                },
            ],
        }
        self.assertEqual(
            json_response['data']['loan_agreement'],
            expected_result,
        )

    def test_loan_tax_fee(self):
        LoanTransactionDetailFactory(
            loan_id=self.loan.id,
            detail={
                'tax_fee': 77000
            }
        )

        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(self.loan.loan_xid))
        json_response = res.json()

        self.assertEqual(json_response['data']['loan']['tax_fee'], 77000)

    def test_loan_admin_fee(self):
        LoanTransactionDetailFactory(
            loan_id=self.loan.id,
            detail={
                'admin_fee': 1234
            }
        )

        res = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(self.loan.loan_xid))
        json_response = res.json()

        self.assertEqual(json_response['data']['loan']['admin_fee'], 1234)


class TestTransactionDetailV3(TestCase):
    """
    Replicate from test_api_v2::TestTransactionDetail
    Testing data->loan
    """

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)

    def test_get_transaction_detail_for_education(self):
        disbursement = DisbursementFactory(reference_id='contract_0b797cb8f5984e0e89eb802a009fa5f4')
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=220),
            disbursement_id=disbursement.id,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.EDUCATION.code, method=TransactionMethodCode.EDUCATION
            ),
        )
        DocumentFactory(document_type='education_invoice', document_source=loan.id)
        school = SchoolFactory()
        student_register = StudentRegisterFactory(
            account=self.account,
            school=school,
            bank_account_destination=BankAccountDestinationFactory(bank=BankFactory()),
            student_fullname='This is full name',
            note='123456789',
        )
        LoanStudentRegisterFactory(loan=loan, student_register=student_register)

        response = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, 200)

        student_tuition_info = response.data['data']['loan']['student_tuition']
        self.assertEqual(student_tuition_info['bank']['reference_number'], '079785984089')
        self.assertEqual(student_tuition_info['school']['name'], school.name)
        self.assertEqual(student_tuition_info['name'], student_register.student_fullname)
        self.assertEqual(student_tuition_info['note'], student_register.note)
        self.assertIsNotNone(student_tuition_info['invoice_pdf_link'])
        self.assertIn('category_product_name', response.data['data']['loan'])

        # test bank_reference_number is null when loan status < 220
        loan.loan_status = StatusLookupFactory(status_code=212)
        loan.save()
        response = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data']['loan']['student_tuition']['bank']['reference_number'], None
        )
        loan = response.json()['data']['loan']
        assert loan['crossed_installment_amount'] != None
        assert loan['crossed_loan_disbursement_amount'] != None
        assert loan['crossed_interest_rate_monthly'] != None

    def test_get_transaction_detail_for_healthcare(self):
        disbursement = DisbursementFactory(reference_id='contract_0b123cb4f5678ee9eb100a109fa5f4')
        healthcare_user = HealthcareUserFactory(account=self.account)
        bank_account_destination = healthcare_user.bank_account_destination
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=220),
            disbursement_id=disbursement.id,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.HEALTHCARE.code, method=TransactionMethodCode.HEALTHCARE
            ),
            bank_account_destination=bank_account_destination,
        )
        AdditionalLoanInformation.objects.create(
            content_type=ContentType.objects.get_for_model(HealthcareUser),
            object_id=healthcare_user.pk,
            loan=loan,
        )
        DocumentFactory(document_type='healthcare_invoice', document_source=loan.id)

        response = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, 200)
        healthcare_user_info = response.data['data']['loan']['healthcare_user']
        self.assertEqual(
            healthcare_user_info['healthcare_platform_name'],
            healthcare_user.healthcare_platform.name,
        )
        self.assertEqual(healthcare_user_info['healthcare_user_fullname'], healthcare_user.fullname)
        self.assertEqual(healthcare_user_info['bank_reference_number'], '012345678910')
        self.assertIsNotNone(healthcare_user_info['invoice_pdf_link'])
        self.assertEqual(
            response.data['data']['loan']['bank']['account_name'],
            bank_account_destination.get_name_from_bank_validation,
        )
        self.assertEqual(
            response.data['data']['loan']['bank']['account_number'],
            bank_account_destination.account_number,
        )

        # test bank_reference_number is null when loan status < 220
        loan.loan_status = StatusLookupFactory(status_code=212)
        loan.save()
        response = self.client.get('/api/loan/v3/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, 200)
        healthcare_user_info = response.data['data']['loan']['healthcare_user']
        self.assertIsNone(healthcare_user_info['bank_reference_number'])
        self.assertIsNone(healthcare_user_info['invoice_pdf_link'])


class TestLoanDetailsAndTemplateDocumentType(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line, email='test_email@gmail.com'
        )
        self.application.dob = datetime(1994, 6, 10)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            cycle_day=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.user_partner = AuthUserFactory()
        self.lender = LenderFactory(
            lender_name='jtp', lender_status='active', user=self.user_partner, company_name="Test"
        )
        TransactionMethod.objects.all().delete()
        transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER.name,
        )
        self.loan = LoanFactory(
            lender_id=self.lender.pk,
            customer=self.customer,
            account=self.account,
            transaction_method=transaction_method,
            product=ProductLookupFactory(),
            sphp_sent_ts=datetime(2024, 10, 10),
        )
        self.loan.loan_xid = 1000023456
        self.application.account = self.account
        self.application.save()
        self.loan.loan_amount = 1000000
        self.loan.save()

    def test_loan_content_with_document_type(self):
        with self.assertTemplateUsed('loan_agreement/julo_one_skrtp.html'):
            response = self.client.get(
                '/api/loan/v3/agreement/content/1000023456?document_type={}'.format(
                    LoanAgreementType.SKRTP
                )
            )
        self.assertEqual(response.status_code, 200)

        with self.assertTemplateUsed('loan_agreement/julo_one_riplay.html'):
            response = self.client.get(
                '/api/loan/v3/agreement/content/1000023456?document_type={}'.format(
                    LoanAgreementType.RIPLAY
                )
            )
        self.assertEqual(response.status_code, 200)

    def test_loan_content_unauthenticated(self):
        # loan_xid not exist
        response = self.client.get(
            '/api/loan/v3/agreement/content/1?document_type={}'.format(LoanAgreementType.RIPLAY)
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['errors'][0], "Loan XID:1 Not found")

        # document_type is None
        response = self.client.get('/api/loan/v3/agreement/content/1?document_type=test')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "Document type not found")

        # forbidden
        self.loan.customer.user_id = self.user_partner.pk
        self.loan.customer.save()
        response = self.client.get(
            '/api/loan/v3/agreement/content/1000023456?document_type={}'.format(
                LoanAgreementType.RIPLAY
            )
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['errors'][0][0], "User not allowed")


class TestDelayedDisbursementContentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)

        params = {
            "content": {
                "tnc": "<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>"
            },
            "condition": {
                "start_time": "09:00",
                "cut_off": "23:59",
                "cashback": 25000,
                "daily_limit": 0,
                "monthly_limit": 0,
                "min_loan_amount": 100000,
                "threshold_duration": 600,
                "list_transaction_method_code": [1],
            },
            "whitelist_last_digit": 3,
        }

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            is_active=True,
            category='loan',
            description='Feature Setting For Delay Disbursement',
            parameters=params,
        )

    @patch('django.utils.timezone.now')
    def test_delay_disbursement_content_active(self, mock_now):
        # 10:00 is between 09:00 and 23:59
        mock_now.return_value = datetime(2024, 10, 10, 10, 0, 0)
        expected_http_status = 200
        expected_body = {
            'success': True,
            'data': {
                'available_transaction_method': [1],
                'cashback': 25000,
                'is_active': True,
                'minimum_loan_amount': 100000,
                'threshold_duration': 600,
                'tnc': '<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>',
            },
            'errors': [],
        }

        response = self.client.get('/api/loan/v3/delayed-disbursement/content')

        self.assertTrue(mock_now.called)

        self.assertEqual(expected_http_status, response.status_code)
        self.assertEqual(expected_body, response.json())

    def test_delay_disbursement_content_not_active(self):
        expected_http_status = 200
        expected_body = {
            'success': True,
            'data': {
                'available_transaction_method': None,
                'cashback': None,
                'is_active': False,
                'minimum_loan_amount': None,
                'threshold_duration': None,
                'tnc': None,
            },
            'errors': [],
        }

        self.fs.is_active = False
        self.fs.save()

        response = self.client.get('/api/loan/v3/delayed-disbursement/content')

        self.assertEqual(expected_http_status, response.status_code)
        self.assertEqual(expected_body, response.json())

    @patch('juloserver.loan.views.views_api_v3.check_daily_monthly_limit')
    @patch('django.utils.timezone.now')
    def test_delay_disbursement_content_active_with_daily_limit(self, mock_now, mock_check_monthly_daily_limit):
        # 10:00 is between 09:00 and 23:59
        mock_now.return_value = datetime(2024, 10, 10, 10, 0, 0)
        mock_check_monthly_daily_limit.return_value = True

        params = {
            "content": {
                "tnc": "<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>"
            },
            "condition": {
                "start_time": "09:00",
                "cut_off": "23:59",
                "cashback": 25000,
                "daily_limit": 1,
                "monthly_limit": 1,
                "min_loan_amount": 100000,
                "threshold_duration": 600,
                "list_transaction_method_code": [1],
            },
            "whitelist_last_digit": 3,
        }
        self.fs.parameters = params
        self.fs.save()
        expected_http_status = 200
        expected_body = {
            'success': True,
            'data': {
                'available_transaction_method': [1],
                'cashback': 25000,
                'is_active': True,
                'minimum_loan_amount': 100000,
                'threshold_duration': 600,
                'tnc': '<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>',
            },
            'errors': [],
        }

        response = self.client.get('/api/loan/v3/delayed-disbursement/content')

        self.assertTrue(mock_now.called)

        self.assertEqual(expected_http_status, response.status_code)
        self.assertEqual(expected_body, response.json())

    @patch('juloserver.loan.views.views_api_v3.check_daily_monthly_limit')
    @patch('django.utils.timezone.now')
    def test_delay_disbursement_content_not_active_with_daily_limit(self, mock_now, mock_check_monthly_daily_limit):
        # 10:00 is between 09:00 and 23:59
        mock_now.return_value = datetime(2024, 10, 10, 10, 0, 0)
        mock_check_monthly_daily_limit.return_value = False
        params = {
            "content": {
                "tnc": "<p>Coba display tnc nya</p>\r\n\r\n<ul>\r\n\t<li>masuk</li>\r\n\t<li>keluar</li>\r\n</ul>"
            },
            "condition": {
                "start_time": "09:00",
                "cut_off": "23:59",
                "cashback": 25000,
                "daily_limit": 1,
                "monthly_limit": 1,
                "min_loan_amount": 100000,
                "threshold_duration": 600,
                "list_transaction_method_code": [1],
            },
            "whitelist_last_digit": 3,
        }
        self.fs.parameters = params
        self.fs.save()
        expected_http_status = 200
        expected_body = {
            'success': True,
            'data': {
                'available_transaction_method': None,
                'cashback': None,
                'is_active': False,
                'minimum_loan_amount': None,
                'threshold_duration': None,
                'tnc': None,
            },
            'errors': [],
        }

        response = self.client.get('/api/loan/v3/delayed-disbursement/content')

        self.assertTrue(mock_now.called)

        self.assertEqual(expected_http_status, response.status_code)
        self.assertEqual(expected_body, response.json())


class TestSubmitLoanWithPromoCode(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.user.set_password('123456')
        self.user.save()
        self.pin = CustomerPinFactory(user=self.user)
        self.ecommerce_method = TransactionMethodFactory(
            method=TransactionMethodCode.E_COMMERCE,
            id=8,
        )
        amount = 2000000
        self.account_limit.available_limit = amount + 1000
        self.account_limit.save()
        self.account_limit.refresh_from_db()
        self.juloshop_transaction = JuloShopTransactionFactory(
            status=JuloShopTransactionStatus.DRAFT, customer=self.customer
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.ECOMMERCE,
            parent_category_id=1,
        )
        self.bank_account_destination = BankAccountDestinationFactory()
        self.user_partner = AuthUserFactory()
        self.lender = LenderFactory(
            lender_name='jtp', lender_status='active', user=self.user_partner
        )
        self.lender_ballance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=999999999
        )
        self.partner = PartnerFactory(user=self.user_partner, name="JULO")
        self.product_line = self.application.product_line
        self.product_profile = ProductProfileFactory(code='123')
        self.product_line.product_profile = self.product_profile
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category="followthemoney",
            is_active=True,
            parameters={'lender_name': 'jtp'},
        )
        LenderDisburseCounterFactory(lender=self.lender)
        self.daily_fee_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={"daily_max_fee": 0.4},
            is_active=True,
            category="credit_matrix",
            description="Test",
        )

        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="You bring me more meth, that's brilliant!",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={
                'amount': 20000,
            },
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            promo_code="You've got one part of that wrong...",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=5,
        )
        self.criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                'limit_per_promo_code': 6,
                'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            self.criteria.id,
        ]
        self.promo_code.save()

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    def test_submit_loan_with_promo_code(
            self, mock_calculate_loan_amount, mock_is_product_locked
    ):
        mock_is_product_locked.return_value = False
        TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": healthcare_user.pk,
            "promo_code": self.promo_code.code,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        loan_id = response.json()['data']['loan_id']
        promo_usage = PromoCodeUsage.objects.get(loan_id=loan_id)
        self.assertIsNotNone(promo_usage)
        self.assertEqual(promo_usage.version, PromoCodeVersion.V2)
        loan = Loan.objects.get(id=loan_id)
        self.assertEqual(loan.loan_purpose, LoanPurposeConst.BIAYA_KESEHATAN)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    def test_submit_loan_with_invalid_promo_code(
            self, mock_calculate_loan_amount, mock_is_product_locked
    ):
        mock_is_product_locked.return_value = False
        TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": healthcare_user.pk,
            "promo_code": 'wrong promo code',
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'], ['Invalid promo code'])

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.calculate_loan_amount')
    @patch('juloserver.promo.services_v3.check_failed_criteria_v2')
    def test_submit_loan_with_provision_discount(
            self, mock_check_failed_criteria_v2, mock_calculate_loan_amount, mock_is_product_locked
    ):
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        mock_is_product_locked.return_value = False
        mock_check_failed_criteria_v2.return_value = False

        # Setup promo code
        promo_code_benefit = PromoCodeBenefitFactory(
            type = PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
            value = {"amount": 10000}
        )
        promo_code = PromoCodeFactory(
            promo_code_benefit=promo_code_benefit,
            type = PromoCodeTypeConst.LOAN,
        )
        provision_fee = 0.05
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        TransactionMethodFactory(
            method=TransactionMethodCode.HEALTHCARE.name, id=TransactionMethodCode.HEALTHCARE.code
        )
        bank_account_category = BankAccountCategoryFactory(
            category='healthcare', display_label='Pribadi', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        healthcare_user = HealthcareUserFactory(
            account=self.account, bank_account_destination=bank_account_destination
        )
        mock_calculate_loan_amount.return_value = (
            300000,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        data = {
            "transaction_type_code": TransactionMethodCode.HEALTHCARE.code,
            "loan_amount_request": 300000,
            "account_id": self.account.id,
            "self_bank_account": False,
            "is_payment_point": False,
            "loan_duration": 2,
            "pin": "123456",
            "bank_account_destination_id": bank_account_destination.id,
            "loan_purpose": "",
            "is_suspicious_ip": False,
            'android_id': "65e67657568",
            'latitude': -6.175499,
            'longitude': 106.820512,
            'gcm_reg_id': "574534867",
            "manufacturer": "SS",
            "model": "14",
            "healthcare_user_id": healthcare_user.pk,
            "promo_code": promo_code.code,
        }
        response = self.client.post('/api/loan/v3/loan', data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        loan_id = response.json()['data']['loan_id']
        promo_usage = PromoCodeUsage.objects.get(loan_id=loan_id)
        self.assertIsNotNone(promo_usage)
        self.assertEqual(promo_usage.version, PromoCodeVersion.V2)
        loan = Loan.objects.get(id=loan_id)
        self.assertEqual(loan.loan_purpose, LoanPurposeConst.BIAYA_KESEHATAN)
