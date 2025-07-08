import pytz
from datetime import datetime, date, timedelta
from unittest.mock import patch, call
import pytest

from django.db.models import F
from django.contrib.auth.models import Group
from django.test import TestCase
from factory import Iterator
from rest_framework.test import APITestCase, APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit, AccountTransaction
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory,
    AccountLimitFactory,
    AccountTransactionFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    BalconLimitIncentiveConst,
    FeatureNameConst,
)
from juloserver.balance_consolidation.services import (
    ConsolidationVerificationStatusService,
    populate_fdc_data,
    process_approve_balance_consolidation,
    get_downgrade_amount_balcon_punishments,
    apply_downgrade_limit_for_balcon_punishments,
    get_invalid_loan_from_other_fintech,
    get_and_validate_fdc_data_for_balcon_punishments,
    get_and_save_customer_latest_fdc_data,
    reverse_all_payment_paid_interest,
)
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    FintechFactory,
)
from juloserver.cfs.tests.factories import AgentFactory, ImageFactory
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Payment, PaymentEvent
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    BankFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    ProductLookupFactory,
    PaymentEventFactory,
    CurrentCreditMatrixFactory, ApplicationJ1Factory, LoanFactory,
)
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.balance_consolidation.models import BalanceConsolidationDelinquentFDCChecking
from juloserver.moengage.services.use_cases import send_event_moengage_for_balcon_punishment
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.models import MoengageUpload



PACKAGE_NAME = 'juloserver.balance_consolidation.services'

class TestPopulateFDC(APITestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        _ = FDCInquiryFactory(application_id=self.application.id, inquiry_status='pending')
        self.inquiry_2 = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=False,
            dpd_terakhir=1,
            status_pinjaman='Outstanding',
        )

    def test_populate_fdc_data(self):
        context = {}
        populate_fdc_data(self.application, context)
        fdc_inquiry_loans = context['latest_fdc_inquiry_loans']
        valid_fdc_inquiry_loan = fdc_inquiry_loans[0]
        self.assertEqual(self.inquiry_2.id, valid_fdc_inquiry_loan.fdc_inquiry_id)
        self.assertEqual(self.inquiry_loan.id, valid_fdc_inquiry_loan.id)


class TestUpdateBalanceConsolidationVerification(APITestCase):
    def setUp(self):
        self.client = APIClient()
        group = Group(name="bo_data_verifier")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.active_status_code = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active
        )
        self.active_in_grace = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active_in_grace
        )
        self.account = AccountFactory(customer=self.customer, status=self.active_status_code)
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        agent = AgentFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.bank = BankFactory(bank_name='BCA')
        self.bank_account_category = BankAccountCategoryFactory(
            category='balance_consolidation', display_label='balance_consolidation'
        )
        self.image = ImageFactory(image_source=0)
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, loan_duration=3, signature_image=self.image
        )
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
        )
        self.image.update_safely(image_source=self.balance_consolidation.id)
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='08674734',
            attempt=0,
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=100000)
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.locked_by = agent
        self.balance_consolidation_verification.save()
        ProductLookupFactory(product_line=self.product_line, late_fee_pct=0.05),
        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(
            credit_matrix_type='julo1_entry_level',
            is_salaried=True,
            is_premium_area=True,
            min_threshold=0.75,
            max_threshold=1,
            transaction_type='balance_consolidation',
            parameter=None,
            product=self.product_lookup,
        )
        self.curent_credit_matrix = CurrentCreditMatrixFactory(
            credit_matrix=self.credit_matrix,
            transaction_type='balance_consolidation',
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000, product=self.product_line
        )

    @patch('juloserver.loan.services.loan_related.get_julo_one_is_proven')
    def test_process_approve_balance_consolidation(self, mock_is_proven, *args):
        mock_is_proven.return_value = True
        self.assertIsNone(self.balance_consolidation_verification.loan)
        account_limit = AccountLimit.objects.get(account=self.account)
        available_limit_before = account_limit.available_limit
        increase_infos = {"increase_amount": 1000000}
        process_approve_balance_consolidation(
            self.balance_consolidation_verification,
            increase_infos
        )
        loan = self.balance_consolidation_verification.loan
        account_limit.refresh_from_db()
        self.assertEqual(available_limit_before, account_limit.available_limit)
        accept_julo_sphp(loan, "JULO")
        self.assertEqual(loan.loan_status_id, 211)
        self.balance_consolidation.refresh_from_db()
        current_image_source = self.balance_consolidation.signature_image.image_source
        self.assertEqual(loan.id, current_image_source)
        self.assertEqual(
            loan.transaction_method.method, TransactionMethodCode.BALANCE_CONSOLIDATION.name
        )

    @patch('juloserver.loan.services.loan_related.get_julo_one_is_proven')
    def test_process_approve_balance_consolidation(self, mock_is_proven, *args):
        mock_is_proven.return_value = True


