from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from factory import Iterator
from django.test import TestCase
from django.utils import timezone

from juloserver.cashback.constants import OverpaidConsts, CashbackChangeReason
from juloserver.cashback.models import (
    CashbackEarned,
    CashbackOverpaidVerification,
    CustomerWalletHistory,
)
from juloserver.cashback.services import (
    compute_cashback_expiry_date,
    generate_cashback_overpaid_case,
)
from juloserver.cashback.tests.factories import (
    CashbackEarnedFactory,
    OverpaidVerificationFactory,
)
from juloserver.cfs.tests.factories import CashbackBalanceFactory
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.customer_module.models import CashbackBalance
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    CustomerWalletHistoryFactory,
    ImageFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)


class TestCorrectingCashback(TestCase):

    def setUp(self):
        self.today = timezone.localtime(timezone.now()).date()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.PAYMENT_ON_TIME,
            wallet_balance_available=0,
            wallet_balance_available_old=0,
            cashback_earned=None
        )
        self.customer_wallet_history1 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.LOAN_PAID_OFF,
            wallet_balance_available=100000,
            wallet_balance_available_old=0,
            cashback_earned=None
        )
        self.customer_wallet_history2 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available=200000,
            wallet_balance_available_old=100000,
            cashback_earned=None
        )
        self.customer_wallet_history3 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.PAYMENT_ON_TIME,
            wallet_balance_available=200000,
            wallet_balance_available_old=200000,
            cashback_earned=None
        )
        self.customer_wallet_history4 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.LOAN_PAID_OFF,
            wallet_balance_available=250000,
            wallet_balance_available_old=200000,
            cashback_earned=CashbackEarnedFactory(
                current_balance=50000,
                expired_on_date=compute_cashback_expiry_date(self.today)
            )
        )
        self.customer_wallet_history5 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available=300000,
            wallet_balance_available_old=250000,
            cashback_earned=CashbackEarnedFactory(
                current_balance=50000,
                expired_on_date=compute_cashback_expiry_date(self.today)
            )
        )
        self.customer_wallet_history6 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.VERIFYING_OVERPAID,
            wallet_balance_available=250000,
            wallet_balance_available_old=300000,
            cashback_earned=None
        )
        self.customer_wallet_history7 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.USED_ON_PAYMENT,
            wallet_balance_available=0,
            wallet_balance_available_old=250000,
            cashback_earned=None
        )
        self.customer_wallet_history8 = CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED,
            wallet_balance_available=50000,
            wallet_balance_available_old=0,
            cashback_earned=None
        )
        self.cashback_overpaid_verification = CashbackOverpaidVerification.objects.get(
            wallet_history=self.customer_wallet_history5
        )
        self.cashback_overpaid_verification.update_safely(status=OverpaidConsts.Statuses.ACCEPTED)

    def test_command_success(self, *args, **options):
        out = StringIO()
        call_command('correcting_cashback_earned_and_cashback_balance', stdout=out)
        out.seek(0)
        self.assertIn("Finished the process of updating %i of ids." % len([self.customer.id]), out.readline())
        self.assertIn("Retroload is run successfully.", out.readline())

    @patch('juloserver.cashback.tasks.update_cashback_earned_and_cashback_balance.delay')
    def test_function_calling(self, mock_update_cashback_earned_and_cashback_balance):
        call_command('correcting_cashback_earned_and_cashback_balance')
        today = timezone.localtime(timezone.now()).date()
        mock_update_cashback_earned_and_cashback_balance.assert_called_once_with(
            [self.customer.id], today
        )

    def test_cashback_earned_verified_false(self):
        call_command('correcting_cashback_earned_and_cashback_balance')

        self.assertEqual(self.customer_wallet_history2.cashback_earned, None)
        self.customer_wallet_history2.refresh_from_db()
        customer_wallet_history2 = CustomerWalletHistory.objects.get(
            id=self.customer_wallet_history2.id
        )
        self.assertEqual(customer_wallet_history2.cashback_earned.verified, False)

    def test_cashback_earned_verified_true(self):
        call_command('correcting_cashback_earned_and_cashback_balance')

        self.assertEqual(self.customer_wallet_history5.cashback_earned.verified, True)
        self.customer_wallet_history5.refresh_from_db()
        self.assertEqual(self.customer_wallet_history5.cashback_earned.verified, True)

    def test_cashback_earned_added_cashback_overpaid(self):
        call_command('correcting_cashback_earned_and_cashback_balance')
        self.customer_wallet_history2.refresh_from_db()
        customer_wallet_history2 = CustomerWalletHistory.objects.get(
            id=self.customer_wallet_history2.id
        )
        self.assertIsNotNone(customer_wallet_history2.cashback_earned)

    def test_cashback_earned_added_normal_cashback(self):
        call_command('correcting_cashback_earned_and_cashback_balance')
        self.customer_wallet_history1.refresh_from_db()
        customer_wallet_history2 = CustomerWalletHistory.objects.get(
            id=self.customer_wallet_history1.id
        )
        self.assertIsNotNone(customer_wallet_history2.cashback_earned)

    def test_cashback_earned_not_added(self):
        call_command('correcting_cashback_earned_and_cashback_balance')

        self.customer_wallet_history6.refresh_from_db()
        customer_wallet_history6 = CustomerWalletHistory.objects.get(
            id=self.customer_wallet_history6.id
        )
        self.assertIsNone(customer_wallet_history6.cashback_earned)

    @patch('juloserver.cashback.tasks.logger')
    def test_logger_is_called(self, mock_logger):
        call_command('correcting_cashback_earned_and_cashback_balance')

        mock_logger.info.assert_called()


