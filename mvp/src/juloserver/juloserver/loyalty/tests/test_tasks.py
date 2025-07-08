import pytz
import csv
import os
from datetime import datetime, date

from django.test import TestCase
from unittest import mock
from factory import Iterator

from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
    ProductLookupFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.tests.factories import AccountFactory
from juloserver.loyalty.tests.factories import (
    PointEarningFactory,
    LoyaltyPointFactory,
    MissionConfigFactory,
    MissionRewardFactory,
    MissionProgressFactory,
    MissionCriteriaFactory,
)
from juloserver.loyalty.tasks import (
    claim_mission_progress_by_batch_subtask,
    claim_mission_progress_after_repetition_delay_task,
    expire_point_earning_task,
    expire_mission_config_task,
    execute_loyalty_transaction_mission_task,
    trigger_upload_whitelist_mission_criteria,
    delete_mission_progress_task,
    send_loyalty_total_point_to_moengage_task,
)
from juloserver.loyalty.constants import (
    MissionCriteriaTypeConst,
    MissionCriteriaValueConst,
    MissionCategoryConst,
    MissionProgressStatusConst,
    FeatureNameConst as LoyaltyFeatureNameConst,
)
from juloserver.account.constants import (
    AccountConstant,
)
from juloserver.loyalty.models import (
    MissionConfig,
    MissionProgress,
    LoyaltyPoint,
)


class TestExpirePointEarningTask(TestCase):
    def setUp(self):
        self.customer_1 = CustomerFactory(user=AuthUserFactory())
        self.customer_2 = CustomerFactory(user=AuthUserFactory())
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account_1 = AccountFactory(customer=self.customer_1, status=status_code)
        self.loyal_point_1 = LoyaltyPointFactory(customer_id=self.customer_1.id)
        self.loyal_point_2 = LoyaltyPointFactory(customer_id=self.customer_2.id)
        self.point_earnings_1 = PointEarningFactory.create_batch(
            3,
            customer_id=self.customer_1.id,
            points=Iterator([2000, 5000, 8000]),
            expiry_date=Iterator([date(2024, 1, 1), date(2024, 1, 1), date(2024, 7, 1)])
        )
        self.point_earnings_2 = PointEarningFactory.create_batch(
            3,
            customer_id=self.customer_2.id,
            points=Iterator([3000, 6000, 9000]),
            expiry_date=Iterator([date(2024, 1, 1), date(2024, 7, 1), date(2024, 7, 1)])
        )

    @mock.patch('juloserver.loyalty.tasks.expire_point_earning_by_batch_task.delay')
    @mock.patch('django.utils.timezone.now')
    def test_expire_point_earning_task_1(self, mock_now,
                                         mock_expire_customer_point_earning_task):
        mock_now.return_value = datetime(2023, 1, 1, 12, 44, 55)
        expire_point_earning_task()
        mock_expire_customer_point_earning_task.assert_not_called()

    @mock.patch('juloserver.loyalty.tasks.expire_point_earning_by_batch_task.delay')
    @mock.patch('django.utils.timezone.now')
    def test_expire_point_earning_task_2(self, mock_now,
                                         mock_expire_point_earning_by_batch_task):
        mock_now.return_value = datetime(2024, 1, 1, 15, 30, 30)

        expire_point_earning_task()
        mock_expire_point_earning_by_batch_task.assert_called_once_with(
            [self.customer_1.id, self.customer_2.id], date(2024, 1, 1)
        )

    @mock.patch('juloserver.loyalty.tasks.expire_point_earning_by_batch_task.delay')
    @mock.patch('django.utils.timezone.now')
    def test_expire_point_earning_task_3(self, mock_now,
                                         mock_expire_point_earning_by_batch_task):
        mock_now.return_value = datetime(2024, 7, 1, 15, 30, 30)

        expire_point_earning_task()
        mock_expire_point_earning_by_batch_task.assert_called_once_with(
            [self.customer_1.id, self.customer_2.id], date(2024, 7, 1)
        )

    @mock.patch('juloserver.loyalty.tasks.expire_point_earning_by_batch_task.delay')
    @mock.patch('django.utils.timezone.now')
    def test_expire_point_earning_task_4(self, mock_now,
                                         mock_expire_point_earning_by_batch_task):
        mock_now.return_value = datetime(2025, 1, 1, 12, 44, 55)

        expire_point_earning_task()
        mock_expire_point_earning_by_batch_task.assert_called_once_with(
            [self.customer_1.id, self.customer_2.id], date(2025, 1, 1)
        )


class TestExpireMissionConfigTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type='Fixed',
            value=10000,
        )
        LoyaltyPointFactory(customer_id=self.customer.id)
        mission_1 = MissionConfigFactory(
            title="Top Up GoPay 5 Kali",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=2,
            category=MissionCategoryConst.TRANSACTION,
            display_order=2,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 16, 34, 55, tzinfo=pytz.UTC),
        )
        mission_2 = MissionConfigFactory(
            title="Bayar 3x Tagihan Pakai Autodebit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=1,
            repetition_delay_days=0,
            category=MissionCategoryConst.TRANSACTION,
            display_order=3,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 16, 58, 55, tzinfo=pytz.UTC),
        )
        mission_3 = MissionConfigFactory(
            title="Beli Pulsa Rp 100.000",
            reward=self.mission_reward,
            target_recurring=4,
            max_repeat=2,
            repetition_delay_days=3,
            category=MissionCategoryConst.TRANSACTION,
            display_order=4,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 12, 23, 55, tzinfo=pytz.UTC),
        )
        mission_4 = MissionConfigFactory(
            title="Bayar 3 Tagihan Lebih Cepat",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=6,
            category=MissionCategoryConst.TRANSACTION,
            display_order=5,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 16, 50, 55, tzinfo=pytz.UTC),
        )
        mission_5 = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=20,
            max_repeat=1,
            repetition_delay_days=0,
            category=MissionCategoryConst.TRANSACTION,
            display_order=6,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 17, 00, 00, tzinfo=pytz.UTC),
        )
        mission_6 = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=3,
            category=MissionCategoryConst.TRANSACTION,
            display_order=7,
            is_active=True,
            expiry_date=datetime(2024, 4, 9, 16, 50, 55, tzinfo=pytz.UTC),
        )
        MissionProgressFactory.create_batch(
            6,
            customer_id=self.customer.id,
            mission_config=Iterator(
                [mission_1, mission_2, mission_3, mission_4, mission_5, mission_6]
            ),
            recurring_number=Iterator([2, 1, 4, 0, 0, 3]),
            status=Iterator(
                [
                    MissionProgressStatusConst.STARTED,
                    MissionProgressStatusConst.IN_PROGRESS,
                    MissionProgressStatusConst.CLAIMED,
                    MissionProgressStatusConst.EXPIRED,
                    MissionProgressStatusConst.IN_PROGRESS,
                    MissionProgressStatusConst.COMPLETED,
                ]
            ),
        )

    @mock.patch('django.utils.timezone.now')
    def test_exprire_mission_config_task_1(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 23, 59, 30)
        expire_mission_config_task()
        mission_progress_expired = MissionProgress.objects.filter(
            status=MissionProgressStatusConst.EXPIRED
        ).count()
        # Except mission progress 1, 3, 5, 6
        self.assertEqual(mission_progress_expired, 2)

    @mock.patch('django.utils.timezone.now')
    def test_exprire_mission_config_task_2(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 10, 0, 0, 2)
        expire_mission_config_task()
        mission_progress_expired = MissionProgress.objects.filter(
            status=MissionProgressStatusConst.EXPIRED
        ).count()
        # Except mission progress 1, 3, 6
        self.assertEqual(mission_progress_expired, 3)

    @mock.patch('django.utils.timezone.now')
    def test_exprire_mission_config_task_3(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 19, 10, 2)
        expire_mission_config_task()
        mission_progress_expired = MissionProgress.objects.filter(
            status=MissionProgressStatusConst.EXPIRED
        ).count()
        # Except mission progress 1, 3, 5, 6
        self.assertEqual(mission_progress_expired, 2)

    @mock.patch('django.utils.timezone.now')
    def test_exprire_inactive_mission_config_task(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 19, 10, 2)
        mission_config = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=5,
            category=MissionCategoryConst.TRANSACTION,
            display_order=7,
            is_active=False,
            expiry_date=datetime(2024, 4, 9, 18, 30, 0),
        )
        mission_progress = MissionProgressFactory(
            customer=self.customer,
            mission_config=mission_config,
            recurring_number=1,
            status=MissionProgressStatusConst.IN_PROGRESS,
        )
        mission_progress.save()
        expire_mission_config_task()
        mission_progress_expired = MissionProgress.objects.filter(
            status=MissionProgressStatusConst.EXPIRED
        ).count()
        # Except mission progress 1, 3, 5, 6 and mission config 5
        self.assertEqual(mission_progress_expired, 3)

    def test_delete_mission_progress_with_deleted_mission_config_task(self):
        mission_config = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=5,
            category=MissionCategoryConst.TRANSACTION,
            display_order=7,
            is_deleted=True,
            expiry_date=datetime(2024, 4, 9, 18, 30, 0),
        )
        mission_progress = MissionProgressFactory(
            customer=self.customer,
            mission_config=mission_config,
            recurring_number=1,
            status=MissionProgressStatusConst.IN_PROGRESS,
        )
        mission_progress.save()
        delete_mission_progress_task(mission_config_id=mission_config.id)
        mission_progress_deleted = MissionProgress.objects.filter(
            status=MissionProgressStatusConst.DELETED
        ).count()
        mission_config_deleted = MissionConfig.objects.filter(is_deleted=True).count()
        # Except mission progress 1, 3, 5, 6 and mission config 5
        self.assertEqual(mission_progress_deleted, 1)
        self.assertEqual(mission_config_deleted, 1)

    @mock.patch('django.utils.timezone.now')
    def test_claim_mission_progress_after_repetition_delay(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 0, 0, 0)

        MissionProgress.objects.filter(
            status=MissionProgressStatusConst.COMPLETED
        ).update(
            completion_date=datetime(2024, 4, 4, 0, 0, 0)
        )

        mission_config = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=5,
            category=MissionCategoryConst.TRANSACTION,
            display_order=7,
            is_active=True,
            expiry_date=datetime(2024, 5, 9, 0, 0, 0),
        )
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=mission_config,
            recurring_number=1,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime(2024, 4, 5, 0, 0, 0),
        )
        mission_progress.save()

        # check completion_date + delay < now
        claim_mission_progress_after_repetition_delay_task()
        mission_progress.refresh_from_db()
        self.assertEqual(mission_progress.status, MissionProgressStatusConst.COMPLETED)

        mission_progress.update_safely(
            completion_date=datetime(2024, 4, 4, 0, 0, 0)
        )

        # check completion_date + delay >= now
        claim_mission_progress_after_repetition_delay_task()
        mission_progress.refresh_from_db()
        self.assertEqual(mission_progress.status, MissionProgressStatusConst.CLAIMED)
        self.assertIsNotNone(mission_progress.point_earning)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.now')
    def test_claim_mission_progress_by_batch_subtask(self, mock_now, mock_send_to_me):
        mock_now.return_value = datetime(2024, 4, 9, 0, 0, 0)

        mission_config = MissionConfigFactory(
            title="Bagikan 20 Kode Referral ke Teman hingga Dapat Limit",
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=5,
            category=MissionCategoryConst.TRANSACTION,
            display_order=7,
            is_active=True,
            expiry_date=datetime(2024, 5, 9, 0, 0, 0),
        )
        mission_progress = MissionProgressFactory(
            customer=self.customer,
            mission_config=mission_config,
            recurring_number=1,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime(2024, 4, 4, 0, 0, 0),
        )
        mission_progress.save()

        claim_mission_progress_by_batch_subtask([mission_progress.id])
        mission_progress.refresh_from_db()
        self.assertEqual(mission_progress.status, MissionProgressStatusConst.CLAIMED)
        self.assertIsNotNone(mission_progress.point_earning)
        mock_send_to_me.assert_called_with(
            self.customer.id,
            [{
                'mission_progress_id': mission_progress.id,
                'status': mission_progress.status
            }]
        )