class TestLoanTransactionDetailBalanceConsolidation(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            fe_display_name='Balance Consolidation'
        )
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
        )
        self.fintech = FintechFactory()
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, bank_name='BANK MANDIRI (PERSERO), Tbk'
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan=self.loan
        )

    def test_transaction_detail(self):
        transaction_detail = self.loan.transaction_detail
        self.assertEqual(
            transaction_detail,
            'Transaction method: Balance Consolidation,<br>Fintech: Kredivo,<br>Bank name: '
            'BANK MANDIRI (PERSERO), Tbk,<br>Bank account no: 08321321321321'
        )


class TestConsolidationVerificationStatusService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        self.account_limit = AccountLimitFactory(
            account=self.account, available_limit=100000, set_limit=100000
        )

        self.image = ImageFactory(image_source=0)
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, loan_duration=3, signature_image=self.image
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='08674734',
            attempt=0,
        )
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.locked_by = AgentFactory(user=self.user)
        self.balance_consolidation_verification.save()

        self.fs = FeatureSettingFactory(
            feature_name=BalconLimitIncentiveConst.LIMIT_INCENTIVE_FS_NAME,
            category='balance_consolidation',
            is_active=True,
            parameters={
                'max_limit_incentive': 5_500_000,
                'min_set_limit': 1_000_000,
                'multiplier': 0.5,
                'bonus_incentive': 500_000,
            }
        )

    def test_check_limit_incentive_fail_min_set_limit(self):
        self.account_limit.update_safely(set_limit=100_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )

        self.assertFalse(consolidation_service.check_limit_incentive())

    def test_check_limit_incentive_fail_over_loan_limit_req(self):
        self.account_limit.update_safely(set_limit=5_000_000, available_limit=5_000_000)
        self.balance_consolidation.update_safely(loan_outstanding_amount=7_500_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertFalse(consolidation_service.check_limit_incentive())

        # for max_limit_incentive
        self.account_limit.update_safely(set_limit=12_000_001, available_limit=12_000_001)
        self.balance_consolidation.update_safely(loan_outstanding_amount=18_000_002)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertFalse(consolidation_service.check_limit_incentive())

    def test_check_limit_incentive_fail_available_limit_not_enough(self):
        self.account_limit.update_safely(set_limit=5_000_000, available_limit=4_999_999)
        self.balance_consolidation.update_safely(loan_outstanding_amount=7_500_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertFalse(consolidation_service.check_limit_incentive())

        self.account_limit.update_safely(set_limit=12_000_001, available_limit=12_000_000)
        self.balance_consolidation.update_safely(loan_outstanding_amount=18_000_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertFalse(consolidation_service.check_limit_incentive())

    def test_check_limit_incentive_success(self):
        self.account_limit.update_safely(set_limit=5_000_000, available_limit=5_000_000)
        self.balance_consolidation.update_safely(loan_outstanding_amount=7_500_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertTrue(consolidation_service.check_limit_incentive())

        self.account_limit.update_safely(set_limit=12_000_000, available_limit=12_000_000)
        self.balance_consolidation.update_safely(loan_outstanding_amount=17_500_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertTrue(consolidation_service.check_limit_incentive())

        self.account_limit.update_safely(set_limit=18_000_000, available_limit=18_000_000)
        self.balance_consolidation.update_safely(loan_outstanding_amount=18_000_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        self.assertTrue(consolidation_service.check_limit_incentive())

    def test_evaluate_increase_limit_incentive_amount(self):
        self.balance_consolidation.update_safely(loan_outstanding_amount=7_500_000)
        self.account_limit.update_safely(set_limit=5_000_000, available_limit=5_000_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        _, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {"increase_amount": 3_000_000, "bonus_incentive": 500_000}
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=17_500_001)
        self.account_limit.update_safely(set_limit=12_000_001, available_limit=12_000_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        _, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {"increase_amount": 6_000_000, "bonus_incentive": 500_000}
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=15_000_000)
        self.account_limit.update_safely(set_limit=12_000_000, available_limit=12_000_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        _, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {"increase_amount": 3_500_000, "bonus_incentive": 500_000}
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=15_000_000)
        self.account_limit.update_safely(set_limit=15_500_000, available_limit=15_490_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        _, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {"increase_amount": 500_000, "bonus_incentive": 500_000}
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=15_000_000)
        self.account_limit.update_safely(set_limit=15_500_000, available_limit=15_500_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        _, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {"increase_amount": 0}
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

    def test_evaluate_increase_limit_incentive_amount_with_config(self):
        self.fs.update_safely(
            parameters={
                'max_limit_incentive': 6_000_000,
                'min_set_limit': 1_500_000,
                'multiplier': 0.5,
                'bonus_incentive': 1_000_000,
            }
        )

        self.balance_consolidation.update_safely(loan_outstanding_amount=7_500_000)
        self.account_limit.update_safely(set_limit=5_000_000, available_limit=5_000_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        eligible, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {'increase_amount': 3500000, 'bonus_incentive': 1000000}
        self.assertTrue(eligible)
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=17_500_001)
        self.account_limit.update_safely(set_limit=12_000_001, available_limit=12_000_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        eligible, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {'increase_amount': 6_500_000, 'bonus_incentive': 1000000}
        self.assertTrue(eligible)
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=15_000_000)
        self.account_limit.update_safely(set_limit=15_500_000, available_limit=15_900_000)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        eligible, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {'increase_amount': 1_000_000, 'bonus_incentive': 1000000}
        self.assertTrue(eligible)
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)

        self.balance_consolidation.update_safely(loan_outstanding_amount=15_000_000)
        self.account_limit.update_safely(set_limit=15_500_000, available_limit=16_000_001)
        consolidation_service = ConsolidationVerificationStatusService(
            consolidation_verification=self.balance_consolidation_verification,
            account=self.account
        )
        eligible, limit_incentive_infos = \
            consolidation_service.evaluate_increase_limit_incentive_amount()
        expected_limit_incentive_infos = {'increase_amount': 0}
        self.assertTrue(eligible)
        self.assertEqual(limit_incentive_infos, expected_limit_incentive_infos)


class TestBalconPunishments(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LOC_APPROVED
            )
        )
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            fe_display_name='Balance Consolidation'
        )
        # Create balcon and according balcon loan
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
        )
        self.fintech = FintechFactory()
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, bank_name='BANK MANDIRI (PERSERO), Tbk'
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan=self.loan,
            account_limit_histories={
                "upgrade": {
                    "max_limit": 1193635,
                    "set_limit": 1193636,
                    "amount_changed": 3_000_000,
                    "available_limit": 1193637,
                    "bonus_incentive": 500_000,
                }
            }
        )
        # Create account limit
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )
        self.bonus_incentive = 500_000

    def test_trigger_downgrade_amount_for_balcon_punishment_1(self):
        self.account_limit.update_safely(max_limit=0, set_limit=0,
                                         available_limit = -100_000, used_limit=100_000)
        self.account_limit.save()
        downgrade_amount = get_downgrade_amount_balcon_punishments(self.account_limit.available_limit, self.bonus_incentive)
        self.assertEqual(downgrade_amount, 0)

        # Trigger outside function
        apply_downgrade_limit_for_balcon_punishments(self.customer.id, self.balance_consolidation_verification)
        self.account_limit.refresh_from_db()
        self.account_limit.available_limit = -100_000
        self.account_limit.set_limit = 0
        self.account_limit.max_limit = 0
        # Check account limit histories
        self.balance_consolidation_verification.refresh_from_db()
        account_limit_histories = self.balance_consolidation_verification.account_limit_histories
        expected_account_limit_histories = {
            "upgrade": {
                "max_limit": 1193635,
                "set_limit": 1193636,
                "amount_changed": 3_000_000,
                "available_limit": 1193637,
                "bonus_incentive": 500_000,
            }
        }
        self.assertEqual(account_limit_histories, expected_account_limit_histories)

    def test_trigger_downgrade_amount_for_balcon_punishment_2(self):
        self.account_limit.update_safely(max_limit=500_000, set_limit=500_000,
                                         available_limit = 300_000, used_limit=200_000)
        self.account_limit.save()
        downgrade_amount = get_downgrade_amount_balcon_punishments(self.account_limit.available_limit, self.bonus_incentive)
        self.assertEqual(downgrade_amount, 300_000)

        # Trigger outside function
        apply_downgrade_limit_for_balcon_punishments(self.customer.id, self.balance_consolidation_verification)
        self.account_limit.refresh_from_db()
        self.account_limit.available_limit = 0
        self.account_limit.set_limit = 200_000
        self.account_limit.max_limit = 200_000
        # Check account limit histories
        self.balance_consolidation_verification.refresh_from_db()
        account_limit_histories = self.balance_consolidation_verification.account_limit_histories
        expected_account_limit_histories = {
            "upgrade": {
                "max_limit": 1193635,
                "set_limit": 1193636,
                "amount_changed": 3_000_000,
                "available_limit": 1193637,
                "bonus_incentive": 500_000,
            },
            "punishments": {
                "deduct_bonus_incentive": 300_000,
            }
        }
        self.assertEqual(account_limit_histories, expected_account_limit_histories)

    def test_trigger_downgrade_amount_for_balcon_punishment_3(self):
        self.account_limit.update_safely(max_limit=2_000_000, set_limit=2_000_000,
                                         available_limit = 2_000_000, used_limit=0)
        self.account_limit.save()
        downgrade_amount = get_downgrade_amount_balcon_punishments(self.account_limit.available_limit, self.bonus_incentive)
        self.assertEqual(downgrade_amount, 500_000)

        # Trigger outside function
        apply_downgrade_limit_for_balcon_punishments(self.customer.id, self.balance_consolidation_verification)
        self.account_limit.refresh_from_db()
        self.account_limit.available_limit = 1_500_000
        self.account_limit.set_limit = 1_500_000
        self.account_limit.max_limit = 1_500_000
        # Check account limit histories
        self.balance_consolidation_verification.refresh_from_db()
        account_limit_histories = self.balance_consolidation_verification.account_limit_histories
        expected_account_limit_histories = {
            "upgrade": {
                "max_limit": 1193635,
                "set_limit": 1193636,
                "amount_changed": 3_000_000,
                "available_limit": 1193637,
                "bonus_incentive": 500_000,
            },
            "punishments": {
                "deduct_bonus_incentive": 500_000,
            }
        }
        self.assertEqual(account_limit_histories, expected_account_limit_histories)


class TestBalanceConsolidationFDCCheckingServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LOC_APPROVED
            )
        )
        self.fintech = FintechFactory(is_active=True)
        self.balcon = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(
                status_code=LoanStatusCodes.CURRENT
            ),
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
                method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            ),
        )
        self.balcon_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balcon,
            loan=self.loan,
            validation_status=BalanceConsolidationStatus.DISBURSED
        )
        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id,
            customer_id=self.customer.id,
            nik=self.customer.nik,
            inquiry_status='success'
        )
        self.fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            status_pinjaman='Outstanding',
            id_penyelenggara=self.fintech.id,
            tgl_penyaluran_dana=date.today(),
            is_julo_loan=False
        )
        self.fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}

    def test_delinquent_balcon_customer(self):
        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() - timedelta(days=10)
        )

        invalid_loan = get_invalid_loan_from_other_fintech(
            fdc_inquiry_data=self.fdc_inquiry_data,
            balcon_verification=self.balcon_verification
        )

        self.assertIsNotNone(invalid_loan)

    def test_not_delinquent_balcon_customer_disbursement_date(self):
        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() + timedelta(days=10)
        )

        invalid_loan = get_invalid_loan_from_other_fintech(
            fdc_inquiry_data=self.fdc_inquiry_data,
            balcon_verification=self.balcon_verification
        )

        self.assertIsNone(invalid_loan)

    def test_not_delinquent_balcon_customer_loan_status(self):
        self.fdc_inquiry_loan.update_safely(status_pinjaman='Fully Paid')
        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() - timedelta(days=10)
        )

        invalid_loan = get_invalid_loan_from_other_fintech(
            fdc_inquiry_data=self.fdc_inquiry_data,
            balcon_verification=self.balcon_verification
        )
        self.assertIsNone(invalid_loan)

    def test_not_delinquent_balcon_customer_fintech(self):
        fintech2 = FintechFactory(is_active=True)
        self.fdc_inquiry_loan.update_safely(id_penyelenggara=fintech2.id)
        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() - timedelta(days=10)
        )

        invalid_loan = get_invalid_loan_from_other_fintech(
            fdc_inquiry_data=self.fdc_inquiry_data,
            balcon_verification=self.balcon_verification
        )
        self.assertIsNone(invalid_loan)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.get_and_save_fdc_data')
    def test_request_fdc_data(self, mock_get_and_save_fdc_data, mock_now):
        mock_now.return_value = datetime(2024, 9, 20, 11, 0, 0, tzinfo=pytz.UTC)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.FETCH_FDC_DATA_DELAY,
            is_active=True,
            parameters={'delay_hour': 5}
        )
        self.fdc_inquiry.update_safely(
            cdate=datetime(2024, 9, 20, 10, 0, 0, tzinfo=pytz.UTC)
        )

        get_and_save_customer_latest_fdc_data(self.customer.id)
        mock_get_and_save_fdc_data.assert_not_called()

        self.fdc_inquiry.update_safely(
            cdate=datetime(2024, 9, 20, 5, 0, 0, tzinfo=pytz.UTC)
        )
        get_and_save_customer_latest_fdc_data(self.customer.id)
        mock_get_and_save_fdc_data.assert_called_once()

    @patch(f'{PACKAGE_NAME}.trigger_balcon_punishments')
    @patch(f'{PACKAGE_NAME}.get_invalid_loan_from_other_fintech')
    @patch(f'{PACKAGE_NAME}.get_and_save_customer_latest_fdc_data')
    def test_get_and_validate_fdc_data_for_delinquent_customer(
        self, mock_fdc_data, mock_invalid_fdc_inquiry_loan, mock_trigger_punishments
    ):
        mock_fdc_data.return_value = self.fdc_inquiry_data
        mock_invalid_fdc_inquiry_loan.return_value = self.fdc_inquiry_loan

        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() - timedelta(days=10)
        )
        get_and_validate_fdc_data_for_balcon_punishments(
            verification_id=self.balcon_verification.id,
            customer_id=self.customer.id
        )

        balcon_delinquent_fdc = BalanceConsolidationDelinquentFDCChecking.objects.filter(
            customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(balcon_delinquent_fdc)
        self.assertEqual(
            balcon_delinquent_fdc.balance_consolidation_verification, self.balcon_verification
        )
        self.assertEqual(
            balcon_delinquent_fdc.invalid_fdc_inquiry_loan_id, self.fdc_inquiry_loan.id
        )
        mock_trigger_punishments.assert_called_once_with(
            self.customer.id, self.balcon_verification
        )

    @patch(f'{PACKAGE_NAME}.trigger_balcon_punishments')
    @patch(f'{PACKAGE_NAME}.get_invalid_loan_from_other_fintech')
    @patch(f'{PACKAGE_NAME}.get_and_save_customer_latest_fdc_data')
    def test_get_and_validate_fdc_data_for_not_delinquent_customer(
        self, mock_fdc_data, mock_invalid_fdc_inquiry_loan, mock_trigger_punishments
    ):
        mock_fdc_data.return_value = self.fdc_inquiry_data
        mock_invalid_fdc_inquiry_loan.return_value = None

        self.balcon_verification.balance_consolidation.update_safely(
            cdate=datetime.now() - timedelta(days=10)
        )
        get_and_validate_fdc_data_for_balcon_punishments(
            verification_id=self.balcon_verification.id,
            customer_id=self.customer.id
        )

        balcon_delinquent_fdc = BalanceConsolidationDelinquentFDCChecking.objects.filter(
            customer_id=self.customer.id
        ).last()

        self.assertIsNone(balcon_delinquent_fdc)
        mock_trigger_punishments.assert_not_called()

    @patch('juloserver.moengage.services.use_cases.send_to_moengage')
    @patch('juloserver.moengage.services.data_constructors.timezone')
    def test_send_moengage_event_for_balcon_punishment(
        self, mock_timezone, mock_send_to_moengage
    ):
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.localtime.return_value = mock_now

        send_event_moengage_for_balcon_punishment(
            customer_id=self.customer.id,
            limit_deducted=500000,
            fintech_id=1,
            fintech_name="Kredivo"
        )

        data_to_send = [
            {
                'type': 'event',
                'customer_id': self.customer.id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.IS_BALANCE_CONSOLIDATION_PUNISHMENT,
                        'attributes': {
                            'limit_deducted': 500000,
                            'fintech_id': 1,
                            'fintech_name': "Kredivo"
                        },
                        'platform': 'ANDROID',
                        'current_time': mock_now.timestamp(),
                        'user_timezone_offset': mock_now.utcoffset().seconds,
                    }
                ]
            }
        ]

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.IS_BALANCE_CONSOLIDATION_PUNISHMENT,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)