class TestCommandUpdateCashbackBalance(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.cashback_earned = CashbackEarnedFactory.create_batch(
            8, current_balance=Iterator([
                0, 339000, 0, 99000, 0, 624000, 204500, 5500
            ]), verified=Iterator([
                True, False, True, False, True, False, True, True
            ])
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory.create_batch(
            8, customer=self.customer, wallet_balance_available=Iterator([
                9000, 348000, 14994, 113994, 162994, 786994, 210000, 210000
            ]), cashback_earned=Iterator(self.cashback_earned)
        )
        self.cashback_balance = CashbackBalanceFactory(
            customer=self.customer, cashback_balance=10000,
            status=CashbackBalanceStatusConstant.UNFREEZE
        )
        self.out = StringIO()

    def test_successfully_updated_cashback_balance(self):
        call_command('retroload_update_cashback_balance', stdout=self.out)

        self.cashback_balance.refresh_from_db()
        self.assertEqual(self.cashback_balance.cashback_balance, 210000)

    def test_initial_negative_cashback_balance(self):
        self.cashback_balance.cashback_balance = -100000
        self.cashback_balance.save()
        call_command('retroload_update_cashback_balance', stdout=self.out)

        self.cashback_balance.refresh_from_db()
        self.assertEqual(self.cashback_balance.cashback_balance, 210000)

    def test_customer_cashback_balance_empty(self):
        customer2 = CustomerFactory()
        ApplicationFactory(customer=customer2)
        cashback_earned2 = CashbackEarnedFactory.create_batch(
            8, current_balance=Iterator([
                0, 339000, 0, 99000, 0, 624000, 204500, 5500
            ]), verified=Iterator([
                True, False, True, False, True, True, True, True
            ])
        )
        CustomerWalletHistoryFactory.create_batch(
            8, customer=customer2, wallet_balance_available=Iterator([
                9000, 348000, 14994, 113994, 162994, 786994, 210000, 210000
            ]), cashback_earned=Iterator(cashback_earned2)
        )
        call_command('retroload_update_cashback_balance', stdout=self.out)

        result = CashbackBalance.objects.get_or_none(cashback_balance=834000)
        self.assertIsNone(result)

