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

from juloserver.julocore.constants import DbConnectionAlias
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loyalty.services.mission_progress import TransactionMissionProgressService
from juloserver.loyalty.models import (
    MissionProgress,
    MissionProgressHistory,
    MissionConfig,
    MissionTargetProgress,
)
from juloserver.loyalty.constants import (
    MissionCategoryConst,
    MissionProgressStatusConst,
    MissionTargetTypeConst,
    MissionCriteriaTypeConst,
)

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    LoanFactory,
)

from juloserver.loyalty.tests.factories import (
    LoyaltyPointFactory,
    MissionConfigFactory,
    MissionConfigCriteriaFactory,
    MissionProgressFactory,
    MissionRewardFactory,
    MissionTargetFactory,
    MissionConfigTargetFactory,
    MissionCriteriaFactory,
    MissionTargetProgressFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.account.constants import (
    AccountConstant,
)


class MissionConfigCriteriaBaseSetup:
    def set_up_mission_configs(self):
        self.mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type='Fixed',
            value=10000,
        )

        self.mission_config_1 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            max_repeat=2,
            is_active=True,
            repetition_delay_days=3,
            reward=self.mission_reward,
        )
        self.mission_config_2 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            max_repeat=3,
            is_active=True,
            repetition_delay_days=3,
            reward=self.mission_reward,
        )
        self.mission_config_3 = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            max_repeat=4,
            is_active=True,
            repetition_delay_days=3,
            reward=self.mission_reward,
        )
        self.mission_config_4 = MissionConfigFactory(category=MissionCategoryConst.GENERAL)

    def set_up_mission_targets(self):
        self.mission_target_1 = MissionTargetFactory(
            name='default mission target',
            category=MissionCategoryConst.GENERAL,
            type=MissionTargetTypeConst.RECURRING,
            value=3
        )
        self.mission_target_2 = MissionTargetFactory(
            name='default mission total',
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=5000000
        )

    def set_up_mission_config_targets(self):
        self.mission_config_target_1 = MissionConfigTargetFactory(
            target=self.mission_target_1,
            config=self.mission_config_1
        )
        self.mission_config_target_2 = MissionConfigTargetFactory(
            target=self.mission_target_2,
            config=self.mission_config_2
        )

        self.mission_config_target_3 = MissionConfigTargetFactory(
            target=self.mission_target_1,
            config=self.mission_config_3
        )
        self.mission_config_target_4 = MissionConfigTargetFactory(
            target=self.mission_target_2,
            config=self.mission_config_3
        )

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

    def set_up_loan(self):
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )


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

        self.set_up_mission_configs()
        self.set_up_mission_targets()
        self.set_up_criteria()

        self.set_up_mission_config_targets()
        self.set_up_mission_config_criteria()

        self.set_up_mission_progresses()

    def set_up_mission_progresses(self):
        # in progress
        self.in_progress_m_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            repeat_number=2,
            is_latest=True,
            status=MissionProgressStatusConst.IN_PROGRESS,
            reference_data={'loan_ids': ['-123']}
        )
        self.target_in_progress = MissionTargetProgressFactory(
            mission_progress=self.in_progress_m_progress,
            mission_target=self.mission_target_1,
            category=MissionCategoryConst.GENERAL,
            type=MissionTargetTypeConst.RECURRING,
            value=1,
        )

        # complete
        self.complete_m_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_config_3,
            repeat_number=1,
            is_latest=True,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime(2024, 3, 7, 0, 0, 0, tzinfo=timezone.utc)
        )
        MissionTargetProgressFactory(
            mission_progress=self.complete_m_progress,
            mission_target=self.mission_target_1,
            category=MissionCategoryConst.GENERAL,
            type=MissionTargetTypeConst.RECURRING,
            value=3,
        )
        MissionTargetProgressFactory(
            mission_progress=self.complete_m_progress,
            mission_target=self.mission_target_2,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=5_000_000,
        )

    @mock.patch('django.utils.timezone.localtime')
    def test_categorize_mission_data(self, mock_localtime):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        service = TransactionMissionProgressService(loan=loan)
        m_config_qs = service.get_transaction_mission_config_qs()
        m_config_ids = list(m_config_qs.values_list('id', flat=True))
        m_progresses_dict = \
            service.get_and_blocking_exists_mission_progresses(m_config_ids=m_config_ids)

        new_mission_data, repeat_mission_data, in_progress_mission_data = \
            service.filter_and_categorize_mission_data(m_config_qs, m_progresses_dict)

        self.assertEqual(len(new_mission_data), 1)
        self.assertEqual(len(repeat_mission_data), 1)
        self.assertEqual(len(in_progress_mission_data), 1)

        new_mission_data = new_mission_data[0]
        repeat_mission_data = repeat_mission_data[0]
        in_progress_mission_data = in_progress_mission_data[0]

        self.assertEqual(in_progress_mission_data.mission_config.id, self.mission_config_1.id)
        self.assertEqual(repeat_mission_data.mission_config.id, self.mission_config_3.id)
        self.assertEqual(new_mission_data.mission_config.id, self.mission_config_2.id)

        self.assertEqual(
            repeat_mission_data.mission_progress.id, self.complete_m_progress.id
        )
        self.assertEqual(
            in_progress_mission_data.mission_progress.id, self.in_progress_m_progress.id
        )

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_new_mission_progresses(self, mock_localtime, mock_send_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # new mission data
        new_mission_progress_qs = MissionProgress.objects.filter(
            mission_config=self.mission_config_2,
            customer_id=self.customer.id
        )
        self.assertEqual(new_mission_progress_qs.count(), 1)

        new_mission_progress = new_mission_progress_qs.last()
        self.assertEqual(new_mission_progress.mission_config.id, self.mission_config_2.id)
        self.assertEqual(new_mission_progress.repeat_number, 1)
        self.assertEqual(new_mission_progress.is_latest, True)
        self.assertEqual(new_mission_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        reference_data = new_mission_progress.reference_data
        self.assertEqual(len(reference_data['loan_ids']), 1)
        self.assertEqual(reference_data['loan_ids'][0], loan.id)

        mission_target_progress_qs = new_mission_progress.missiontargetprogress_set.all()
        self.assertEqual(mission_target_progress_qs.count(), 1)

        mission_target_progress = mission_target_progress_qs.last()
        self.assertEqual(mission_target_progress.mission_target.id, self.mission_target_2.id)
        self.assertEqual(mission_target_progress.type, self.mission_target_2.type)
        self.assertEqual(mission_target_progress.category, self.mission_target_2.category)
        self.assertEqual(mission_target_progress.value, loan.loan_amount)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_repeat_mission_progresses(self, mock_localtime, mock_send_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # repeat mission data
        repeat_mission_progress_qs = MissionProgress.objects.filter(
            mission_config=self.mission_config_3,
            customer_id=self.customer.id
        )
        self.assertEqual(repeat_mission_progress_qs.count(), 2)

        new_mission_progress = repeat_mission_progress_qs.last()
        self.assertEqual(new_mission_progress.mission_config.id, self.mission_config_3.id)
        self.assertEqual(new_mission_progress.repeat_number, 2)
        self.assertEqual(new_mission_progress.is_latest, True)
        self.assertEqual(new_mission_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        reference_data = new_mission_progress.reference_data
        self.assertEqual(len(reference_data['loan_ids']), 1)
        self.assertEqual(reference_data['loan_ids'][0], loan.id)

        # test mission target progress
        mission_target_progress_qs = new_mission_progress.missiontargetprogress_set.all()
        self.assertEqual(mission_target_progress_qs.count(), 2)

        mission_target_progress_1 = mission_target_progress_qs.first()
        self.assertEqual(mission_target_progress_1.mission_target.id, self.mission_target_1.id)
        self.assertEqual(mission_target_progress_1.type, self.mission_target_1.type)
        self.assertEqual(mission_target_progress_1.category, self.mission_target_1.category)
        self.assertEqual(mission_target_progress_1.value, 1)

        mission_target_progress_2 = mission_target_progress_qs.last()
        self.assertEqual(mission_target_progress_2.mission_target.id, self.mission_target_2.id)
        self.assertEqual(mission_target_progress_2.type, self.mission_target_2.type)
        self.assertEqual(mission_target_progress_2.category, self.mission_target_2.category)
        self.assertEqual(mission_target_progress_2.value, loan.loan_amount)

        # test old mission_progress
        old_mission_progress = repeat_mission_progress_qs.first()
        self.assertEqual(old_mission_progress.id, self.complete_m_progress.id)
        self.assertEqual(old_mission_progress.mission_config.id, self.mission_config_3.id)
        self.assertEqual(old_mission_progress.repeat_number, 1)
        self.assertEqual(old_mission_progress.is_latest, False)
        self.assertEqual(old_mission_progress.status, MissionProgressStatusConst.CLAIMED)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_in_progress_mission_progresses(self, mock_localtime, mock_send_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # in_progress mission data
        in_progress_qs = MissionProgress.objects.filter(
            mission_config=self.mission_config_1,
            customer_id=self.customer.id
        )
        self.assertEqual(in_progress_qs.count(), 1)

        in_progress = in_progress_qs.last()
        self.assertEqual(in_progress.mission_config.id, self.mission_config_1.id)
        self.assertEqual(in_progress.repeat_number, 2)
        self.assertEqual(in_progress.is_latest, True)
        self.assertEqual(in_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        reference_data = in_progress.reference_data
        self.assertEqual(len(reference_data['loan_ids']), 2)
        self.assertEqual(reference_data['loan_ids'][-1], loan.id)

        mission_target_progress_qs = in_progress.missiontargetprogress_set.all()
        self.assertEqual(mission_target_progress_qs.count(), 1)

        mission_target_progress = mission_target_progress_qs.last()
        self.assertEqual(mission_target_progress.mission_target.id, self.mission_target_1.id)
        self.assertEqual(mission_target_progress.type, self.mission_target_1.type)
        self.assertEqual(mission_target_progress.category, self.mission_target_1.category)
        self.assertEqual(mission_target_progress.value, 2)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_create_new_mission_progress_with_inactive_mission(self, mock_localtime, mock_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        # Cannot create new mission progress when mission config is_active = False
        self.mission_config_2.update_safely(
            is_active=False
        )
        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # check NEW mission progress
        new_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_2,
            is_latest=True,
        ).last()

        self.assertIsNone(new_m_progress)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_repeat_mission_progress_with_inactive_missions(self, mock_localtime, mock_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        # Cannot repeat mission progress with inactive mission
        self.mission_config_3.update_safely(
            is_active=False
        )

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # check REPEAT mission progress
        repeat_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_3,
        )

        self.assertEqual(repeat_m_progress.count(), 1)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_update_in_progress_m_progress_with_inactive_mission(self, mock_localtime, mock_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        # Still can be updated mission progress when mission config is_active = False
        self.mission_config_1.update_safely(
            is_active=False
        )
        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # check IN PROGRESS mission progress still can be updated
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_update_mission_progress_with_deleted_mission(self, mock_localtime, mock_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        # Still can be updated mission progress when mission config is_active = False
        self.mission_config_1.update_safely(
            is_deleted=True
        )
        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # check IN PROGRESS mission progress still can be updated
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertIsNotNone(in_progress_m_progress)
        self.assertEqual(in_progress_m_progress.id, self.in_progress_m_progress.id)
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.IN_PROGRESS)
        reference_data = in_progress_m_progress.reference_data
        self.assertIsNotNone(len(reference_data['loan_ids']))
        self.assertTrue(loan.id not in reference_data['loan_ids'])

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_complete_mission_progress(self, mock_localtime, mock_send_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )
        self.target_in_progress.update_safely(value=2)

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        # check IN PROGRESS mission progress
        in_progress_m_progress = MissionProgress.objects.filter(
            customer_id=self.customer.id,
            mission_config=self.mission_config_1,
            is_latest=True,
        ).last()
        self.assertEqual(in_progress_m_progress.status, MissionProgressStatusConst.COMPLETED)

    @mock.patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    @mock.patch('django.utils.timezone.localtime')
    def test_get_mission_progress_data_to_send_moengage(self, mock_localtime, mock_send_noti):
        mock_localtime.return_value = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        loan = LoanFactory(
            customer=self.customer,
            loan_amount=2000000,
            loan_duration=6,
            transaction_method_id=TransactionMethodCode.OTHER.code
        )

        service = TransactionMissionProgressService(loan=loan)
        service.process()

        new_mission_progress_qs = MissionProgress.objects.filter(
            mission_config=self.mission_config_2,
            customer_id=self.customer.id
        )
        repeat_mission_progress_qs = MissionProgress.objects.filter(
            mission_config=self.mission_config_3,
            customer_id=self.customer.id
        )

        moengage_data = [
            {
                'mission_progress_id': new_mission_progress_qs[0].id,
                'status': MissionProgressStatusConst.IN_PROGRESS
            },
            {
                'mission_progress_id': repeat_mission_progress_qs.filter(is_latest=False).last().id,
                'status': MissionProgressStatusConst.CLAIMED
            },
            {
                'mission_progress_id': repeat_mission_progress_qs.filter(is_latest=True).last().id,
                'status': MissionProgressStatusConst.IN_PROGRESS
            },
        ]
        mock_send_noti.assert_called_with(self.customer.id, moengage_data)