class TestPunishmentReversePayment(TestCase):
    def setUp(self):
        local_time = datetime(2024, 9, 20, 10, 0, 0, tzinfo=pytz.UTC)
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LOC_APPROVED
            )
        )
        self.account_payments = AccountPaymentFactory.create_batch(
            4,
            account=self.account,
            due_amount=Iterator([
                2_250_000, 2_250_000, 2_250_000, 2_250_000
            ]),
            paid_interest=Iterator([
                250_000, 250_000, 250_000, 250_000
            ]),
            paid_amount=Iterator([
                250_000, 250_000, 250_000, 250_000
            ]),
        )
        self.fintech = FintechFactory(is_active=True)
        self.balcon = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_amount=10_000_000,
            loan_duration=4,
            loan_status=StatusLookupFactory(
                status_code=LoanStatusCodes.CURRENT
            ),
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
                method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            ),
        )
        self.balcon_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balcon,
            loan=self.loan,
            validation_status=BalanceConsolidationStatus.DISBURSED
        )

        self.payments = Payment.objects.filter(loan_id=self.loan.id)
        self.payments.update(
            due_amount=F('due_amount') - F('installment_interest'),
            paid_interest=F('paid_interest') + F('installment_interest'),
            paid_amount=F('paid_amount') + F('installment_interest')
        )
        self.account_trx = AccountTransactionFactory(
            account=self.account,
            payback_transaction=None,
            transaction_amount=1_000_000,
            transaction_type='waive_interest',
            towards_interest=1_000_000,
            transaction_date=local_time,
            accounting_date=local_time.date()
        )

        self.payment_events = []
        payment_event_ids = []
        for idx, payment in enumerate(self.payments):
            if payment.payment_number < 3:
                payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
            payment.account_payment = self.account_payments[idx]
            payment_event = PaymentEventFactory(
                payment=payment,
                event_payment=payment.installment_interest,
                event_due_amount=payment.due_amount+payment.installment_interest,
                event_type='waive_interest',
                payment_method=None,
                can_reverse=False,
                account_transaction=self.account_trx
            )
            self.payment_events.append(payment_event)
            payment.save()
            payment_event.save()
            payment_event_ids.append(payment_event.id)

        self.balcon_verification.update_safely(
            extra_data={'payment_event_ids': payment_event_ids}
        )

    @pytest.mark.skip(reason="Flaky")
    def test_reverse_all_payment_paid_interest(self):
        reverse_all_payment_paid_interest(self.customer.id, self.balcon_verification)

        for payment in self.payments:
            payment.refresh_from_db()
            if payment.payment_number < 3:
                self.assertEqual(payment.due_amount, 2_250_000)
                self.assertEqual(payment.paid_interest, 250_000)
                self.assertEqual(payment.paid_amount, 250_000)
                self.assertEqual(payment.account_payment.due_amount, 2_250_000)
                self.assertEqual(payment.account_payment.paid_interest, 250_000)
                self.assertEqual(payment.account_payment.paid_amount, 250_000)
            else:
                self.assertEqual(payment.due_amount, 2_500_000)
                self.assertEqual(payment.paid_interest, 0)
                self.assertEqual(payment.paid_amount, 0)
                self.assertEqual(payment.account_payment.due_amount, 2_500_000)
                self.assertEqual(payment.account_payment.paid_interest, 0)
                self.assertEqual(payment.account_payment.paid_amount, 0)

        reversal_account_trx = AccountTransaction.objects.filter(
            account_id=self.account.id,
            transaction_type='payment_void'
        ).last()
        self.assertIsNotNone(reversal_account_trx)
        self.assertEqual(reversal_account_trx.transaction_amount, -500_000)
        self.assertEqual(reversal_account_trx.towards_interest, -500_000)

        account_trx = AccountTransaction.objects.filter(
            account_id=self.account.id,
            transaction_type='waive_interest'
        ).last()
        self.assertIsNotNone(account_trx)
        self.assertEqual(account_trx.reversal_transaction_id, reversal_account_trx.id)

        payment_events = PaymentEvent.objects.filter(
            payment__in=self.payments[2:],
            event_type = 'payment_void'
        )
        self.assertEqual(payment_events.count(), 2)
        for payment_event in payment_events:
            self.assertEqual(payment_event.event_payment, -250_000)
            self.assertEqual(payment_event.event_due_amount, 2_250_000)
            self.assertEqual(payment_event.account_transaction_id, reversal_account_trx.id)
