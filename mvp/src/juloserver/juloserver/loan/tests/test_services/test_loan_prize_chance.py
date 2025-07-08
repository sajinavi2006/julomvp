import pytest

from datetime import timedelta
from unittest import mock

from django.test import TestCase, SimpleTestCase
from factory import Iterator

from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    CustomerFactory,
)
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.loan.services.loan_prize_chance import *
from juloserver.loan.services import loan_prize_chance
from juloserver.loan.tests.factories import LoanPrizeChanceFactory
from juloserver.promo.tests.factories import PromoCodeFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.ana_api.tests.factories import EarlyHiSeasonTicketCountFactory


class TestGetLoanPrizeCounter(TestCase):
    def setUp(self):
        loan_prize_chance._loan_prize_chance_setting = None
        self.setting = FeatureSettingFactory(
            feature_name='marketing_loan_prize_chance',
            is_active=True,
            parameters={
                'minimum_amount': 1000000,
                'start_time': '2023-10-13 00:00:00',
                'end_time': '2023-11-30 23:59:59',
            }
        )

    def test_is_active_inside_time_range(self):
        setting = get_loan_prize_chance_setting()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 10, 13, 0, 0, 0)
            self.assertTrue(setting.is_active)

    def test_is_active_outside_time_range(self):
        setting = get_loan_prize_chance_setting()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 12, 1, 0, 0, 0)
            self.assertFalse(setting.is_active)

            mock_now.return_value = datetime(2023, 10, 12, 23, 59, 59)
            self.assertFalse(setting.is_active)

    def test_is_active_feature_not_active(self):
        self.setting.update_safely(is_active=False)
        setting = get_loan_prize_chance_setting()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 10, 13, 0, 0, 0)
            self.assertFalse(setting.is_active)

    def test_start_time(self):
        setting = get_loan_prize_chance_setting()
        self.assertIsInstance(setting.start_time, datetime)
        self.assertEqual('Asia/Jakarta', setting.start_time.tzinfo.zone)
        self.assertEqual('2023-10-13 00:00:00', setting.start_time.strftime('%Y-%m-%d %H:%M:%S'))

    def test_end_time(self):
        setting = get_loan_prize_chance_setting()
        self.assertIsInstance(setting.start_time, datetime)
        self.assertEqual('Asia/Jakarta', setting.end_time.tzinfo.zone)
        self.assertEqual('2023-11-30 23:59:59', setting.end_time.strftime('%Y-%m-%d %H:%M:%S'))

    def test_minimum_amount(self):
        setting = get_loan_prize_chance_setting()
        self.assertEqual(1000000, setting.minimum_amount)

    def test_calculate_chance(self):
        setting = get_loan_prize_chance_setting()
        with mock.patch.object(timezone, 'now') as mock_now:
            # Test inside of time range
            mock_now.return_value = datetime(2023, 10, 13, 0, 0, 0)
            self.assertEqual(0, setting.calculate_chance(999999))
            self.assertEqual(1, setting.calculate_chance(1999999))
            self.assertEqual(2, setting.calculate_chance(2999999))

            # Test outside of time range
            mock_now.return_value = datetime(2023, 10, 12, 23, 59, 59)
            self.assertEqual(0, setting.calculate_chance(1999999))

    def test_calculate_chance_turn_off(self):
        self.setting.update_safely(is_active=False)
        setting = get_loan_prize_chance_setting()
        with mock.patch.object(timezone, 'now') as mock_now:
            # Test inside of time range
            mock_now.return_value = datetime(2023, 10, 13, 0, 0, 0)
            self.assertEqual(0, setting.calculate_chance(1999999))

    def test_promo_code_id(self):
        self.setting.parameters = {
            'promo_code_id': '10'
        }
        self.setting.save()
        setting = get_loan_prize_chance_setting()
        self.assertEqual(10, setting.promo_code_id)

    def test_promo_code_id_none(self):
        self.setting.parameters = {}
        self.setting.save()
        setting = get_loan_prize_chance_setting()
        self.assertIsNone(setting.promo_code_id)

    def test_promo_code_start_time(self):
        promo_code = PromoCodeFactory(
            start_date='2023-02-01 00:00:00',
            end_date='2023-02-20 23:59:59'
        )
        self.setting.parameters = {
            'promo_code_id': promo_code.id,
            'start_time': '2023-03-01 00:00:00',
            'end_time': '2023-03-01 00:00:00',
        }
        self.setting.save()
        setting = get_loan_prize_chance_setting()
        self.assertIsInstance(setting.start_time, datetime)
        self.assertEqual('Asia/Jakarta', setting.start_time.tzinfo.zone)
        self.assertEqual('2023-02-01 00:00:00', setting.start_time.strftime('%Y-%m-%d %H:%M:%S'))

    def test_promo_code_end_time(self):
        promo_code = PromoCodeFactory(
            start_date='2023-02-01 00:00:00',
            end_date='2023-02-20 23:59:59'
        )
        self.setting.parameters = {
            'promo_code_id': promo_code.id,
            'start_time': '2023-03-01 00:00:00',
            'end_time': '2023-03-01 00:00:00',
        }
        self.setting.save()
        setting = get_loan_prize_chance_setting()
        self.assertIsInstance(setting.end_time, datetime)
        self.assertEqual('Asia/Jakarta', setting.end_time.tzinfo.zone)
        self.assertEqual('2023-02-20 23:59:59', setting.end_time.strftime('%Y-%m-%d %H:%M:%S'))

    def test_chance_per_promo_code(self):
        setting = get_loan_prize_chance_setting()
        self.assertEqual(1, setting.chance_per_promo_code)

        self.setting.parameters['chance_per_promo_code'] = 2
        self.setting.save()
        setting = get_loan_prize_chance_setting()
        self.assertEqual(2, setting.chance_per_promo_code)


