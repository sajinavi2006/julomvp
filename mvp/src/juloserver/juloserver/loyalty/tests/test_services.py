import ast
import mock
from datetime import datetime, date, timedelta, timezone
from operator import attrgetter
from fakeredis import FakeStrictRedis

from django.utils import timezone
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from factory import Iterator

from juloserver.payment_point.constants import TransactionMethodCode, SepulsaProductType, \
    SepulsaProductCategory
from juloserver.loyalty.services.services import (
    calculate_expiry_date,
    get_unexpired_point_earnings,
    calculate_will_expired_remaining_points,
    expire_per_customer_point_earning,
)
from juloserver.loyalty.services.mission_related import (
    GeneralMissionCriteriaChecking,
    ResetMissionProgressChecking,
    TransactionMissionCriteriaChecking,
    TransactionMissionProgressService,
    populate_whitelist_mission_criteria_on_redis,
    delete_whitelist_mission_criteria_on_redis,
)
from juloserver.loyalty.models import (
    MissionProgress,
    MissionProgressHistory,
    PointHistory,
    PointEarning,
    MissionConfig,
    MissionTargetProgress,
)
from juloserver.loyalty.constants import (
    MissionCategoryConst,
    MissionCriteriaTypeConst,
    MissionCriteriaValueConst,
    MissionConfigTargetUserConst,
    MissionProgressStatusConst,
    MissionRewardTypeConst,
    MissionCriteriaWhitelistStatusConst,
    MissionTargetTypeConst,
    FeatureNameConst,
    PointRedeemReferenceTypeConst,
    RedemptionMethodErrorCode,
)

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    LoanFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    FeatureSettingFactory,
)
from juloserver.payment_point.tests.factories import (
    XfersProductFactory,
    XfersEWalletTransactionFactory,
    AYCProductFactory,
    AYCEWalletTransactionFactory,
)
from juloserver.julo.services2.redis_helper import RedisHelper
from juloserver.loyalty.tests.factories import (
    LoyaltyPointFactory,
    PointEarningFactory,
    MissionCriteriaFactory,
    MissionConfigFactory,
    MissionConfigCriteriaFactory,
    MissionProgressFactory,
    MissionRewardFactory,
    MissionTargetFactory,
    MissionConfigTargetFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.account.constants import (
    AccountConstant,
)
from juloserver.loyalty.services.mission_related import CalculateMissionPointRewards
from juloserver.loyalty.services.point_redeem_services import (
    is_eligible_redemption_method,
    get_transfer_method_pricing_info,
)


class MockStrictRedisHelper(RedisHelper):
    def __init__(self):
        self.client = FakeStrictRedis(decode_responses=True)
        self.client.ping()


class TestExpiryPointEarning(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer_point = LoyaltyPointFactory(
            customer_id=self.customer.id,
            total_point=60000
        )
        self.point_earnings_1 = PointEarningFactory.create_batch(
            5,
            customer_id=self.customer.id,
            points=Iterator([2000, 3000, 5000, 6000, 10000]),
            expiry_date=date(2025, 1, 1)
        )
        self.point_earnings_2 = PointEarningFactory.create_batch(
            5,
            customer_id=self.customer.id,
            points=Iterator([4000, 5000, 7000, 9000, 9000]),
            expiry_date=date(2025, 7, 1)
        )

    @patch('django.utils.timezone.now')
    def test_calculate_expiry_date_first_half_of_year(self, mock_now):
        mock_now.return_value = datetime(2024, 3, 28, 12, 23, 56)

        expiry_date = calculate_expiry_date()
        self.assertEqual(expiry_date, date(2025, 7, 1))

    @patch('django.utils.timezone.now')
    def test_calculate_expiry_date_second_half_of_year(self, mock_now):
        mock_now.return_value = datetime(2024, 8, 21, 12, 23, 56)

        expiry_date = calculate_expiry_date()
        self.assertEqual(expiry_date, date(2026, 1, 1))

    def test_get_unexpired_point_earnings_1(self):
        expiry_date = date(2025, 1, 1)
        will_expired, available = get_unexpired_point_earnings(self.customer, expiry_date)
        expected_will_expired_ids = list(map(attrgetter("id"), self.point_earnings_1))
        expected_available_ids = list(map(attrgetter("id"), self.point_earnings_2))
        expected_will_expired = PointEarning.objects.filter(
            pk__in=expected_will_expired_ids
        )
        expected_available = PointEarning.objects.filter(
            pk__in=expected_available_ids
        )
        self.assertEqual(list(will_expired), list(expected_will_expired))
        self.assertEqual(list(available), list(expected_available))

    def test_get_unexpired_point_earnings_2(self):
        expiry_date = date(2025, 7, 1)
        will_expired, available = get_unexpired_point_earnings(self.customer, expiry_date)

        expected_will_expired_ids = list()
        expected_will_expired_ids += list(map(attrgetter("id"), self.point_earnings_1))
        expected_will_expired_ids += list(map(attrgetter("id"), self.point_earnings_2))
        expected_available_ids = list()
        expected_will_expired = PointEarning.objects.filter(
            pk__in=expected_will_expired_ids
        )
        expected_available = PointEarning.objects.filter(
            pk__in=expected_available_ids
        )
        self.assertEqual(list(will_expired), list(expected_will_expired))
        self.assertEqual(list(available), list(expected_available))

    @patch("juloserver.loyalty.services.services.get_unexpired_point_earnings")
    @patch('django.utils.timezone.now')
    def test_calculate_will_expired_remaining_points(self, mock_now,
                                                     mock_get_unexpired_point_earnings):
        will_expired_ids = list(map(attrgetter("id"), self.point_earnings_1))
        will_expired = PointEarning.objects.filter(pk__in=will_expired_ids)

        available_ids = list(map(attrgetter("id"), self.point_earnings_2))
        available = PointEarning.objects.filter(pk__in=available_ids)

        mock_now.return_value = datetime(2025, 1, 1, 12, 23, 56)
        mock_get_unexpired_point_earnings.return_value = will_expired, available

        # used < expired
        self.customer_point.update_safely(total_point=40000)
        points = calculate_will_expired_remaining_points(self.customer_point, available)
        self.assertEqual(points, 6000)

        # used > expired
        self.customer_point.update_safely(total_point=20000)
        points = calculate_will_expired_remaining_points(self.customer_point, available)
        self.assertEqual(points, 0)

    def test_expire_per_customer_point_earning_1(self):
        self.customer_point.update_safely(total_point=40000)
        expire_per_customer_point_earning(self.customer, date(2025, 1, 1))

        self.customer_point.refresh_from_db()
        self.assertEqual(self.customer_point.total_point, 34000)

        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()

        self.assertEqual(point_history.old_point, 40000)
        self.assertEqual(point_history.new_point, 34000)
        self.assertEqual(point_history.change_reason, 'Kedaluwarsa')

        will_expired_ids = list(map(attrgetter("id"), self.point_earnings_1))
        will_expired = PointEarning.objects.filter(pk__in=will_expired_ids)

        for point_earning in will_expired:
            self.assertTrue(point_earning.is_expired)

    def test_expire_per_customer_point_earning_2(self):
        self.customer_point.update_safely(total_point=20000)
        expire_per_customer_point_earning(self.customer, date(2025, 1, 1))

        self.customer_point.refresh_from_db()
        self.assertEqual(self.customer_point.total_point, 20000)

        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNone(point_history)

        will_expired_ids = list(map(attrgetter("id"), self.point_earnings_1))
        will_expired = PointEarning.objects.filter(pk__in=will_expired_ids)

        for point_earning in will_expired:
            self.assertTrue(point_earning.is_expired)

    def test_expire_per_customer_point_earning_3(self):
        self.customer_point.update_safely(total_point=34000)
        expire_per_customer_point_earning(self.customer, date(2025, 7, 1))

        self.customer_point.refresh_from_db()
        self.assertEqual(self.customer_point.total_point, 0)

        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()

        self.assertEqual(point_history.old_point, 34000)
        self.assertEqual(point_history.new_point, 0)
        self.assertEqual(point_history.change_reason, 'Kedaluwarsa')

        will_expired_ids = list(map(attrgetter("id"), self.point_earnings_2))
        will_expired = PointEarning.objects.filter(pk__in=will_expired_ids)

        for point_earning in will_expired:
            self.assertTrue(point_earning.is_expired)


class TestCalculateMissionPointRewards(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.mission_config = MissionConfigFactory()
        self.set_up_mission_rewards()

    def set_up_mission_rewards(self):
        self.general_reward = MissionRewardFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 3000}
        )
        self.fixed_transaction_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 2000}
        )
        self.percentage_transaction_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.PERCENTAGE,
            value={
                MissionRewardTypeConst.MAX_POINTS: 5000,
                MissionRewardTypeConst.PERCENTAGE: 50
            }
        )
        self.fixed_referral_reward = MissionRewardFactory(
            category=MissionCategoryConst.REFERRAL,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 4000}
        )
        self.percentage_referral_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.PERCENTAGE,
            value={
                MissionRewardTypeConst.MAX_POINTS: 10000,
                MissionRewardTypeConst.PERCENTAGE: 80
            }
        )

    def test_mission_reward_general(self):
        self.mission_config.update_safely(reward=self.general_reward)
        service = CalculateMissionPointRewards(self.mission_config)
        self.assertEqual(service.calculate(), 3000)

    def test_fixed_transaction_reward(self):
        self.mission_config.update_safely(reward=self.fixed_transaction_reward)
        service = CalculateMissionPointRewards(self.mission_config)
        self.assertEqual(service.calculate(), 2000)

    def test_percentage_transaction_reward(self):
        self.mission_config.update_safely(reward=self.percentage_transaction_reward)
        service = CalculateMissionPointRewards(self.mission_config)
        self.assertEqual(service.calculate(), 5000)

    def test_fixed_referral_reward(self):
        self.mission_config.update_safely(reward=self.fixed_referral_reward)
        service = CalculateMissionPointRewards(self.mission_config)
        self.assertEqual(service.calculate(), 4000)

    def test_percentage_referral_reward(self):
        self.mission_config.update_safely(reward=self.percentage_referral_reward)
        service = CalculateMissionPointRewards(self.mission_config)
        self.assertEqual(service.calculate(), 10000)


