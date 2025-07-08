from datetime import (
    date,
    datetime,
    timedelta,
)
from factory import Iterator
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.cashback.exceptions import CashbackLessThanMinAmount
from juloserver.cashback.constants import (
    OverpaidConsts,
    CashbackExpiredConst,
    CashbackChangeReason,
    FeatureNameConst as CashbackFeatureNameConst
)
from juloserver.cashback.services import (
    compute_cashback_expiry_date,
    create_cashback_transfer_transaction,
    get_expired_date_and_cashback,
    is_cashback_enabled,
    has_ineligible_overpaid_cases,
    CashbackExpiredSetting,
    get_cashback_expiry_info, update_wallet_earned, process_decision_overpaid_case,
)
from juloserver.cashback.tests.factories import CashbackEarnedFactory, OverpaidVerificationFactory
from juloserver.cfs.tests.factories import CashbackBalanceFactory, AgentFactory
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.julo.banks import BankManager
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import ProductLine, CustomerWalletHistory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.cashback import CashbackRedemptionService
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.julo.tests.factories import (
    BankFactory,
    CustomerFactory,
    CustomerWalletHistoryFactory,
    FeatureSettingFactory,
    ApplicationFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    ReferralSystemFactory,
    CustomerWalletHistoryFactory,
    ApplicationHistoryFactory,
    PaymentFactory
)
from juloserver.julo.constants import (
    CashbackTransferConst,
    FeatureNameConst,
)
from juloserver.cashback.models import CashbackEarned, CashbackOverpaidVerification
from juloserver.referral.services import process_referral_code_v2
from juloserver.referral.constants import (
    ReferralBenefitConst,
    FeatureNameConst as ReferralFeatureNameConst
)
from juloserver.referral.tests.factories import ReferralBenefitFactory

PACKAGE_NAME = 'juloserver.cashback.services'


class TestWalletEarned(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        julover_app_factory = ApplicationFactory.julover()
        self.julover_customer = julover_app_factory.customer
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            parameters={'months': 24}
        )

    def test_cashback_earned(self):
        self.customer.change_wallet_balance(0, 10000, 'cashback earned')
        cashback_earned = CashbackEarned.objects.first()
        self.assertEqual(cashback_earned.current_balance, 10000)

    def test_cashback_used(self):
        self.customer.change_wallet_balance(0, 10000, 'cashback earned')
        self.customer.change_wallet_balance(0, -5000, 'cashback used')
        cashback_earned = CashbackEarned.objects.first()
        self.assertEqual(cashback_earned.current_balance, 5000)

    def test_cashback_earned_julover(self):
        self.julover_customer.change_wallet_balance(0, 5000, 'cashback earned')
        cashback_earned = CashbackEarned.objects.first()
        self.assertEqual(cashback_earned.current_balance, 5000)

    def test_cashback_used_julover(self):
        self.julover_customer.change_wallet_balance(0, 20000, 'cashback earned')
        self.julover_customer.change_wallet_balance(0, -10000, 'cashback used')
        cashback_earned = CashbackEarned.objects.first()
        self.assertEqual(cashback_earned.current_balance, 10000)

    def test_cashback_earned_case_overpaid(self):
        history1 = self.customer.change_wallet_balance(
            100000, 100000, CashbackChangeReason.CASHBACK_OVER_PAID
        )
        history2 = self.customer.change_wallet_balance(
            0, -100000, CashbackChangeReason.VERIFYING_OVERPAID
        )
        history3 = self.customer.change_wallet_balance(
            0, 100000, CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED
        )
        case = CashbackOverpaidVerification.objects.get(wallet_history=history1)
        case.update_safely(status=OverpaidConsts.Statuses.ACCEPTED)
        cashback_earned = case.wallet_history.cashback_earned
        cashback_earned.current_balance = 100000
        cashback_earned.verified = True
        cashback_earned.save()

        self.assertIsNotNone(history1.cashback_earned)
        self.assertIsNone(history2.cashback_earned)
        self.assertIsNone(history3.cashback_earned)

        self.assertEqual(self.customer.wallet_balance_available, 100000)

    def test_cashback_earned_case_overpaid_void(self):
        history1 = self.customer.change_wallet_balance(
            0, 100000, CashbackChangeReason.CASHBACK_OVER_PAID
        )

        with self.assertRaises(Exception) as e:
            self.customer.change_wallet_balance(
                0, -5000, CashbackChangeReason.CASHBACK_OVER_PAID_VOID
            )
        self.assertTrue(str(e), "juloserver.julo.models.DoesNotExist: "
                                "CustomerWalletHistory matching query does not exist."
                        )
        self.customer.change_wallet_balance(
            0, -100000, CashbackChangeReason.CASHBACK_OVER_PAID_VOID
        )
        history1.refresh_from_db()
        self.assertEqual(history1.cashback_earned.current_balance, 0)