@mock.patch('juloserver.loan.tasks.loan_prize_chance.calculate_loan_prize_chances.delay')
class TestHandleLoanPrizeChanceOnLoanStatusChange(TestCase):
    def setUp(self):
        loan_prize_chance._loan_prize_chance_setting = None
        self.setting = FeatureSettingFactory(
            feature_name='marketing_loan_prize_chance',
            is_active=True,
            parameters={
                'minimum_amount': 1000000,
                'start_time': '2023-10-13 00:00:00',
                'end_time': '2023-11-30 23:59:59',
            }
        )
        self.product_lookup = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=1)
        )
        self.loan = LoanFactory(
            product=self.product_lookup,
            loan_status=StatusLookupFactory(status_code=220),
        )

    @pytest.mark.skip(reason="Flaky")
    def test_eligible_loan(self, mock_calculate_loan_prize_chances):
        handle_loan_prize_chance_on_loan_status_change(self.loan)
        force_run_on_commit_hook()

        mock_calculate_loan_prize_chances.assert_called_once_with(self.loan.id)

    def test_not_eligible_loan(self, mock_calculate_loan_prize_chances):
        self.loan.update_safely(loan_status_id=211)
        handle_loan_prize_chance_on_loan_status_change(self.loan)
        force_run_on_commit_hook()

        mock_calculate_loan_prize_chances.assert_not_called()

    def test_not_eligible_loan_product(self, mock_calculate_loan_prize_chances):
        invalid_product = ProductLookupFactory(
            product_line=ProductLineFactory(product_line_code=9999)
        )
        self.loan.update_safely(product=invalid_product)
        handle_loan_prize_chance_on_loan_status_change(self.loan)
        force_run_on_commit_hook()

        mock_calculate_loan_prize_chances.assert_not_called()

    def test_not_eligible_wrong_loan_diff_cdate(self, mock_calculate_loan_prize_chances):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 10, 12, 0, 0, 0)
            loan = LoanFactory(
                product=self.product_lookup,
                loan_status=StatusLookupFactory(status_code=220),
            )

        handle_loan_prize_chance_on_loan_status_change(loan)
        force_run_on_commit_hook()

        mock_calculate_loan_prize_chances.assert_not_called()


@mock.patch('juloserver.loan.services.loan_prize_chance.get_prize_chance_cache')
@mock.patch('juloserver.loan.services.loan_prize_chance.calculate_customer_prize_chances')
class TestStoreLoanPrizeChances(TestCase):
    def setUp(self):
        self.loan = LoanFactory()

    def test_new_loan(self, mock_calculate_customer_chance, mock_get_cache):
        mock_calculate_customer_chance.return_value = 100

        ret_val = store_loan_prize_chances(self.loan, 2)
        self.assertIsInstance(ret_val, LoanPrizeChance)
        self.assertEqual(2, ret_val.chances)
        self.assertEqual(self.loan.id, ret_val.loan_id)
        self.assertEqual(self.loan.customer_id, ret_val.customer_id)

        mock_calculate_customer_chance.assert_called_once_with(self.loan.customer_id)
        mock_get_cache.return_value.set_chances.assert_called_once_with(self.loan.customer_id, 100)

    def test_existing_loan(self, mock_calculate_customer_chance, mock_get_cache):
        LoanPrizeChance.objects.create(
            loan=self.loan,
            customer=self.loan.customer,
            chances=10,
        )

        ret_val = store_loan_prize_chances(self.loan, 2)
        self.assertEqual(10, ret_val.chances)
        mock_calculate_customer_chance.assert_not_called()
        mock_get_cache.assert_not_called()

    def test_chances_less_than_1(self, mock_calculate_customer_chance, mock_get_cache):
        with self.assertRaises(ValueError) as context:
            store_loan_prize_chances(self.loan, 0)

        self.assertEqual(0, LoanPrizeChance.objects.count())
        mock_calculate_customer_chance.assert_not_called()
        mock_get_cache.assert_not_called()