class TestUploadWhitelistCriteria(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.customer2 = CustomerFactory()
        self.customer3 = CustomerFactory()
        self.fake_redis = MockRedisHelper()
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

    @mock.patch('juloserver.loyalty.tasks.read_csv_file_by_csv_reader')
    @mock.patch('juloserver.loyalty.tasks.get_redis_client')
    def test_trigger_upload_whitelist_mission_criteria_key_existed(self,
                                                                   mock_redis,
                                                                   mock_read_csv_file):
        mock_redis.return_value = self.fake_redis
        self.fake_redis.sadd(
            self.redis_key, {self.customer.id, self.customer2.id, self.customer3.id}
        )
        trigger_upload_whitelist_mission_criteria(self.criteria.id)
        mock_read_csv_file.assert_not_called()


    @mock.patch('juloserver.loyalty.tasks.read_csv_file_by_csv_reader')
    @mock.patch('juloserver.loyalty.tasks.get_redis_client')
    def test_trigger_upload_whitelist_mission_criteria_key_not_existed(self,
                                                                       mock_redis,
                                                                       mock_read_csv_file):
        mock_redis.return_value = self.fake_redis
        data = [
            [str(self.customer.id)],
            [str(self.customer2.id)],
            [str(self.customer3.id)],
        ]
        file_name = 'whitelist_customers.csv'
        file_path = os.path.abspath(file_name)
        with open(file_path, mode='w', newline='') as file:
            csv_writer = csv.writer(file, delimiter=',')
            csv_writer.writerows(data)

        with open(file_path, mode='r') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',')
            mock_read_csv_file.return_value = csv_reader
            trigger_upload_whitelist_mission_criteria(self.criteria.id)
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer.id))
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer2.id))
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer3.id))
        os.remove(file_path)