class TestCashbackServices(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.julover_application = ApplicationFactory.julover()
        self.julover_customer = self.julover_application.customer
        self.workflow = WorkflowFactory(
            name='JuloOneWorkflow',
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            name_in_bank="I'm Iron Man",
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.bank = BankFactory()
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            parameters={'months': 24}
        )
        history1 = self.customer.change_wallet_balance(0, 200_000,reason='sold my kidney')
        self.cashback_earned1 = history1.cashback_earned
        history2 = self.customer.change_wallet_balance(0, 5_000_000,reason='sold my heart')
        self.cashback_earned2 = history2.cashback_earned
        history3 = self.customer.change_wallet_balance(0, 100_000_000_000,reason='sold my brain')
        self.cashback_earned3 = history3.cashback_earned
        history4 = self.customer.change_wallet_balance(0, 100,reason='sold my wife')
        self.cashback_earned4 = history4.cashback_earned
        self.today = timezone.localtime(timezone.now()).date()

        # julo turbo application
        self.workflow1 = WorkflowFactory(
            name=WorkflowConst.JULO_STARTER,
        )
        self.application1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow1,
            name_in_bank="I'm Iron Man",
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        )


    def test_cashback_enability(self):
        # Julo1 case
        self.assertEqual(is_cashback_enabled(self.application), True)

        # Julover case
        self.assertEqual(is_cashback_enabled(self.julover_application), True)

        # Non Julo1 case
        self.application.workflow = WorkflowFactory(
            name='TestingWorkflow',
        )
        self.application.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB
        )
        self.application.save()
        self.assertEqual(is_cashback_enabled(self.application), False)

        # Non Julo1 case but old product lines
        old_product_codes = [
            *ProductLineCodes.mtl(),
            *ProductLineCodes.stl(),
            *ProductLineCodes.bri(),
            *ProductLineCodes.ctl(),
        ]
        for code in old_product_codes:
            self.application.product_line = ProductLine.objects.get(product_line_code=code)
            self.application.save()
            self.assertEqual(is_cashback_enabled(self.application), True)

    def test_cashback_enability_in_julo_turbo(self):
        self.assertEqual(is_cashback_enabled(self.application1), True)

        # workflow julo_starter, product_line != julo_starter
        self.application1.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB
        )
        self.application1.save()
        self.assertEqual(is_cashback_enabled(self.application1), True)

        # workflow != julo_starter, product_line = julo_starter
        self.application1.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
        )
        self.application1.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application1.save()
        self.assertEqual(is_cashback_enabled(self.application1), False)

        # workflow != julo_starter, product_line != julo_starter
        self.application1.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
        )
        self.application1.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB1
        )
        self.application1.save()
        self.assertEqual(is_cashback_enabled(self.application1), False)

    def test_has_ineligble_overpaid_case(self):
        x = has_ineligible_overpaid_cases(self.customer)
        self.assertEqual(x, False)
        # add unprocessed overpaid
        CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available_old=20000,
            wallet_balance_available=20000 + OverpaidConsts.MINIMUM_AMOUNT,
        )
        x = has_ineligible_overpaid_cases(self.customer)
        self.assertEqual(x, True)

        x = has_ineligible_overpaid_cases(None)
        self.assertEqual(x, False)

    @patch.object(BankManager, 'get_by_name_or_none')
    def test_create_cashback_transfer_transaction(self, mock_get_bank):
        mock_get_bank.return_value = self.bank
        self.application.bank_name = 'bca'
        self.application.save()
        amount = 50000
        new_cashback_request = create_cashback_transfer_transaction(self.application, amount)
        self.assertEqual(new_cashback_request.transfer_amount, amount - 4000)
        self.assertEqual(new_cashback_request.partner_transfer, CashbackTransferConst.METHOD_BCA)

        self.application.bank_name = "We're gonna need a bigger test case..."
        self.application.save()

        new_cashback_request = create_cashback_transfer_transaction(self.application, amount)
        self.assertEqual(new_cashback_request.partner_transfer, CashbackTransferConst.METHOD_XFERS)

        with self.assertRaises(CashbackLessThanMinAmount) as context:
            create_cashback_transfer_transaction(self.application, 3000)

    @patch.object(BankManager, 'get_by_name_or_none')
    def test_create_cashback_transfer_transaction_julover(self, mock_get_bank):
        mock_get_bank.return_value = self.bank
        self.julover_application.bank_name = 'bca'
        self.julover_application.name_in_bank = 'Joker'
        self.julover_application.save()
        amount = 50000
        new_cashback_request = create_cashback_transfer_transaction(self.julover_application, amount)
        self.assertEqual(new_cashback_request.transfer_amount, amount - 4000)
        self.assertEqual(new_cashback_request.partner_transfer, CashbackTransferConst.METHOD_BCA)

        self.julover_application.bank_name = 'mandiri'
        self.julover_application.save()

        new_cashback_request = create_cashback_transfer_transaction(self.julover_application, amount)
        self.assertEqual(new_cashback_request.partner_transfer, CashbackTransferConst.METHOD_XFERS)

        with self.assertRaises(CashbackLessThanMinAmount) as context:
            create_cashback_transfer_transaction(self.julover_application, 3000)

    def test_compute_cashback_expiry_date(self):
        d1 = datetime.strptime("2022-09-30", '%Y-%m-%d')
        result1 = compute_cashback_expiry_date(d1)
        self.assertEqual(result1, date(2022,12,31))

        d2 = datetime.strptime("2022-10-01", '%Y-%m-%d')
        result2 = compute_cashback_expiry_date(d2)
        self.assertEqual(result2, date(2023,12,31))

        d3 = datetime.strptime("2022-12-31", '%Y-%m-%d')
        result3 = compute_cashback_expiry_date(d3)
        self.assertEqual(result3, date(2023,12,31))

    def test_get_expired_date_and_cashback(self):
        # case: history 3&4 expires later than history 1&2 (history 3&4 > 1&2)
        self.cashback_earned1.expired_on_date = self.today + timedelta(days=1)
        self.cashback_earned1.save()
        self.cashback_earned2.expired_on_date = self.today + timedelta(days=1)
        self.cashback_earned2.save()
        self.cashback_earned3.expired_on_date = self.today + timedelta(days=3)
        self.cashback_earned3.save()
        self.cashback_earned4.expired_on_date = self.today + timedelta(days=5)
        self.cashback_earned4.save()

        next_expired_date, expired_cash = get_expired_date_and_cashback(self.customer.id)
        self.assertEqual(next_expired_date, self.today + timedelta(days=1))
        self.assertEqual(
            expired_cash,
            self.cashback_earned1.current_balance +
            self.cashback_earned2.current_balance
        )
        # case: history 4 > history 2&3 > today > history1
        self.cashback_earned1.expired_on_date = self.today + timedelta(days=-1)
        self.cashback_earned1.save()
        self.cashback_earned2.expired_on_date = self.today + timedelta(days=3)
        self.cashback_earned2.save()

        next_expired_date, expired_cash = get_expired_date_and_cashback(self.customer.id)
        self.assertEqual(next_expired_date, self.today + timedelta(days=3))
        self.assertEqual(
            expired_cash,
            self.cashback_earned2.current_balance +
            self.cashback_earned3.current_balance
        )

        # case: same as above but history 2&3 expires today
        self.cashback_earned2.expired_on_date = self.today
        self.cashback_earned2.save()
        self.cashback_earned3.expired_on_date = self.today
        self.cashback_earned3.save()

        next_expired_date, expired_cash = get_expired_date_and_cashback(self.customer.id)
        self.assertEqual(next_expired_date, self.today + timedelta(days=5))
        self.assertEqual(
            expired_cash,
            self.cashback_earned4.current_balance
        )
        # case: all of them in the past
        self.cashback_earned1.expired_on_date = self.today + timedelta(days=-1)
        self.cashback_earned1.save()
        self.cashback_earned2.expired_on_date = self.today + timedelta(days=-1)
        self.cashback_earned2.save()
        self.cashback_earned3.expired_on_date = self.today + timedelta(days=-1)
        self.cashback_earned3.save()
        self.cashback_earned4.expired_on_date = self.today + timedelta(days=-1)
        self.cashback_earned4.save()

        next_expired_date, expired_cash = get_expired_date_and_cashback(self.customer.id)
        self.assertEqual(next_expired_date, None)
        self.assertEqual(expired_cash, 0)