class TestResetMissionProgressChecking(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.set_up_missions()
        self.set_up_mission_progresses()

    def set_up_missions(self):
        self.mission_config = MissionConfigFactory()
        self.mission_config_1 = MissionConfigFactory(
            max_repeat=1, target_recurring=2, is_active=True, repetition_delay_days=5
        )
        self.mission_config_2 = MissionConfigFactory(
            max_repeat=2, target_recurring=4, is_active=True, repetition_delay_days=4
        )
        self.mission_config_3 = MissionConfigFactory(
            max_repeat=3, target_recurring=3, is_active=True, repetition_delay_days=3
        )

    def set_up_mission_progresses(self):
        self.mission_progress_1 = MissionProgressFactory(
            mission_config=self.mission_config_1,
            customer_id=self.customer.id,
            recurring_number=1,
            status=MissionProgressStatusConst.IN_PROGRESS
        )
        self.mission_progress_2 = MissionProgressFactory(
            mission_config=self.mission_config_2,
            customer_id=self.customer.id,
            recurring_number=4,
            status=MissionProgressStatusConst.COMPLETED
        )
        self.mission_progress_3 = MissionProgressFactory(
            mission_config=self.mission_config_3,
            recurring_number=3,
            repeat_number=2,
            customer_id=self.customer.id,
            status=MissionProgressStatusConst.COMPLETED
        )

    def test_get_customer_latest_mission_progress(self):
        service = ResetMissionProgressChecking(self.mission_config, self.customer)
        self.assertIsNone(service.get_customer_latest_mission_progress())

        service = ResetMissionProgressChecking(self.mission_config_1, self.customer)
        self.assertEqual(service.get_customer_latest_mission_progress(), self.mission_progress_1)

        service = ResetMissionProgressChecking(self.mission_config_2, self.customer)
        self.assertEqual(service.get_customer_latest_mission_progress(), self.mission_progress_2)

    def test_not_existing_mission_progress(self):
        service = ResetMissionProgressChecking(self.mission_config, self.customer)
        self.assertTrue(service.check_not_existing_mission_progress())

        service = ResetMissionProgressChecking(self.mission_config_1, self.customer)
        self.assertFalse(service.check_not_existing_mission_progress())

        service = ResetMissionProgressChecking(self.mission_config_2, self.customer)
        self.assertFalse(service.check_not_existing_mission_progress())

    def test_latest_mission_progress_status(self):
        service = ResetMissionProgressChecking(self.mission_config_1, self.customer)
        self.assertFalse(service.check_latest_mission_progress_status())

        service = ResetMissionProgressChecking(self.mission_config_2, self.customer)
        self.assertTrue(service.check_latest_mission_progress_status())

    def test_latest_mission_progress_repeat_number(self):
        service = ResetMissionProgressChecking(self.mission_config_2, self.customer)

        self.mission_progress_2.update_safely(repeat_number=4)
        service.latest_mission_progress.refresh_from_db()
        self.assertFalse(service.check_latest_mission_progress_repeat_number())

        self.mission_progress_2.update_safely(repeat_number=1)
        service.latest_mission_progress.refresh_from_db()
        self.assertTrue(service.check_latest_mission_progress_repeat_number())

    def test_latest_mission_progress_repeat_delay(self):
        service = ResetMissionProgressChecking(self.mission_config_2, self.customer)

        completion_date = timezone.localtime(timezone.now()).today() - timedelta(days=3)
        self.mission_progress_2.update_safely(completion_date=completion_date)
        service.latest_mission_progress.refresh_from_db()
        self.assertFalse(service.check_latest_mission_progress_repeat_delay())

        completion_date = timezone.localtime(timezone.now()).today() - timedelta(days=10)
        self.mission_progress_2.update_safely(completion_date=completion_date)
        service.latest_mission_progress.refresh_from_db()
        self.assertTrue(service.check_latest_mission_progress_repeat_delay())

    def test_resetable_mission_progress_failed_status(self):
        mission_config = MissionConfigFactory(
            max_repeat=3, target_recurring=3, is_active=True, repetition_delay_days=3
        )
        MissionProgressFactory(
            mission_config=mission_config,
            recurring_number=2,
            repeat_number=2,
            customer_id=self.customer.id,
            status=MissionProgressStatusConst.EXPIRED
        )
        service = ResetMissionProgressChecking(mission_config, self.customer)
        self.assertFalse(service.check_latest_mission_progress_resetable())

    def test_resetable_mission_progress_failed_repeat_number(self):
        mission_config = MissionConfigFactory(
            max_repeat=3, target_recurring=3, is_active=True, repetition_delay_days=3
        )
        MissionProgressFactory(
            mission_config=mission_config,
            recurring_number=3,
            repeat_number=3,
            customer_id=self.customer.id,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=timezone.localtime(timezone.now()).today() - timedelta(days=10)
        )
        service = ResetMissionProgressChecking(mission_config, self.customer)
        self.assertFalse(service.check_latest_mission_progress_resetable())

    def test_resetable_mission_progress_failed_repeat_delay(self):
        mission_config = MissionConfigFactory(
            max_repeat=3, target_recurring=3, is_active=True, repetition_delay_days=3
        )
        MissionProgressFactory(
            mission_config=mission_config,
            recurring_number=3,
            repeat_number=3,
            customer_id=self.customer.id,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=timezone.localtime(timezone.now()).today() - timedelta(days=1)
        )
        service = ResetMissionProgressChecking(mission_config, self.customer)
        self.assertFalse(service.check_latest_mission_progress_resetable())

    def test_resetable_mission_progress_passed(self):
        mission_config = MissionConfigFactory(
            max_repeat=3, target_recurring=3, is_active=True, repetition_delay_days=3
        )
        MissionProgressFactory(
            mission_config=mission_config,
            recurring_number=3,
            repeat_number=2,
            customer_id=self.customer.id,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=timezone.localtime(timezone.now()).today() - timedelta(days=5)
        )
        service = ResetMissionProgressChecking(mission_config, self.customer)
        self.assertTrue(service.check_latest_mission_progress_resetable())


class TestGeneralMissionCriteriaChecking(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=1000000,
            set_limit=1000000,
            available_limit=600000,
            used_limit=400000
        )
        self.mission_config = MissionConfigFactory()
        self.mission_criteria_1 = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.TARGET_USER,
            value={'target_user': MissionConfigTargetUserConst.FTC}
        )
        self.mission_criteria_2 = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.TARGET_USER,
            value={'target_user': MissionConfigTargetUserConst.REPEAT}
        )
        self.mission_criteria_3 = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.UTILIZATION_RATE,
            value={'utilization_rate': 20}
        )
        self.mission_criteria_4 = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.UTILIZATION_RATE,
            value={'utilization_rate': 80}
        )
        self.mission_criteria_5 = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.WHITELIST_CUSTOMERS,
            value={
                'status': MissionCriteriaWhitelistStatusConst.PROCESS,
                'duration': 2,
                'upload_url': 'loyalty_customers_whitelist_5'
            }
        )
        self.fake_redis = MockStrictRedisHelper()

    def test_get_customer_target_user_1(self):
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        target_user = service.get_customer_target_user()
        self.assertEqual(target_user, 'FTC')

        LoanFactory(account=self.account, customer=self.customer)
        target_user = service.get_customer_target_user()
        self.assertEqual(target_user, 'REPEAT')

    def test_get_customer_target_user_2(self):
        loan_1 = LoanFactory(account=self.account, customer=self.customer)
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer, loan_1)
        target_user = service.get_customer_target_user()
        self.assertEqual(target_user, 'FTC')

        loan_2 = LoanFactory(account=self.account, customer=self.customer)
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer, loan_2)
        target_user = service.get_customer_target_user()
        self.assertEqual(target_user, 'REPEAT')

    def test_get_customer_utilization_rate(self):
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        utilization_rate = service.get_customer_utilization_rate()
        self.assertTrue(utilization_rate, 40)

    def test_check_target_user_1(self):
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertFalse(service.check_target_user(self.mission_criteria_2))

        LoanFactory(account=self.account, customer=self.customer)
        self.assertTrue(service.check_target_user(self.mission_criteria_2))

    def test_check_target_user_2(self):
        loan_1 = LoanFactory(account=self.account, customer=self.customer)
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer, loan_1)
        self.assertFalse(service.check_target_user(self.mission_criteria_2))

        loan_2 = LoanFactory(account=self.account, customer=self.customer)
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer, loan_2)
        self.assertTrue(service.check_target_user(self.mission_criteria_2))

    def test_check_utilization_rate(self):
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertTrue(service.check_utilization_rate(self.mission_criteria_3))

        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertFalse(service.check_utilization_rate(self.mission_criteria_4))

    @mock.patch('juloserver.loyalty.services.mission_related.get_redis_client')
    @mock.patch('juloserver.loyalty.tasks.trigger_upload_whitelist_mission_criteria')
    def test_check_whitelist_customer_file(self, mock_trigger_upload_task, mock_redis_client):
        mock_redis_client.return_value = self.fake_redis
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_5
        )

        redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(
            self.mission_criteria_5.id
        )
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertFalse(service.check_whitelist_customers_file(self.mission_criteria_5))
        mock_trigger_upload_task.delay.assert_called_once()

        self.fake_redis.sadd(redis_key, {str(self.customer.id)})
        self.assertTrue(service.check_whitelist_customers_file(self.mission_criteria_5))

    def test_check_mission_config_no_criteria(self):
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertTrue(service.check())

    @mock.patch('juloserver.loyalty.services.mission_related.get_redis_client')
    def test_check_all_general_criteria_1(self, mock_redis_client):
        mock_redis_client.return_value.exists.return_value = True
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_1
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_3
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_5
        )
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertTrue(service.check())

    @mock.patch('juloserver.loyalty.services.mission_related.get_redis_client')
    def test_check_all_general_criteria_2(self, mock_redis_client):
        mock_redis_client.return_value.exists.return_value = True
        LoanFactory(account=self.account, customer=self.customer)
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_2
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_3
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config,
            criteria=self.mission_criteria_5
        )
        service = GeneralMissionCriteriaChecking(self.mission_config, self.customer)
        self.assertTrue(service.check())