class TestLoyaltyTransactionMission(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            product=ProductLookupFactory(product_line=product_line)
        )

    @mock.patch('juloserver.loyalty.services.mission_progress'
                '.TransactionMissionProgressService.process')
    def test_whitelist_loyalty_transaction_mission_success_1(self,
                                                           mock_process_after_loan_disbursement):
        # No feature setting case
        execute_loyalty_transaction_mission_task(self.loan.id)
        mock_process_after_loan_disbursement.assert_called()

    @mock.patch('juloserver.loyalty.services.mission_progress'
                '.TransactionMissionProgressService.process')
    def test_whitelist_loyalty_transaction_mission_success_2(self,
                                                           mock_process_after_loan_disbursement):
        # has feature setting but is_active=False
        fs = FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [self.customer.id]},
            is_active=False,
        )
        fs.save()
        execute_loyalty_transaction_mission_task(self.loan.id)
        mock_process_after_loan_disbursement.assert_called()

    @mock.patch('juloserver.loyalty.services.mission_progress'
                '.TransactionMissionProgressService.process')
    def test_whitelist_loyalty_transaction_mission_success_3(self,
                                                           mock_process_after_loan_disbursement):
        # has feature setting but is_active=True
        fs = FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [self.customer.id]},
            is_active=True,
        )
        fs.save()
        execute_loyalty_transaction_mission_task(self.loan.id)
        mock_process_after_loan_disbursement.assert_called()

    @mock.patch('juloserver.loyalty.services.mission_related'
                '.TransactionMissionProgressService.process_after_loan_disbursement')
    def test_whitelist_loyalty_transaction_mission_fail(self,
                                                        mock_process_after_loan_disbursement):
        # has feature setting but customer not in the list
        fs = FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [self.customer.id+1]},
            is_active=True,
        )
        fs.save()
        execute_loyalty_transaction_mission_task(self.loan.id)
        mock_process_after_loan_disbursement.assert_not_called()

    @mock.patch('juloserver.loyalty.services.mission_related'
                '.TransactionMissionProgressService.process_after_loan_disbursement')
    def test_loan_j1_jturbo_loyalty_transaction_mission(self,
                                                        mock_process_after_loan_disbursement):

        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.PARTNERSHIP_PRE_CHECK,
        )
        self.loan.update_safely(
            product=ProductLookupFactory(product_line=product_line)
        )

        execute_loyalty_transaction_mission_task(self.loan.id)
        mock_process_after_loan_disbursement.assert_not_called()


class TestSendLoyaltyTotalPointToMoengage(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loyalty_point = LoyaltyPointFactory(
            customer_id=self.customer.id,
            total_point=200,
        )

    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loyalty.tasks.send_user_attributes_loyalty_total_point_to_moengage.delay')
    def test_positive_point_to_send_loyalty_total_point_to_moengage(self,
                                                  mock_user_attributes_loyalty_total_point_to_me,
                                                  mock_now):
        loyalty_point = LoyaltyPoint.objects.filter(
            customer_id=self.customer.id
        ).update(udate=datetime(2024, 9, 24, 16, 30, 0))
        mock_now.return_value = datetime(2024, 9, 25, 9, 0, 0)
        send_loyalty_total_point_to_moengage_task()
        mock_user_attributes_loyalty_total_point_to_me.assert_called_once_with(
            [self.customer.id]
        )

    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loyalty.tasks.send_user_attributes_loyalty_total_point_to_moengage.delay')
    def test_negative_point_to_send_loyalty_total_point_to_moengage(self,
                                                  mock_user_attributes_loyalty_total_point_to_me,
                                                  mock_now):
        loyalty_point = LoyaltyPoint.objects.filter(
            customer_id=self.customer.id
        ).update(udate=datetime(2024, 9, 24, 16, 30, 0), total_point=0)
        mock_now.return_value = datetime(2024, 9, 25, 9, 0, 0)
        send_loyalty_total_point_to_moengage_task()
        mock_user_attributes_loyalty_total_point_to_me.assert_called_once_with(
            [self.customer.id]
        )

    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loyalty.tasks.send_user_attributes_loyalty_total_point_to_moengage.delay')
    def test_udate_to_send_loyalty_total_point_to_moengage(self,
                                                  mock_user_attributes_loyalty_total_point_to_me,
                                                  mock_now):
        loyalty_point = LoyaltyPoint.objects.filter(
            customer_id=self.customer.id
        ).update(udate=datetime(2024, 9, 25, 4, 30, 0))
        mock_now.return_value = datetime(2024, 9, 25, 9, 0, 0)
        send_loyalty_total_point_to_moengage_task()
        mock_user_attributes_loyalty_total_point_to_me.assert_not_called()