class TestCashbackRedemptionService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(
            name='JuloOneWorkflow',
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            name_in_bank="Wolverine",
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )

    @patch('juloserver.julo.services2.cashback.cashback_payment_process_account')
    def test_pay_next_loan_payment_case_activeloan(self, mock_cashback_payment_process):
        # no loan
        service = CashbackRedemptionService()
        result = service.pay_next_loan_payment(
            customer=self.customer,
        )
        self.assertEqual(result, False)

        # loan 210
        x = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        result = service.pay_next_loan_payment(
            customer=self.customer,
        )
        self.assertEqual(result, False)

        # loan 250
        x.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
        x.save()
        result = service.pay_next_loan_payment(
            customer=self.customer,
        )
        self.assertEqual(result, False)

        # loan active
        x.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        x.save()
        mock_cashback_payment_process.return_value = 'yada yada yada'
        result = service.pay_next_loan_payment(
            customer=self.customer,
        )
        self.assertEqual(result, 'yada yada yada')


class TestGetCashbackExpiryInfo(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @patch.object(timezone, 'now')
    def test_with_expiry_info(self, mock_now):
        mock_now.return_value = datetime(2020, 12, 30, 0, 0, 0)
        CustomerWalletHistoryFactory(
            customer=self.customer,
            cashback_earned=CashbackEarnedFactory(
                expired_on_date=date(2020, 12, 31), current_balance=20000, verified=True)
        )
        CashbackBalanceFactory(customer=self.customer, cashback_balance=20000)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True,
            parameters={'reminder_days': 1}
        )

        ret_val = get_cashback_expiry_info(self.customer.id)
        self.assertEqual('Cashback <b>Rp 20.000</b> akan kadaluwarsa tanggal '
                         '<b>31 Desember 2020</b>.', ret_val)

    @patch('{}.get_expired_date_and_cashback'.format(PACKAGE_NAME))
    @patch.object(timezone, 'now')
    def test_no_expired_cashback(self, mock_now, mock_get_expired_date_and_cashback):
        mock_now.return_value = datetime(2024, 5, 30, 0, 0, 0)
        today = timezone.localtime(timezone.now()).date()
        mock_get_expired_date_and_cashback.return_value = today, 0

        ret_val = get_cashback_expiry_info(self.customer.id)

        self.assertIsNone(ret_val)
        mock_get_expired_date_and_cashback.assert_called_once_with(self.customer.id)

    @patch('{}.get_expired_date_and_cashback'.format(PACKAGE_NAME))
    @patch.object(timezone, 'now')
    def test_more_than_reminder_days(self, mock_now, mock_get_expired_date_and_cashback):
        mock_now.return_value = datetime(2020, 12, 29, 0, 0, 0)
        mock_get_expired_date_and_cashback.return_value = date(2020, 12, 31), 10000
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True,
            parameters={'reminder_days': 1}
        )

        ret_val = get_cashback_expiry_info(self.customer.id)
        self.assertIsNone(ret_val)

    @patch.object(timezone, 'now')
    def test_multiple_cashback_earned_status(self, mock_now):
        mock_now.return_value = datetime(2020, 12, 30, 0, 0, 0)
        cashback_earned = CashbackEarnedFactory.create_batch(
            2, expired_on_date=date(2020, 12, 31),
            current_balance=Iterator([20000, 100000]),
            verified=Iterator([True, False])
        )
        CustomerWalletHistoryFactory.create_batch(
            2, customer=self.customer, cashback_earned=Iterator(cashback_earned)
        )
        CashbackBalanceFactory(customer=self.customer, cashback_balance=20000)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True,
            parameters={'reminder_days': 1}
        )

        ret_val = get_cashback_expiry_info(self.customer.id)
        self.assertEqual('Cashback <b>Rp 20.000</b> akan kadaluwarsa tanggal '
                         '<b>31 Desember 2020</b>.', ret_val)