class MissionConfigCriteriaBaseSetup:
    def set_up_missions(self):
        self.mission_config_1 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            target_recurring=2,
            max_repeat=2,
            is_active=True,
            repetition_delay_days=3
        )
        self.mission_config_2 = MissionConfigFactory(category=MissionCategoryConst.TRANSACTION)
        self.mission_config_3 = MissionConfigFactory(category=MissionCategoryConst.GENERAL)
        self.mission_config_4 = MissionConfigFactory(category=MissionCategoryConst.TRANSACTION)

    def set_up_criteria(self):
        self.mission_criteria_1 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TENOR,
            value={'tenor': 5}
        )
        self.mission_criteria_2 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.MINIMUM_LOAN_AMOUNT,
            value={'minimum_loan_amount': 1500000}
        )
        self.mission_criteria_3 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                'transaction_methods': [{
                    'transaction_method_id': 2
                }]
            }
        )
        self.mission_criteria_4 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                'transaction_methods': [{
                    'transaction_method_id': 3,
                    'categories': ['pulsa']
                }]
            }
        )
        self.mission_criteria_5 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                'transaction_methods': [{
                    'transaction_method_id': 5,
                    'categories': ['DANA']
                }]
            }
        )
        self.mission_criteria_6 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                'transaction_methods': [{
                    'transaction_method_id': 5,
                    'categories': ['ShopeePay', 'OVO']
                }]
            }
        )

    def set_up_loan(self):
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

    def set_up_sepulsa_loan(self):
        self.sepulsa_product = SepulsaProductFactory(category='pulsa')
        self.sepulsa_loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.PULSA_N_PAKET_DATA.code
        )
        self.sepulsa_transaction = SepulsaTransactionFactory(
            customer=self.customer,
            loan=self.sepulsa_loan,
            product=self.sepulsa_product
        )

    def set_up_xfers_ewallet_loan(self):
        self.xfers_ewallet_product = XfersProductFactory(
            sepulsa_product=SepulsaProductFactory(),
            category='DANA'
        )
        self.xfers_ewallet_loan = LoanFactory(
            customer=self.customer,
            loan_amount=500000,
            loan_duration=3,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code
        )
        self.xfers_ewallet_transaction = XfersEWalletTransactionFactory(
            customer=self.customer,
            loan=self.xfers_ewallet_loan,
            xfers_product=self.xfers_ewallet_product
        )

    def set_up_ayc_ewallet_loan(self):
        self.ayc_ewallet_product = AYCProductFactory(
            sepulsa_product=SepulsaProductFactory(),
            category='ShopeePay'
        )
        self.ayc_ewallet_loan = LoanFactory(
            customer=self.customer,
            loan_amount=200000,
            loan_duration=2,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code
        )
        self.ayc_ewallet_transaction = AYCEWalletTransactionFactory(
            customer=self.customer,
            loan=self.ayc_ewallet_loan,
            ayc_product=self.ayc_ewallet_product
        )