class TestCalculateCustomerPrizeChances(TestCase):
    def setUp(self):
        loan_prize_chance._loan_prize_chance_setting = None
        self.setting = FeatureSettingFactory(
            feature_name='marketing_loan_prize_chance',
            is_active=True,
            parameters={
                'minimum_amount': 1000000,
                'start_time': '2023-10-13 00:00:00',
                'end_time': '2023-11-30 23:59:59',
                'campaign_start_date': '2023-10-13',
                'campaign_end_date': '2023-11-30',
                'campaign_period': 'October 2023'
            }
        )
        self.customer = CustomerFactory(id=1)
        self.account = AccountFactory(customer=self.customer)

    def test_calculate_prize_chances(self):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 10, 14, 0, 0, 0)
            LoanPrizeChanceFactory.create_batch(
                3,
                customer_id=1,
                loan_id=Iterator([1, 2, 3]),
                chances=Iterator([1, 1, 3]),
            )
            # Other customer data
            LoanPrizeChanceFactory(
                customer_id=2,
                loan_id=4,
                chances=10,
            )
            EarlyHiSeasonTicketCountFactory(
                account_id=self.account.id,
                total_ticket_count=5,
                campaign_start_date='2023-10-13',
                campaign_end_date='2023-11-30',
                campaign_period='October 2023'
            )

        # outside of time range
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 10, 12, 0, 0, 0)
            LoanPrizeChanceFactory(
                customer_id=1,
                loan_id=5,
                chances=1,
            )

        ret_val = calculate_customer_prize_chances(1)
        self.assertEqual(5, ret_val)

    def test_no_data(self):
        ret_val = calculate_customer_prize_chances(1)
        self.assertEqual(0, ret_val)


@mock.patch('juloserver.loan.services.loan_prize_chance.get_prize_chance_cache')
@mock.patch('juloserver.loan.services.loan_prize_chance.calculate_customer_prize_chances')
class TestGetCustomerPrizeChances(TestCase):
    def test_no_caches(self, mock_calculate_customer_chances, mock_get_cache):
        mock_get_cache.return_value.get_chances.return_value = None
        mock_calculate_customer_chances.return_value = 10

        ret_val = get_customer_prize_chances(1)
        self.assertEqual(10, ret_val)

        mock_get_cache.return_value.set_chances.assert_called_once_with(1, 10)
        mock_calculate_customer_chances.assert_called_once_with(1)

    def test_with_caches(self, mock_calculate_customer_chances, mock_get_cache):
        mock_get_cache.return_value.get_chances.return_value = 5
        mock_calculate_customer_chances.return_value = 10

        ret_val = get_customer_prize_chances(1)
        self.assertEqual(5, ret_val)

        mock_get_cache.return_value.set_chances.assert_not_called()
        mock_calculate_customer_chances.assert_not_called()


@mock.patch('juloserver.loan.services.loan_prize_chance.get_redis_client')
@mock.patch('juloserver.loan.services.loan_prize_chance.get_loan_prize_chance_setting')
class TestPrizeChanceCache(TestCase):
    def test_construct(self, mock_get_setting, mock_get_redis_client):
        ret_val = get_prize_chance_cache()
        self.assertIsInstance(ret_val, PrizeChanceCache)
        mock_get_setting.assert_called_once_with()
        mock_get_redis_client.assert_called_once_with()

    def test_set_chances(self, mock_get_setting, mock_get_redis_client):
        now = timezone.localtime(timezone.now())
        mock_get_setting.return_value.end_time = timezone.localtime(datetime(2023, 11, 30, 23, 59, 59))
        cache = get_prize_chance_cache()

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = timezone.localtime(
                datetime(now.year, now.month, now.day, 5, 0, 0)
            )
            cache.set_chances(1, 10)

        mock_get_redis_client.return_value.set.assert_called_once_with(
            'loan_prize_chances:1', 10, timedelta(hours=1),
        )

    def test_get_chances(self, mock_get_setting, mock_get_redis_client):
        mock_get_redis_client.return_value.get.return_value = 10
        cache = get_prize_chance_cache()
        ret_val = cache.get_chances(1)

        self.assertEqual(10, ret_val)
        mock_get_redis_client.return_value.get.assert_called_once_with('loan_prize_chances:1')


class TestAddPrizeChancesContext(SimpleTestCase):
    def test_not_string(self):
        ret_val = add_prize_chances_context(1, {})
        self.assertEqual(1, ret_val)

    def test_expected_flow(self):
        url = 'https://julo.co.id/prize?in_app=True'
        ret_val = add_prize_chances_context(url, {'prize_chances': 10})
        self.assertEqual('https://julo.co.id/prize?in_app=True&chances=10', ret_val)

    def test_no_query_string(self):
        url = 'https://julo.co.id/prize'
        ret_val = add_prize_chances_context(url, {'prize_chances': 10})
        self.assertEqual('https://julo.co.id/prize?chances=10', ret_val)

    def test_using_fragment(self):
        url = 'https://julo.co.id/prize#fragment'
        ret_val = add_prize_chances_context(url, {'prize_chances': 10})
        self.assertEqual('https://julo.co.id/prize?chances=10#fragment', ret_val)

    def test_using_deeplink(self):
        url = 'julo://prize'
        ret_val = add_prize_chances_context(url, {'prize_chances': 10})
        self.assertEqual('julo://prize?chances=10', ret_val)