class TestCashbackExpiredSetting(TestCase):
    def test_get_reminder_days(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True, parameters={'reminder_days': 15}
        )
        ret_val = CashbackExpiredSetting.get_reminder_days()
        self.assertEqual(15, ret_val)

    def test_get_reminder_days_default(self):
        ret_val = CashbackExpiredSetting.get_reminder_days()
        self.assertEqual(CashbackExpiredConst.DEFAULT_REMINDER_DAYS, ret_val)


class TestCashbackBalanceUpdate(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.cashback_balance = CashbackBalanceFactory(customer=self.customer)

    def test_change_wallet_balance_random_event(self):
        self.customer.change_wallet_balance(100000, 100000, 'test1')
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 100000)

        self.customer.change_wallet_balance(100000, 100000, 'test_reason')
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 200000)

    def test_change_wallet_balance_overpaid_related(self):
        overpaid_reason = [CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED,
                           CashbackChangeReason.VERIFYING_OVERPAID,
                           CashbackChangeReason.CASHBACK_OVER_PAID]

        for reason in overpaid_reason:
            self.customer.change_wallet_balance(100000, 100000, reason)
            self.cashback_balance.refresh_from_db()
            self.assertEquals(self.cashback_balance.cashback_balance, 0)


class TestCashbackTemporarilyFreeze(TestCase):
    def setUp(self):
        self.set_up_referrer()
        self.set_up_referee()
        self.setup_feature_settings()
        self.setup_referral_system()

    def set_up_referrer(self):
        self.referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        self.referrer_account = AccountFactory(
            customer=self.referrer,
            status=StatusLookupFactory(status_code=420)
        )
        self.referrer_application = ApplicationFactory(
            customer=self.referrer,
            account=self.referrer_account
        )

    def set_up_referee(self):
        self.product_line_code = ProductLineFactory(product_line_code=1)
        self.user_auth = AuthUserFactory()
        self.referee = CustomerFactory(user=self.user_auth)
        self.referee_account = AccountFactory(
            customer=self.referee,
            status=StatusLookupFactory(status_code=420)
        )
        self.referee_application = ApplicationFactory(
            customer=self.referee,
            account=self.referee_account,
            referral_code='TEST_REFERRAL_CODE',
            product_line=self.product_line_code,
        )

    def setup_feature_settings(self):
        self.freeze_cashback_fs_params = {
            'first_repayment_logic': {
                'is_active': True
            },
            'period_logic': {
                'is_active': True,
                'start_date': '2023-11-01',
                'end_date': '2023-12-31',
                'mimimum_freeze_date': '2024-01-01',
                'freeze_period': 45
            }
        }
        self.freeze_cashback_fs = FeatureSettingFactory(
            feature_name=CashbackFeatureNameConst.CASHBACK_TEMPORARY_FREEZE,
            parameters=self.freeze_cashback_fs_params
        )
        self.referral_fs = FeatureSettingFactory(
            feature_name=ReferralFeatureNameConst.REFERRAL_BENEFIT_LOGIC
        )

    def setup_referral_system(self):
        self.referral_system = ReferralSystemFactory(
            name='PromoReferral',
            minimum_transaction_amount=80000
        )
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=100000, is_active=True
        )

    def test_disabled_feature_setting(self):
        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        self.freeze_cashback_fs.update_safely(is_active=False)
        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    def test_period_and_first_repayment_off(self):
        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = False
        self.freeze_cashback_fs_params['period_logic']['is_active'] = False
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000,
        )

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch.object(timezone, 'now')
    def test_period_on_and_first_repayment_off_before_period(self, mock_now):
        mock_now.return_value = datetime(2023, 10, 18, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = False
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000,
        )
        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch.object(timezone, 'now')
    def test_period_on_and_first_repayment_off_after_period(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 12, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = False
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000,
        )

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch('juloserver.cashback.tasks.unfreeze_referrer_and_referree_cashback_task')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch.object(timezone, 'now')
    def test_period_on_and_first_repayment_off_during_period(self, mock_now,
                                                             mock_payment_signal,
                                                             mock_unfreeze_cashback_task):
        mock_now.return_value = datetime(2023, 11, 27, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = False
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan & payments
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        payments = PaymentFactory.create_batch(
            3, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=310)
        )
        first_payment = list(filter(lambda pm: pm.payment_number == 1, payments))[0]

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: first repayment off -> do nothing
        mock_now.return_value = datetime(2023, 12, 5, 0, 0, 0)
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        first_payment.update_safely(payment_status=StatusLookupFactory(status_code=330))

        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        mock_now.return_value = datetime(2024, 2, 23, 0, 0, 0)
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        first_payment.update_safely(payment_status=StatusLookupFactory(status_code=331))

        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

    @patch('juloserver.cashback.tasks.unfreeze_referrer_and_referree_cashback_task')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch.object(timezone, 'now')
    def test_period_first_repayment_on_before_period(self, mock_now,
                                                     mock_payment_signal,
                                                     mock_unfreeze_cashback_task):
        mock_now.return_value = datetime(2023, 10, 21, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = True
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan & payments
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        payments = PaymentFactory.create_batch(
            3, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=310)
        )

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: repayment before period -> freeze
        payments[0].update_safely(payment_status=StatusLookupFactory(status_code=331))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch('juloserver.cashback.tasks.unfreeze_referrer_and_referree_cashback_task')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch.object(timezone, 'now')
    def test_period_first_repayment_on_after_period(self, mock_now,
                                                    mock_payment_signal,
                                                    mock_unfreeze_cashback_task):
        mock_now.return_value = datetime(2024, 1, 17, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = True
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan & payments
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        payments = PaymentFactory.create_batch(
            3, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=310)
        )

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze
        payments[0].update_safely(payment_status=StatusLookupFactory(status_code=331))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch('juloserver.cashback.tasks.unfreeze_referrer_and_referree_cashback_task')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch.object(timezone, 'now')
    def test_period_and_first_repayment_on_during_period(self, mock_now,
                                                         mock_payment_signal,
                                                         mock_unfreeze_cashback_task):
        mock_now.return_value = datetime(2023, 11, 2, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = True
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan & payments
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        payments = PaymentFactory.create_batch(
            3, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=310),
        )

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: 1st repayment in period -> freeze
        mock_now.return_value = datetime(2023, 11, 25, 0, 0, 0)
        payments[0].update_safely(payment_status=StatusLookupFactory(status_code=330))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: 2nd repayment in period -> freeze
        mock_now.return_value = datetime(2023, 11, 25, 0, 0, 0)
        payments[1].update_safely(payment_status=StatusLookupFactory(status_code=330))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: 2nd repayment in period -> freeze
        mock_now.return_value = datetime(2023, 2, 1, 0, 0, 0)
        payments[1].update_safely(payment_status=StatusLookupFactory(status_code=331))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertFalse(referrer_wallet_history.cashback_earned.verified)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 0)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze: 1st repayment after period -> unfreeze
        mock_now.return_value = datetime(2023, 2, 1, 0, 0, 0)
        payments[0].update_safely(payment_status=StatusLookupFactory(status_code=332))
        referrer_wallet_history.refresh_from_db()
        referee_wallet_history.refresh_from_db()
        self.assertTrue(referrer_wallet_history.cashback_earned.verified)
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referrer_wallet_history.cashback_balance.cashback_balance, 50000)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)

    @patch('juloserver.cashback.tasks.unfreeze_referrer_and_referree_cashback_task')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch.object(timezone, 'now')
    def test_referrer_application_deleted(self, mock_now,
                                          mock_payment_signal,
                                          mock_unfreeze_cashback_task):
        mock_now.return_value = datetime(2024, 1, 17, 0, 0, 0)

        # Setup fs params
        self.freeze_cashback_fs_params['first_repayment_logic']['is_active'] = True
        self.freeze_cashback_fs_params['period_logic']['is_active'] = True
        self.freeze_cashback_fs.update_safely(parameters=self.freeze_cashback_fs_params)

        # Create x190 referee application history
        ApplicationHistoryFactory(
            application_id=self.referee_application.id,
            status_old=110,
            status_new=190
        )

        # Create loan & payments
        loan = LoanFactory(
            customer=self.referee,
            application=self.referee_application,
            account=self.referee_account,
            loan_amount=300000
        )
        payments = PaymentFactory.create_batch(
            3, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=310)
        )

        # Delete referrer application
        self.referrer_application.update_safely(is_deleted=True)

        process_referral_code_v2(self.referee_application, loan, self.referral_fs)
        referrer_wallet_history = CustomerWalletHistory.objects.get_or_none(customer=self.referrer)
        referee_wallet_history = CustomerWalletHistory.objects.get(customer=self.referee)

        # Check cashback freeze
        self.assertIsNone(referrer_wallet_history)
        self.assertFalse(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 0)

        # Check cashback unfreeze
        payments[0].update_safely(payment_status=StatusLookupFactory(status_code=331))
        referee_wallet_history.refresh_from_db()
        self.assertTrue(referee_wallet_history.cashback_earned.verified)
        self.assertEqual(referee_wallet_history.cashback_balance.cashback_balance, 20000)
