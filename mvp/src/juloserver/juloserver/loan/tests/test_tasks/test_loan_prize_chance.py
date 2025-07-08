from unittest import mock

from django.test import TestCase
from django.utils import timezone

from juloserver.account.models import AccountLimitHistory
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.loan.tasks.loan_prize_chance import calculate_loan_prize_chances
from juloserver.promo.tests.factories import (
    PromoCodeFactory,
    PromoCodeUsageFactory,
)


@mock.patch('juloserver.loan.tasks.loan_prize_chance.store_loan_prize_chances')
@mock.patch('juloserver.loan.tasks.loan_prize_chance.get_loan_prize_chance_setting')
@mock.patch('juloserver.loan.tasks.loan_prize_chance.is_loan_eligible_for_prize_chance')
class TestCalculateLoanPrizeChances(TestCase):
    def setUp(self):
        self.account_limit = AccountLimitFactory()
        self.loan = LoanFactory(account=self.account_limit.account, loan_amount=50000)

    def test_calculate_with_0_chance(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=0),
            bonus_available_limit_threshold=20000,
            is_promo_code_enabled=False,
            chance_per_promo_code=1,
        )

        AccountLimitHistory.objects.create(
            account_limit=self.account_limit, field_name='available_limit',
            value_old=200000, value_new=100000,
        )
        AccountLimitHistory.objects.create(
            account_limit=self.account_limit, field_name='available_limit',
            value_old=100000, value_new=0,
        )
        calculate_loan_prize_chances(self.loan.id)

        mock_is_loan_eligible.assert_called_once_with(self.loan)
        mock_get_loan_prize_setting.assert_called_once_with()
        mock_store_loan_prize_chances.assert_not_called()

    def test_calculate_with_0_chance_full_limit(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=0),
            bonus_available_limit_threshold=20000,
            is_promo_code_enabled=False,
            chance_per_promo_code=1,
        )

        AccountLimitHistory.objects.create(
            account_limit=self.account_limit, field_name='available_limit',
            value_old=100000, value_new=19999,
        )

        AccountLimitHistory.objects.create(
            account_limit=self.account_limit, field_name='available_limit',
            value_old=200000, value_new=100000,
        )
        calculate_loan_prize_chances(self.loan.id)

        mock_is_loan_eligible.assert_called_once_with(self.loan)
        mock_get_loan_prize_setting.assert_called_once_with()
        mock_store_loan_prize_chances.assert_called_once_with(self.loan, 1)

    def test_calculate_with_0_chance_no_limit(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=0),
            is_promo_code_enabled=False,
            chance_per_promo_code=1,
        )

        calculate_loan_prize_chances(self.loan.id)

        mock_is_loan_eligible.assert_called_once_with(self.loan)
        mock_get_loan_prize_setting.assert_called_once_with()
        mock_store_loan_prize_chances.assert_not_called()

    def test_calculate_with_more_than_0_chance(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=10),
            is_promo_code_enabled=False,
            chance_per_promo_code=1,
        )

        calculate_loan_prize_chances(self.loan.id)

        mock_store_loan_prize_chances.assert_called_once_with(mock.ANY, 10)

    def test_calculate_promo_code(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        promo_code_usage = PromoCodeUsageFactory(loan_id=self.loan.id, applied_at=timezone.now())
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=10),
            is_promo_code_enabled=True,
            promo_code_id=promo_code_usage.promo_code_id,
            chance_per_promo_code=1,
        )

        calculate_loan_prize_chances(self.loan.id)
        mock_store_loan_prize_chances.assert_called_once_with(mock.ANY, 1)

    def test_calculate_promo_code_custom_chance(
        self,
        mock_is_loan_eligible,
        mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        promo_code_usage = PromoCodeUsageFactory(loan_id=self.loan.id, applied_at=timezone.now())
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=10),
            is_promo_code_enabled=True,
            promo_code_id=promo_code_usage.promo_code_id,
            chance_per_promo_code=2,
        )

        calculate_loan_prize_chances(self.loan.id)
        mock_store_loan_prize_chances.assert_called_once_with(mock.ANY, 2)

    def test_calculate_promo_code_not_applied(
        self, mock_is_loan_eligible, mock_get_loan_prize_setting,
        mock_store_loan_prize_chances,
    ):
        promo_code = PromoCodeFactory()
        mock_is_loan_eligible.return_value = True
        mock_get_loan_prize_setting.return_value = mock.Mock(
            is_active=True,
            calculate_chance=mock.Mock(return_value=10),
            is_promo_code_enabled=True,
            promo_code_id=promo_code.id,
            chance_per_promo_code=1,
        )

        calculate_loan_prize_chances(self.loan.id)
        mock_store_loan_prize_chances.assert_not_called()