class TestTransactionMissionCriteriaChecking(TestCase, MissionConfigCriteriaBaseSetup):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=1000000,
            set_limit=1000000,
            available_limit=600000,
            used_limit=400000
        )

        self.set_up_missions()
        self.set_up_criteria()
        self.set_up_loan()

    def test_check_tenor(self):
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_1
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertTrue(checking.check_tenor(self.mission_criteria_1))

        self.loan.loan_duration = 4
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertFalse(checking.check_tenor(self.mission_criteria_1))

    def test_check_minimum_loan_amount(self):
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_2
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertTrue(checking.check_minimum_loan_amount(self.mission_criteria_2))

        self.loan.loan_amount = 2000000
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertTrue(checking.check_minimum_loan_amount(self.mission_criteria_2))

        self.loan.loan_amount = 1499999
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertFalse(checking.check_minimum_loan_amount(self.mission_criteria_2))

    def test_check_transaction_method_1(self):
        """ For Kirim Dana/Tarik Dana transaction """
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_3,
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertTrue(checking.check_transaction_method(self.mission_criteria_3))

        self.loan.transaction_method_id = 1
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_3))

    def test_check_transaction_method_2(self):
        """ For sepulsa transaction (method != Dompet Digital) """
        self.set_up_sepulsa_loan()
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_4,
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.sepulsa_loan)
        self.assertTrue(checking.check_transaction_method(self.mission_criteria_4))

        self.sepulsa_loan.transaction_method_id = 2
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.sepulsa_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_4))

        self.sepulsa_loan.transaction_method_id = 3
        self.sepulsa_product.category = ''
        self.sepulsa_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.sepulsa_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_4))

        self.sepulsa_product.category = 'ShopeePay'
        self.sepulsa_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.sepulsa_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_4))

    def test_check_transaction_method_3(self):
        """ For xfers transaction (method == Dompet Digital, product == Xfers) """
        self.set_up_xfers_ewallet_loan()
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_5,
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.xfers_ewallet_loan)
        self.assertTrue(checking.check_transaction_method(self.mission_criteria_5))

        self.xfers_ewallet_loan.transaction_method_id = 2
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.xfers_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_5))

        self.xfers_ewallet_loan.transaction_method_id = 5
        self.xfers_ewallet_product.category = ''
        self.xfers_ewallet_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.xfers_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_5))

        self.xfers_ewallet_product.category = 'ShopeePay'
        self.xfers_ewallet_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.xfers_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_5))

    def test_check_transaction_method_4(self):
        """ For xfers transaction (method == Dompet Digital, product == AyoConnect) """
        self.set_up_ayc_ewallet_loan()
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_6,
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.ayc_ewallet_loan)
        self.assertTrue(checking.check_transaction_method(self.mission_criteria_6))

        self.ayc_ewallet_loan.transaction_method_id = 2
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.ayc_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_6))

        self.ayc_ewallet_loan.transaction_method_id = 5
        self.ayc_ewallet_product.category = ''
        self.ayc_ewallet_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.ayc_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_6))

        self.ayc_ewallet_product.category = 'LinkAja'
        self.ayc_ewallet_product.save()
        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.ayc_ewallet_loan)
        self.assertFalse(checking.check_transaction_method(self.mission_criteria_6))

    def test_check_all(self):
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_1,
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_2,
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_3,
        )

        checking = TransactionMissionCriteriaChecking(self.mission_config_1, self.loan)
        self.assertTrue(checking.check())


class TestTransactionMissionProgressService(TestCase, MissionConfigCriteriaBaseSetup):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=1000000,
            set_limit=1000000,
            available_limit=600000,
            used_limit=400000
        )
        self.loyalty_point = LoyaltyPointFactory(customer_id=self.customer.id)
        self.set_up_sepulsa_loan()

    def set_up_mission_data(self):
        self.mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type='Fixed',
            value=10000,
        )
        self.mission_config_1 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=3,
        )
        self.mission_config_2 = MissionConfigFactory(
            title="Top Up GoPay 5 Kali",
            category=MissionCategoryConst.TRANSACTION,
            reward=self.mission_reward,
            target_recurring=2,
            max_repeat=3,
            repetition_delay_days=1
        )
        self.mission_config_3 = MissionConfigFactory(category=MissionCategoryConst.TRANSACTION)

        self.in_progress_m_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            recurring_number=1,
            repeat_number=2,
            is_latest=True,
            status=MissionProgressStatusConst.IN_PROGRESS,
            reference_data={'loan_ids': ['-123']}
        )
        self.complete_m_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_config_2,
            recurring_number=2,
            repeat_number=1,
            is_latest=True,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime(2024, 3, 8, 0, 0, 0, tzinfo=timezone.utc)
        )

        self.in_progress_m_progress.save()
        self.complete_m_progress.save()
        self.mission_config_3.save()

    def set_up_mission_config_criteria(self):
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_1,
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_2,
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config_1,
            criteria=self.mission_criteria_3,
        )

        MissionConfigCriteriaFactory(
            config=self.mission_config_2,
            criteria=self.mission_criteria_1,
        )
        MissionConfigCriteriaFactory(
            config=self.mission_config_2,
            criteria=self.mission_criteria_2,
        )

    @mock.patch('django.utils.timezone.localtime')
    def test_classify_mission_configs(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        m_config_qs = MissionConfig.objects.get_valid_mission_config_queryset().filter(
            category=MissionCategoryConst.TRANSACTION,
        )
        m_config_ids = list(m_config_qs.values_list('id', flat=True))
        m_progresses_dict = service.get_and_blocking_exists_mission_progresses(m_config_ids)
        new_m_configs, repeat_m_configs, in_progress_m_configs = \
            service.classify_mission_configs(m_config_qs, m_progresses_dict)

        self.assertEqual(len(new_m_configs), 1)
        self.assertEqual(len(repeat_m_configs), 1)
        self.assertEqual(len(in_progress_m_configs), 1)

        self.assertEqual(new_m_configs[0]['m_config'].id, self.mission_config_3.id)

        self.assertEqual(repeat_m_configs[0]['m_config'].id, self.mission_config_2.id)
        self.assertEqual(repeat_m_configs[0]['m_progress'].id, self.complete_m_progress.id)

        self.assertEqual(in_progress_m_configs[0]['m_config'].id, self.mission_config_1.id)
        self.assertEqual(in_progress_m_configs[0]['m_progress'].id, self.in_progress_m_progress.id)

    @mock.patch('django.utils.timezone.localtime')
    def test_create_new_mission_progresses(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        m_config_qs = MissionConfig.objects.get_valid_mission_config_queryset().filter(
            category=MissionCategoryConst.TRANSACTION,
        )
        m_config_ids = list(m_config_qs.values_list('id', flat=True))
        m_progresses_dict = service.get_and_blocking_exists_mission_progresses(m_config_ids)
        new_m_configs, _, _ = \
            service.classify_mission_configs(m_config_qs, m_progresses_dict)

        new_m_configs = service.create_new_mission_progresses(new_m_configs)
        service.update_mission_progresses_after_loan(new_m_configs)
        self.assertEqual(new_m_configs[0]['m_config'].id, self.mission_config_3.id)

        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_3
        ).last()
        self.assertEqual(new_m_configs[0]['m_progress'].id, in_progress_m_progress.id)

    @mock.patch('django.utils.timezone.localtime')
    def test_create_repeat_mission_progresses(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        m_config_qs = MissionConfig.objects.get_valid_mission_config_queryset().filter(
            category=MissionCategoryConst.TRANSACTION,
        )
        m_config_ids = list(m_config_qs.values_list('id', flat=True))
        m_progresses_dict = service.get_and_blocking_exists_mission_progresses(m_config_ids)
        _, repeat_m_configs, _ = \
            service.classify_mission_configs(m_config_qs, m_progresses_dict)

        repeat_m_configs = service.create_repeat_mission_progresses(repeat_m_configs)
        repeat_m_config = repeat_m_configs[0]
        self.assertEqual(repeat_m_config['m_config'].id, self.mission_config_2.id)

        self.assertIsNotNone(repeat_m_config['old_m_progress'])
        repeat_m_config['old_m_progress'].refresh_from_db()
        self.assertEqual(repeat_m_config['old_m_progress'].id, self.complete_m_progress.id)
        self.assertFalse(repeat_m_config['old_m_progress'].is_latest)

        self.assertIsNotNone(repeat_m_config['m_progress'])
        self.assertTrue(repeat_m_config['m_progress'].is_latest)

    @mock.patch('django.utils.timezone.localtime')
    def test_process_after_loan_disbursement(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        self.mission_config_3.update_safely(
            target_recurring=2,
            max_repeat=3,
        )

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check NEW mission progress
        new_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_3,
            is_latest=True,
        ).last()

        self.assertIsNotNone(new_m_progress)
        self.assertEqual(new_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(new_m_progress.recurring_number, 1)
        self.assertEqual(new_m_progress.repeat_number, 1)
        reference_data = new_m_progress.reference_data
        self.assertIsNotNone(reference_data['loan_ids'])
        self.assertIsNotNone(reference_data['loan_ids'][0], self.sepulsa_loan.id)

        # check REPEAT mission progress
        repeat_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_2,
            is_latest=True,
        ).last()

        self.assertIsNotNone(repeat_m_progress)
        self.assertNotEqual(repeat_m_progress.id, self.complete_m_progress.id)
        self.assertEqual(repeat_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(repeat_m_progress.recurring_number, 1)
        self.assertEqual(repeat_m_progress.repeat_number, 2)
        reference_data = repeat_m_progress.reference_data
        self.assertIsNotNone(reference_data['loan_ids'])
        self.assertIsNotNone(reference_data['loan_ids'][0], self.sepulsa_loan.id)

        # check IN PROGRESS mission progress
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)
        self.assertEqual(in_progress_m_progress.id, self.in_progress_m_progress.id)
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(in_progress_m_progress.recurring_number, 2)
        self.assertEqual(in_progress_m_progress.repeat_number, 2)
        reference_data = in_progress_m_progress.reference_data
        self.assertIsNotNone(len(reference_data['loan_ids']))
        self.assertTrue(self.sepulsa_loan.id in reference_data['loan_ids'])

        # check history creation of NEW mission progress
        new_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=new_m_progress,
        )
        self.assertEqual(len(new_m_progress_history_qs), 3)
        new_hist_recurring_number = \
            new_m_progress_history_qs.filter(field='recurring_number').last()
        self.assertIsNotNone(new_hist_recurring_number)
        self.assertEqual(new_hist_recurring_number.old_value, '0')
        self.assertEqual(new_hist_recurring_number.new_value, '1')

        new_hist_reference_data = \
            new_m_progress_history_qs.filter(field='reference_data').last()
        self.assertIsNotNone(new_hist_reference_data)
        old_value = ast.literal_eval(new_hist_reference_data.old_value)
        new_value = ast.literal_eval(new_hist_reference_data.new_value)
        self.assertEqual(len(old_value['loan_ids']), 0)
        self.assertEqual(len(new_value['loan_ids']), 1)
        self.assertEqual(new_value['loan_ids'][0], self.sepulsa_loan.id)

        # check history creation of REPEAT mission progress
        repeat_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=repeat_m_progress,
        )
        self.assertEqual(len(repeat_m_progress_history_qs), 3)
        repeat_hist_recurring_number = \
            repeat_m_progress_history_qs.filter(field='recurring_number').last()
        self.assertIsNotNone(repeat_hist_recurring_number)
        self.assertEqual(repeat_hist_recurring_number.old_value, '0')
        self.assertEqual(repeat_hist_recurring_number.new_value, '1')

        repeat_hist_reference_data = \
            repeat_m_progress_history_qs.filter(field='reference_data').last()
        self.assertIsNotNone(repeat_hist_reference_data)
        old_value = ast.literal_eval(repeat_hist_reference_data.old_value)
        new_value = ast.literal_eval(repeat_hist_reference_data.new_value)
        self.assertEqual(len(old_value['loan_ids']), 0)
        self.assertEqual(len(new_value['loan_ids']), 1)
        self.assertEqual(new_value['loan_ids'][0], self.sepulsa_loan.id)

        # check history creation of IN PROGRESS mission progress
        in_progress_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=in_progress_m_progress,
        )
        self.assertEqual(len(in_progress_m_progress_history_qs), 2)
        in_progress_hist_recurring_number = \
            in_progress_m_progress_history_qs.filter(field='recurring_number').last()
        self.assertIsNotNone(in_progress_hist_recurring_number)
        self.assertEqual(in_progress_hist_recurring_number.old_value, '1')
        self.assertEqual(in_progress_hist_recurring_number.new_value, '2')

        in_progress_hist_reference_data = \
            in_progress_m_progress_history_qs.filter(field='reference_data').last()
        self.assertIsNotNone(in_progress_hist_reference_data)
        old_value = ast.literal_eval(in_progress_hist_reference_data.old_value)
        new_value = ast.literal_eval(in_progress_hist_reference_data.new_value)
        self.assertEqual(len(old_value['loan_ids']), 1)
        self.assertEqual(len(new_value['loan_ids']), 2)
        self.assertTrue(self.sepulsa_loan.id not in old_value['loan_ids'])
        self.assertTrue(self.sepulsa_loan.id in new_value['loan_ids'])

    @mock.patch('django.utils.timezone.localtime')
    def test_create_new_mission_progress_with_inactive_mission(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        # Cannot create new mission progress when mission config is_active = False
        self.mission_config_3.update_safely(
            is_active=False
        )
        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check NEW mission progress
        new_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_3,
            is_latest=True,
        ).last()

        self.assertIsNone(new_m_progress)

        # check history creation of NEW mission progress
        new_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=new_m_progress,
        )
        self.assertEqual(len(new_m_progress_history_qs), 0)
        new_hist_recurring_number = \
            new_m_progress_history_qs.filter(field='recurring_number').last()
        self.assertIsNone(new_hist_recurring_number)

        new_hist_reference_data = \
            new_m_progress_history_qs.filter(field='reference_data').last()
        self.assertIsNone(new_hist_reference_data)

    @mock.patch('django.utils.timezone.localtime')
    def test_repeat_mission_progress_with_inactive_missions(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        # Cannot repeat mission progress with inactive mission
        self.mission_config_2.update_safely(
            is_active=False
        )

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check REPEAT mission progress
        repeat_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_2,
            is_latest=True,
        ).last()

        self.assertIsNotNone(repeat_m_progress)
        self.assertEqual(repeat_m_progress.id, self.complete_m_progress.id)
        self.assertEqual(repeat_m_progress.status, MissionProgressStatusConst.COMPLETED)
        self.assertEqual(repeat_m_progress.recurring_number, 2)
        self.assertEqual(repeat_m_progress.repeat_number, 1)

    @mock.patch('django.utils.timezone.localtime')
    def test_update_in_progress_m_progress_with_inactive_mission(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        # Still can be updated mission progress when mission config is_active = False
        self.mission_config_1.update_safely(
            is_active=False
        )
        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check IN PROGRESS mission progress still can be updated
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)
        self.assertEqual(in_progress_m_progress.id, self.in_progress_m_progress.id)
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(in_progress_m_progress.recurring_number, 2)
        self.assertEqual(in_progress_m_progress.repeat_number, 2)
        reference_data = in_progress_m_progress.reference_data
        self.assertIsNotNone(len(reference_data['loan_ids']))
        self.assertTrue(self.sepulsa_loan.id in reference_data['loan_ids'])

        # check history creation of IN PROGRESS mission progress
        in_progress_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=in_progress_m_progress,
        )
        self.assertEqual(len(in_progress_m_progress_history_qs), 2)
        in_progress_hist_recurring_number = \
            in_progress_m_progress_history_qs.filter(field='recurring_number').last()
        self.assertIsNotNone(in_progress_hist_recurring_number)
        self.assertEqual(in_progress_hist_recurring_number.old_value, '1')
        self.assertEqual(in_progress_hist_recurring_number.new_value, '2')

        in_progress_hist_reference_data = \
            in_progress_m_progress_history_qs.filter(field='reference_data').last()
        self.assertIsNotNone(in_progress_hist_reference_data)
        old_value = ast.literal_eval(in_progress_hist_reference_data.old_value)
        new_value = ast.literal_eval(in_progress_hist_reference_data.new_value)
        self.assertEqual(len(old_value['loan_ids']), 1)
        self.assertEqual(len(new_value['loan_ids']), 2)
        self.assertTrue(self.sepulsa_loan.id not in old_value['loan_ids'])
        self.assertTrue(self.sepulsa_loan.id in new_value['loan_ids'])

    @mock.patch('django.utils.timezone.localtime')
    def test_update_mission_progress_with_deleted_mission(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        # Still can be updated mission progress when mission config is_active = False
        self.mission_config_1.update_safely(
            is_deleted=True
        )
        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check IN PROGRESS mission progress still can be updated
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)
        self.assertEqual(in_progress_m_progress.id, self.in_progress_m_progress.id)
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(in_progress_m_progress.recurring_number, 1)
        self.assertEqual(in_progress_m_progress.repeat_number, 2)
        reference_data = in_progress_m_progress.reference_data
        self.assertIsNotNone(len(reference_data['loan_ids']))
        self.assertFalse(self.sepulsa_loan.id in reference_data['loan_ids'])

        # check history creation of IN PROGRESS mission progress
        in_progress_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=in_progress_m_progress,
        )
        self.assertEqual(len(in_progress_m_progress_history_qs), 0)

    @mock.patch('django.utils.timezone.localtime')
    def test_complete_mission_progress(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        self.in_progress_m_progress.update_safely(recurring_number=2)

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check IN PROGRESS mission progress
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.COMPLETED)

        # check history creation of IN PROGRESS mission progress
        in_progress_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=in_progress_m_progress,
        )
        self.assertEqual(len(in_progress_m_progress_history_qs), 3)
        in_progress_hist_status = \
            in_progress_m_progress_history_qs.filter(field='status').last()
        self.assertIsNotNone(in_progress_hist_status)
        self.assertEqual(in_progress_hist_status.old_value, MissionProgressStatusConst.IN_PROGRESS)
        self.assertEqual(in_progress_hist_status.new_value, MissionProgressStatusConst.COMPLETED)

    @mock.patch('django.utils.timezone.localtime')
    def test_claim_mission_progress(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        self.set_up_mission_data()
        self.mission_config_2.update_safely(
            expiry_date=datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        )

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        self.complete_m_progress.refresh_from_db()
        self.assertEqual(self.complete_m_progress.status, MissionProgressStatusConst.CLAIMED)

        claimed_m_progress_history_qs = MissionProgressHistory.objects.filter(
            mission_progress=self.complete_m_progress,
            field='status'
        ).last()
        self.assertIsNotNone(claimed_m_progress_history_qs)
        self.assertEqual(claimed_m_progress_history_qs.old_value,
                         MissionProgressStatusConst.COMPLETED)
        self.assertEqual(claimed_m_progress_history_qs.new_value,
                         MissionProgressStatusConst.CLAIMED)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_mission_progress_data_to_send_moengage(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        self.set_up_mission_data()
        mission_config_4 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            target_recurring=3,
            max_repeat=3,
        )

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        m_config_qs = MissionConfig.objects.get_valid_mission_config_queryset().filter(
            category=MissionCategoryConst.TRANSACTION,
        )
        m_config_ids = list(m_config_qs.values_list('id', flat=True))
        m_progresses_dict = service.get_and_blocking_exists_mission_progresses(m_config_ids)
        new_m_configs, repeat_m_configs, in_progress_m_configs = \
            service.classify_mission_configs(m_config_qs, m_progresses_dict)
        new_m_configs = service.create_new_mission_progresses(new_m_configs)
        repeat_m_configs = service.create_repeat_mission_progresses(repeat_m_configs)
        in_progress_m_configs.extend([*new_m_configs, *repeat_m_configs])
        updated_history_data = service.update_mission_progresses_after_loan(in_progress_m_configs)
        claimed_history_data = service.process_mission_progress_to_claim(repeat_m_configs)

        moengage_data = service.get_mission_progress_data_to_send_moengage(
            [*updated_history_data, *claimed_history_data]
        )

        new_progress_in_progress = None
        new_progress_completed = None
        for data in new_m_configs:
            if data['m_config'].id == mission_config_4.id:
                new_progress_in_progress = data['m_progress']
            elif data['m_config'].id == self.mission_config_3.id:
                new_progress_completed = data['m_progress']

        repeat_progress_in_progress = repeat_m_configs[0]['m_progress']
        repeat_progress_claimed = repeat_m_configs[0]['old_m_progress']
        in_progress = in_progress_m_configs[0]['m_progress']

        moengage_dict = {data['mission_progress_id']: data for data in moengage_data}

        self.assertIsNotNone(moengage_dict.get(new_progress_in_progress.id))
        self.assertEqual(
            moengage_dict[new_progress_in_progress.id]['status'],
            MissionProgressStatusConst.IN_PROGRESS
        )
        self.assertIsNotNone(moengage_dict.get(new_progress_completed.id))
        self.assertEqual(
            moengage_dict[new_progress_completed.id]['status'],
            MissionProgressStatusConst.COMPLETED
        )

        self.assertIsNotNone(moengage_dict.get(repeat_progress_in_progress.id))
        self.assertEqual(
            moengage_dict[repeat_progress_in_progress.id]['status'],
            MissionProgressStatusConst.IN_PROGRESS
        )
        self.assertIsNotNone(moengage_dict.get(repeat_progress_claimed.id))
        self.assertEqual(
            moengage_dict[repeat_progress_claimed.id]['status'],
            MissionProgressStatusConst.CLAIMED
        )

        self.assertIsNone(moengage_dict.get(in_progress.id))

    @mock.patch('django.utils.timezone.localtime')
    def test_update_mission_target_progress_sync(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.set_up_mission_data()
        m_target = MissionTargetFactory(
            name='default mission target',
            category=MissionCategoryConst.GENERAL,
            type=MissionTargetTypeConst.RECURRING,
            value=3
        )
        m_config_target = MissionConfigTargetFactory(
            target=m_target,
            config=self.mission_config_1
        )
        m_config_target.save()

        service = TransactionMissionProgressService(loan=self.sepulsa_loan)
        service.process_after_loan_disbursement()

        # check IN PROGRESS mission progress still can be updated
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)
        self.assertEqual(in_progress_m_progress.id, self.in_progress_m_progress.id)

        target_progress = MissionTargetProgress.objects.filter(
            mission_progress_id=in_progress_m_progress.id
        ).last()
        self.assertIsNotNone(target_progress)
        self.assertEqual(target_progress.value, in_progress_m_progress.recurring_number)


class TestPopulateDataWhitelistCriteriaRedis(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.fake_redis = MockStrictRedisHelper()
        self.criteria = MissionCriteriaFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionCriteriaTypeConst.WHITELIST_CUSTOMERS,
            value={
                'upload_url': 'loyalty_customers_whitelist_1',
                'duration': 2
            }
        )
        self.redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(
            self.criteria.id
        )

    @patch('juloserver.loyalty.services.mission_related.get_redis_client')
    def test_populate_whitelist_mission_criteria_on_redis(self, mock_redis):
        mock_redis.return_value = self.fake_redis
        populate_whitelist_mission_criteria_on_redis(
            {self.customer.id}, self.criteria
        )
        result = self.fake_redis.sismember(self.redis_key, self.customer.id)
        self.assertTrue(result)

        delete_whitelist_mission_criteria_on_redis(self.criteria)
        result = self.fake_redis.get(self.redis_key, self.customer.id)
        self.assertIsNone(result)


class TestPointRedemptionServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.loyalty_point = LoyaltyPointFactory(customer_id=self.customer.id, total_point=123_456)
        self.setup_point_redeem_fs()
        self.setup_conversion_rate_fs()

    def setup_point_redeem_fs(self):
        self.point_redeem_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_REDEEM,
            is_active=True,
            parameters={
                PointRedeemReferenceTypeConst.REPAYMENT: {
                    "name": "Potong Tagihan",
                    "is_active": True,
                    "tag_info": {
                        "title": "",
                        "is_active": False
                    },
                    "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/111.png",
                    "is_default": True,
                    "minimum_withdrawal": 20_000
                },
                PointRedeemReferenceTypeConst.GOPAY_TRANSFER: {
                    "name": "GoPay",
                    "is_active": True,
                    "tag_info": {
                        "title": "Baru",
                        "is_active": True
                    },
                    "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/222.png",
                    "is_default": False,
                    "minimum_withdrawal": 20_000,
                    "partner_fee": 110,
                    "julo_fee": 0,
                },
                PointRedeemReferenceTypeConst.DANA_TRANSFER: {
                    "name": "Dana",
                    "is_active": True,
                    "tag_info": {},
                    "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/222.png",
                    "is_default": False,
                    "minimum_withdrawal": 20_000,
                    "julo_fee": 0,
                }
            }
        )

    def setup_conversion_rate_fs(self):
        self.point_conversion_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_CONVERT,
            is_active=True,
            parameters={
                "from_point_to_rupiah": 1.4
            }
        )

    @patch('juloserver.loyalty.services.point_redeem_services.is_point_blocked_by_collection_repayment_reason')
    def test_check_eligible_repayment_method(self, mock_block_repayment):
        mock_block_repayment.return_value = False

        method = PointRedeemReferenceTypeConst.REPAYMENT
        params = self.point_redeem_fs.parameters[method]

        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertTrue(is_valid)
        self.assertIsNone(error_code)

        self.point_redeem_fs.parameters[method]['is_active'] = False
        self.point_redeem_fs.save()

        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertFalse(is_valid)
        self.assertEqual(error_code, RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        mock_block_repayment.return_value = True
        self.point_redeem_fs.parameters[method]['is_active'] = True
        self.point_redeem_fs.save()

        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertFalse(is_valid)
        self.assertEqual(error_code, RedemptionMethodErrorCode.BLOCK_DEDUCTION_POINT)


    def test_check_eligible_transfer_method(self):
        method = PointRedeemReferenceTypeConst.GOPAY_TRANSFER
        params = self.point_redeem_fs.parameters[method]

        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertTrue(is_valid)
        self.assertIsNone(error_code)

        self.point_redeem_fs.parameters[method]['is_active'] = False
        self.point_redeem_fs.save()

        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertFalse(is_valid)
        self.assertEqual(error_code, RedemptionMethodErrorCode.UNAVAILABLE_METHOD)


    def test_check_white_transfer_dana(self):
        method = PointRedeemReferenceTypeConst.DANA_TRANSFER
        params = self.point_redeem_fs.parameters[method]
        SepulsaProductFactory(
            type=SepulsaProductType.E_WALLET_OPEN_PAYMENT,
            category=SepulsaProductCategory.DANA,
            is_active=True
        )
        # turn off whitelist = eligible for transfer
        whitelist_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_TRANSFER_WHITELIST_CUST,
            is_active=False,
            parameters={}
        )
        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertTrue(is_valid)
        self.assertIsNone(error_code)

        # is_active = true. but no customer_id in parameters -> not eligible
        whitelist_fs.update_safely(is_active=True)
        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertFalse(is_valid)
        self.assertEqual(error_code, RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        # is_active = true and customer_id in parameters -> eligible
        whitelist_parameters = whitelist_fs.parameters
        whitelist_parameters['customer_ids'] = [self.customer.id]
        whitelist_fs.update_safely(parameters=whitelist_parameters)
        is_valid, error_code = is_eligible_redemption_method(method, params, self.customer)
        self.assertTrue(is_valid)
        self.assertIsNone(error_code)


    def test_get_nominal_limit_for_transfer(self):
        method = PointRedeemReferenceTypeConst.GOPAY_TRANSFER
        params = self.point_redeem_fs.parameters[method]
        total_point = self.loyalty_point.total_point

        # Admin fee < Minimum withdrawal -> Mininal nominal amount = Minimum withdrawal
        self.point_redeem_fs.parameters[method]['partner_fee'] = 10_000
        self.point_redeem_fs.parameters[method]['minimum_withdrawal'] = 20_000
        self.point_redeem_fs.save()
        specific_info = get_transfer_method_pricing_info(method, params, total_point)
        self.assertEqual(specific_info['admin_fee'], 10_000)
        self.assertEqual(specific_info['minimum_nominal_amount'], 20_000)
        self.assertEqual(specific_info['maximum_nominal_amount'], 172_838)

        # Admin fee > Minimum withdrawal -> Mininal nominal amount = Admin fee
        self.point_redeem_fs.parameters[method]['partner_fee'] = 30_000
        self.point_redeem_fs.parameters[method]['minimum_withdrawal'] = 25_000
        self.point_redeem_fs.save()
        specific_info = get_transfer_method_pricing_info(method, params, total_point)
        self.assertEqual(specific_info['admin_fee'], 30_000)
        self.assertEqual(specific_info['minimum_nominal_amount'], 30_000)
        self.assertEqual(specific_info['maximum_nominal_amount'], 172_838)
