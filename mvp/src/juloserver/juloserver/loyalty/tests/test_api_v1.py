import datetime
import json
import pytz

from django.utils import timezone
from factory import Iterator
from juloserver.julo.statuses import ApplicationStatusCodes
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_405_METHOD_NOT_ALLOWED,
)
from rest_framework.test import APIClient, APITestCase
from django.test.testcases import TestCase
from mock import patch

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.exceptions import GopayClientException
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory, ApplicationFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    AccountingCutOffDateFactory,
    BankFactory,
    ProductLineFactory,
)
from juloserver.julo.constants import ProductLineCodes
from juloserver.loyalty.constants import (
    DailyCheckinConst,
    DailyCheckinMessageConst,
    MissionMessageConst,
    MissionCategoryConst,
    MissionProgressStatusConst,
    MissionRewardTypeConst,
    MissionCriteriaTypeConst,
    MissionCriteriaValueConst,
    FeatureNameConst,
    MissionFilterCategoryConst,
    PointRedeemReferenceTypeConst,
    RedemptionMethodErrorMessage,
    PointTransferErrorMessage,
    APIVersionConst,
    MissionTargetTypeConst,
)
from juloserver.loyalty.services.services import update_customer_total_points
from juloserver.loyalty.tests.factories import (
    DailyCheckinFactory,
    DailyCheckinProgressFactory,
    LoyaltyPointFactory,
    MissionConfigFactory,
    MissionProgressFactory,
    MissionRewardFactory,
    MissionCriteriaFactory,
    MissionConfigCriteriaFactory,
    PointHistoryFactory,
    PointEarningFactory,
    PointRedeemFSFactory,
    LoyaltyGopayTransferTransactionFactory,
    PointUsageHistoryFactory,
    MissionTargetProgressFactory,
    MissionTargetFactory,
    MissionConfigTargetFactory,
)
from juloserver.loyalty.models import (
    PointEarning,
    PointHistory,
    MissionProgressHistory,
    PointUsageHistory,
    LoyaltyGopayTransferTransaction,
)
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.julo.models import Payment, PaybackTransaction, StatusLookup


class LoyaltyPointInfoTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = ProductLineCodes.J1
        self.product_line.save()
        self.status_lookup = StatusLookupFactory()
        self.status_lookup.status_code = ApplicationStatusCodes.LOC_APPROVED
        self.status_lookup.save()
        self.application = ApplicationFactory(customer=self.customer)
        self.application.product_line = self.product_line
        self.application.application_status = self.status_lookup
        self.application.save()

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.url = '/api/loyalty/v1/info'
        self.query_params = {'categories': 'Semua'}

        LoyaltyPointFactory(customer_id=self.customer.id, total_point=24000)
        self.set_up_feature_settings()
        self.set_up_mission_rewards()
        self.set_up_mission_configs()
        self.set_up_mission_criteria()
        self.set_up_mission_target()
        self.set_up_mission_config_and_criteria()
        self.set_up_mission_config_and_target()
        self.set_up_mission_progresses()

    def set_up_feature_settings(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.MISSION_FILTER_CATEGORY,
            is_active=True,
            parameters={
                'search_categories': [
                    {'category': MissionFilterCategoryConst.ALL_MISSIONS, 'is_active': True},
                    {'category': MissionFilterCategoryConst.ON_GOING, 'is_active': True},
                    {'category': MissionFilterCategoryConst.COMPLETED, 'is_active': True},
                    {'category': MissionFilterCategoryConst.EXPIRED, 'is_active': True},
                ]
            },
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_CONVERT,
            is_active=True,
            parameters={
                'from_point_to_rupiah': 1.5
            },
        )

    def set_up_mission_rewards(self):
        self.general_reward = MissionRewardFactory(
            category=MissionCategoryConst.GENERAL,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 3000}
        )
        self.transaction_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 2000}
        )
        self.referral_reward = MissionRewardFactory(
            category=MissionCategoryConst.REFERRAL,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 6000}
        )

    def set_up_mission_configs(self):
        self.mission_1 = MissionConfigFactory(
            title="Mission 1",
            icon=None,
            reward=self.general_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=2,
            category=MissionCategoryConst.GENERAL,
            display_order=2,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 12, 23, 34, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V1,
        )
        self.mission_2 = MissionConfigFactory(
            title="Mission 2",
            icon=None,
            reward=self.general_reward,
            target_recurring=3,
            max_repeat=1,
            repetition_delay_days=0,
            category=MissionCategoryConst.GENERAL,
            display_order=3,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 12, 23, 34, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V1,
        )
        self.mission_3 = MissionConfigFactory(
            title="Mission 3",
            icon=None,
            reward=self.transaction_reward,
            target_recurring=4,
            max_repeat=2,
            repetition_delay_days=3,
            category=MissionCategoryConst.TRANSACTION,
            display_order=4,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 15, 20, 55, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V1,
        )
        self.mission_4 = MissionConfigFactory(
            title="Mission 4",
            icon=None,
            reward=self.transaction_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=6,
            category=MissionCategoryConst.TRANSACTION,
            display_order=5,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 12, 23, 34, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V1,
        )
        self.mission_5 = MissionConfigFactory(
            title="Mission 5",
            icon=None,
            reward=self.referral_reward,
            target_recurring=3,
            max_repeat=2,
            repetition_delay_days=3,
            category=MissionCategoryConst.REFERRAL,
            display_order=7,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 12, 23, 34, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V1,
        )

    def set_up_mission_criteria(self):
        self.mission_criteria_1 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                MissionCriteriaValueConst.TRANSACTION_METHODS: [{
                    MissionCriteriaValueConst.TRANSACTION_METHOD_ID: 2
                }]
            }
        )

        self.mission_criteria_2 = MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                MissionCriteriaValueConst.TRANSACTION_METHODS: [{
                    MissionCriteriaValueConst.TRANSACTION_METHOD_ID: 3
                }]
            }
        )

    def set_up_mission_target(self):
        self.target = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=3
        )

    def set_up_mission_config_and_criteria(self):
        MissionConfigCriteriaFactory(
            config=self.mission_3,
            criteria=self.mission_criteria_1
        )
        MissionConfigCriteriaFactory(
            config=self.mission_4,
            criteria=self.mission_criteria_2
        )

    def set_up_mission_config_and_target(self):
        MissionConfigTargetFactory(
            config=self.mission_2,
            target=self.target
        )

    def set_up_mission_progresses(self):
        self.mission_progress_1 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_2,
            repeat_number=1,
            recurring_number=1,
            status=MissionProgressStatusConst.IN_PROGRESS
        )
        self.mission_target_progress_1 = MissionTargetProgressFactory(
            mission_target=self.target,
            mission_progress=self.mission_progress_1,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=1
        )
        self.mission_progress_2 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_3,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.CLAIMED,
            completion_date=datetime.date(2024, 3, 25)
        )
        self.mission_progress_3 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_4,
            repeat_number=1,
            recurring_number=1,
            status=MissionProgressStatusConst.EXPIRED
        )
        self.mission_progress_4 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_5,
            repeat_number=1,
            recurring_number=3,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25)
        )

    def test_get_search_categories(self):
        url = '/api/loyalty/v1/get_search_categories'
        response = self.client.get(url)
        list_categories = ['Semua Misi', 'Sedang Berjalan', 'Selesai', 'Kedaluwarsa']
        self.assertEqual(response.json()['data'], list_categories)

    def test_get_customer_total_point(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['loyalty_point'])
        self.assertEqual(resp_data['loyalty_point']['customer_id'], self.customer.id)
        self.assertEqual(resp_data['loyalty_point']['total_point'], 24000)

    def test_get_convert_rate(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(resp_data['convert_rate_info'], '1 poin = Rp1.5')

    def test_mission_entry_point(self):
        FeatureSettingFactory(feature_name='loyalty_entry_point', is_active=True)
        self.url = '/api/loyalty/v1/loyalty_entry_point'
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(resp_data, {
            'loyalty_point': 24000,
            'has_new_reward': True,
            'label': 'Check-In!'
        })

    @patch('django.utils.timezone.now')
    def test_get_mission_list_no_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_5.id,
                "title": "Mission 5",
                "icon": None,
                "reward_points": 6000,
                "target_recurring": 3,
                "display_order": 7,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.REFERRAL,
                "transaction_method_id": None,
                "recurring_number": 3,
                "status": MissionProgressStatusConst.COMPLETED,
                "mission_progress_id": self.mission_progress_4.id,
                "completion_date": '2024-03-24T17:00:00Z',
            },
            {
                "mission_id": self.mission_2.id,
                "title": "Mission 2",
                "icon": None,
                "reward_points": 3000,
                "target_recurring": 3,
                "display_order": 3,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_1.id,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_1.id,
                "title": "Mission 1",
                "icon": None,
                "reward_points": 3000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 4,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 4,
                "status": MissionProgressStatusConst.CLAIMED,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": '2024-03-24T17:00:00Z',
            },
            {
                "mission_id": self.mission_4.id,
                "title": "Mission 4",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 3,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.EXPIRED,
                "mission_progress_id": self.mission_progress_3.id,
                "completion_date": None,
            }
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_list_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_2.id,
                "title": "Mission 2",
                "icon": None,
                "reward_points": 3000,
                "target_recurring": 3,
                "display_order": 3,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_1.id,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_1.id,
                "title": "Mission 1",
                "icon": None,
                "reward_points": 3000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_5.id,
                "title": "Mission 5",
                "icon": None,
                "reward_points": 6000,
                "target_recurring": 3,
                "display_order": 7,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.REFERRAL,
                "transaction_method_id": None,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 4,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 4,
                "status": MissionProgressStatusConst.CLAIMED,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": '2024-03-24T17:00:00Z',
            },
            {
                "mission_id": self.mission_4.id,
                "title": "Mission 4",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 3,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.EXPIRED,
                "mission_progress_id": self.mission_progress_3.id,
                "completion_date": None,
            }
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_list_resetable_with_completed_category(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        query_params = {'category': 'Selesai'}
        response = self.client.get(self.url, data=query_params)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = []

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_by_category_without_progress(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)

        user2 = AuthUserFactory()
        customer2 = CustomerFactory(user=user2)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user2.auth_expiry_token.key)

        query_params = {'category': 'Kedaluwarsa'}
        response = self.client.get(self.url, data=self.query_params)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'], [])

    @patch('django.utils.timezone.now')
    def test_get_mission_list_with_all_deleted_missions(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        self.mission_1.update_safely(is_deleted=True)
        self.mission_2.update_safely(is_deleted=True)
        self.mission_3.update_safely(is_deleted=True)
        self.mission_4.update_safely(is_deleted=True)
        self.mission_5.update_safely(is_deleted=True)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        self.assertEqual(resp_data['missions'], [])

    @patch('django.utils.timezone.now')
    def test_get_mission_list_with_deleted_mission(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        self.mission_2.update_safely(is_deleted=True)
        self.mission_1.update_safely(is_deleted=True)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_5.id,
                "title": "Mission 5",
                "icon": None,
                "reward_points": 6000,
                "target_recurring": 3,
                "display_order": 7,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.REFERRAL,
                "transaction_method_id": None,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
            },
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 4,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 4,
                "status": MissionProgressStatusConst.CLAIMED,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": '2024-03-24T17:00:00Z',
            },
            {
                "mission_id": self.mission_4.id,
                "title": "Mission 4",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 3,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.EXPIRED,
                "mission_progress_id": self.mission_progress_3.id,
                "completion_date": None,
            }
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)


class LoyaltyPointMissionDetailTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 2000}
        )
        self.mission_criteria=MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                MissionCriteriaValueConst.TRANSACTION_METHODS: [{
                    MissionCriteriaValueConst.TRANSACTION_METHOD_ID: 2
                }]
            }
        )
        self.mission = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            title="Mission",
            icon=None,
            reward=self.mission_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=2,
            display_order=2,
            description="<p>Description<p>",
            tnc="<p>TnC<p>",
            api_version=APIVersionConst.V1,
        )
        MissionConfigCriteriaFactory(
            config=self.mission,
            criteria=self.mission_criteria
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.url = '/api/loyalty/v1/mission/details/'

    def test_get_mission_detail_not_found(self):
        url = self.url + str(0)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['errors'][0], MissionMessageConst.ERROR_MISSION_CONFIG_NOT_FOUND
        )

    def test_get_mission_detail_without_progress(self):
        url = self.url + str(self.mission.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            {
                "mission_id": self.mission.id,
                "title": "Mission",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": None,
                "completion_date": None,
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
            },
        )

    def test_get_mission_detail_with_progress(self):
        target = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=3
        )
        MissionConfigTargetFactory(
            config=self.mission,
            target=target
        )
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=1,
            recurring_number=1,
            status=MissionProgressStatusConst.IN_PROGRESS
        )
        MissionTargetProgressFactory(
            mission_target=target,
            mission_progress=mission_progress,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=1
        )

        url = self.url + str(self.mission.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            {
                "mission_id": self.mission.id,
                "title": "Mission",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": None,
                "completion_date": None,
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 1,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": mission_progress.id,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
            },
        )

    @patch('django.utils.timezone.now')
    def test_get_mission_detail_with_progress_no_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 26, 0, 0, 0)
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=1,
            recurring_number=3,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25)
        )

        url = self.url + str(self.mission.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            {
                "mission_id": self.mission.id,
                "title": "Mission",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": None,
                "completion_date": "2024-03-24T17:00:00Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 3,
                "status": MissionProgressStatusConst.COMPLETED,
                "mission_progress_id": mission_progress.id,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
            },
        )

    @patch('django.utils.timezone.now')
    def test_get_mission_detail_with_progress_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=1,
            recurring_number=3,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25)
        )

        url = self.url + str(self.mission.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            {
                "mission_id": self.mission.id,
                "title": "Mission",
                "icon": None,
                "reward_points": 2000,
                "target_recurring": 3,
                "display_order": 2,
                "expiry_date": None,
                "completion_date": None,
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "recurring_number": 0,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
            },
        )


class LoyaltyPointMissionClaimTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_point = LoyaltyPointFactory(
            customer_id=self.customer.id,
            total_point=60000
        )
        self.fixed_mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.FIXED,
            value={MissionRewardTypeConst.FIXED: 10000}
        )
        self.percentage_mission_reward = MissionRewardFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionRewardTypeConst.PERCENTAGE,
            value={
                MissionRewardTypeConst.MAX_POINTS: 50000,
                MissionRewardTypeConst.PERCENTAGE: 5
            }
        )
        self.mission_criteria=MissionCriteriaFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionCriteriaTypeConst.TRANSACTION_METHOD,
            value={
                MissionCriteriaValueConst.TRANSACTION_METHOD_ID: 2
            }
        )
        self.mission = MissionConfigFactory(
            category=MissionCategoryConst.TRANSACTION,
            title="Mission",
            icon=None,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=2,
            display_order=2,
            description="<p>Description<p>",
            tnc="<p>TnC<p>"
        )
        MissionConfigCriteriaFactory(
            config=self.mission,
            criteria=self.mission_criteria
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.url = '/api/loyalty/v1/mission/claim'

    def test_claim_not_found_mission_progress(self):
        response = self.client.post(self.url, data={'mission_progress_id': 0})
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            MissionMessageConst.ERROR_MISSION_PROGRESS_NOT_FOUND,
            response.json()['errors']
        )

    @patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    def test_claim_not_allowed_mission_progress(self, mock_send_to_me):
        customer = CustomerFactory(user=AuthUserFactory())
        mission_progress = MissionProgressFactory(
            customer_id=customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.CLAIMED,
            completion_date=datetime.date(2024, 3, 25),
            point_earning=None
        )
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            MissionMessageConst.ERROR_MISSION_PROGRESS_NOT_FOUND,
            response.json()['errors']
        )
        mock_send_to_me.assert_not_called()

    @patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    def test_claim_invalid_status_mission_progress(self, mock_send_to_me):
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.CLAIMED,
            completion_date=datetime.date(2024, 3, 25),
            point_earning=None
        )
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            MissionMessageConst.ERROR_MISSION_PROGRESS_NOT_FOUND,
            response.json()['errors']
        )
        mock_send_to_me.assert_not_called()

    @patch(
        'juloserver.moengage.services.use_cases'
        '.send_loyalty_mission_progress_data_event_to_moengage.delay'
    )
    def test_claim_mission_progress_with_fixed_reward(self, mock_send_to_me):
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25),
            point_earning=None
        )
        self.mission.update_safely(reward=self.fixed_mission_reward)
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['point_amount'], 10000)

        mock_send_to_me.assert_called_with(
            self.customer.id,
            [{
                'mission_progress_id': mission_progress.id,
                'status': MissionProgressStatusConst.CLAIMED,
            }]
        )

    def test_claim_mission_progress_with_percentage_reward_lower_than_max_point(self):
        loan_1 = LoanFactory(customer=self.customer, loan_amount=300000)
        loan_2 = LoanFactory(customer=self.customer, loan_amount=500000)
        self.mission.update_safely(reward=self.percentage_mission_reward)
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25),
            reference_data={'loan_ids': [loan_1.id, loan_2.id]},
            point_earning=None
        )
        self.mission.update_safely(reward=self.percentage_mission_reward)
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['point_amount'], 40000)

    def test_claim_mission_progress_with_percentage_reward_greater_than_max_point(self):
        loan_1 = LoanFactory(customer=self.customer, loan_amount=1000000)
        loan_2 = LoanFactory(customer=self.customer, loan_amount=500000)
        self.mission.update_safely(reward=self.percentage_mission_reward)
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25),
            reference_data={'loan_ids': [loan_1.id, loan_2.id]},
            point_earning=None
        )
        self.mission.update_safely(reward=self.percentage_mission_reward)
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['point_amount'], 50000)

    def test_claim_mission_progress_update_customer_point(self):
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=2,
            recurring_number=4,
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25),
            point_earning=None
        )
        self.mission.update_safely(reward=self.fixed_mission_reward)
        response = self.client.post(self.url, data={'mission_progress_id': mission_progress.id})
        self.assertEqual(response.status_code, 200)

        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        point_earning = PointEarning.objects.filter(customer_id=self.customer.id).last()
        status_history = MissionProgressHistory.objects.filter(
            mission_progress=mission_progress, field='status'
        ).last()
        point_earning_history = MissionProgressHistory.objects.filter(
            mission_progress=mission_progress, field='point_earning'
        ).last()

        # Check customer total point
        self.customer_point.refresh_from_db()
        self.assertEqual(self.customer_point.total_point, 70000)

        # Check point history
        self.assertEqual(point_history.old_point, 60000)
        self.assertEqual(point_history.new_point, 70000)
        self.assertEqual(point_history.change_reason, 'Mission')

        # Check point earning
        self.assertEqual(point_earning.points, 10000)
        self.assertEqual(point_earning.point_history_id, point_history.id)

        # Check mission progress history
        self.assertEqual(status_history.old_value, MissionProgressStatusConst.COMPLETED)
        self.assertEqual(status_history.new_value, MissionProgressStatusConst.CLAIMED)

        self.assertEqual(point_earning_history.old_value, None)
        self.assertEqual(point_earning_history.new_value, str(point_earning.id))

        # Check mission progress
        mission_progress.refresh_from_db()
        self.assertEqual(mission_progress.status, MissionProgressStatusConst.CLAIMED)
        self.assertEqual(mission_progress.point_earning, point_earning)


class DailyCheckinTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_point = LoyaltyPointFactory(customer_id=self.customer.id)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        daily_reward = json.loads('{"1": 10, "2": 10, "3":10, "4":10, "5":10, "6":10, "default": 10 }')
        self.daily_checkin = DailyCheckinFactory(max_days_reach_bonus=7, daily_reward=daily_reward, reward=250, is_latest=True)
        self.daily_checkin_progress = DailyCheckinProgressFactory(customer_id=self.customer.id, daily_checkin=self.daily_checkin, is_latest=True)
        self.post_interface_url = '/api/loyalty/v1/daily-checkin'
        self.post_claim_url = '/api/loyalty/v1/daily-checkin/claim'

    # get success first day
    def test_get_success(self):
        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['daily_check_in'][1]['status'], DailyCheckinConst.STATUS_AVAILABLE)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success second day
    def test_get_success_second_day(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 1
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['daily_check_in'][1]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][2]['status'], DailyCheckinConst.STATUS_AVAILABLE)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get sucess reward day
    def test_get_success_reward_day(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 7
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][6]['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['daily_check_in'][6]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success reset after reward day
    def test_get_success_after_reward_day(self):
        # after reward day, a new circle will create
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 8
        self.daily_checkin_progress.is_completed = True
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success reset missed day
    def test_gets_success_reset_missed_day(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=2)
        self.daily_checkin_progress.days_count = 3
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success user continue existing daily check in with new daily-checkin config
    def test_get_success_continue_new_daily_checkin_config(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 3
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        self.daily_checkin.is_latest = False
        self.daily_checkin.save()
        daily_reward = json.loads('{"1": 10, "2": 40, "3":50}')
        self.daily_checkin = DailyCheckinFactory(max_days_reach_bonus=4, daily_reward=daily_reward, reward=1000, is_latest=True)

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][3]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][3]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success user reset existing daily check in with new daily-checkin config (missed-day)
    def test_get_success_reset_new_daily_checkin_config_completed(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 8
        self.daily_checkin_progress.is_completed = True
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        self.daily_checkin.is_latest = False
        self.daily_checkin.save()
        daily_reward = json.loads('{"1": 10, "2": 40, "3":50}')
        self.daily_checkin = DailyCheckinFactory(max_days_reach_bonus=4, daily_reward=daily_reward, reward=1000, is_latest=True)

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], self.daily_checkin.reward)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success user reset existing daily check in with new daily-checkin config (missed-day)
    def test_get_success_reset_new_daily_checkin_config(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=3)
        self.daily_checkin_progress.days_count = 3
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        self.daily_checkin.is_latest = False
        self.daily_checkin.save()
        daily_reward = json.loads('{"1": 10, "2": 40, "3":50}')
        self.daily_checkin = DailyCheckinFactory(max_days_reach_bonus=4, daily_reward=daily_reward, reward=1000, is_latest=True)

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], self.daily_checkin.reward)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # get success user without daily_checkin_progress (FTC)
    def test_get_success_ftc(self):
        self.daily_checkin_progress = None

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)
        self.assertEqual(resp_data['daily_check_in'][1]['status'], DailyCheckinConst.STATUS_AVAILABLE)
        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_LOCKED)
        self.assertEqual(resp_data['reward']['value'], 250)
        self.assertEqual(resp_data['is_claimable_today'], True)

    # POST success claim point
    def test_post_success(self):
        response = self.client.post(self.post_claim_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']
        self.assertEqual(resp_data['today_reward'], 10)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Harian')

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['is_claimable_today'], False)
        self.assertEqual(resp_data['daily_check_in'][1]['value'], 10)
        self.assertEqual(resp_data['daily_check_in'][1]['status'], DailyCheckinConst.STATUS_AVAILABLE)

    def test_post_success_second_day(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 1
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_claim_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 10)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Harian')

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][1]['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['is_claimable_today'], False)
        self.assertEqual(resp_data['is_claimable_today'], False)
        self.assertEqual(resp_data['daily_check_in'][2]['value'], 10)
        self.assertEqual(resp_data['daily_check_in'][2]['status'], DailyCheckinConst.STATUS_AVAILABLE)

    # POST success claim reward point
    def test_post_success_reward(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 7
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_claim_url)

        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 250)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Bonus')


    # POST success claim reward point
    def test_post_success_before_reward(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 6
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_claim_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 10)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Harian')

    def test_post_success_before_reward_special_case(self):
        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 6
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        daily_reward = json.loads('{"1": 100, "default":10}')
        self.daily_checkin = DailyCheckinFactory(max_days_reach_bonus=6, daily_reward=daily_reward, reward=250, is_latest=True)

        response = self.client.post(self.post_claim_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 10)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Harian')

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_AVAILABLE)
        self.assertEqual(resp_data['is_claimable_today'], False)

        resp_data = response.json()['data']

        d = timezone.localtime(timezone.now()).date() - datetime.timedelta(days=1)
        self.daily_checkin_progress.days_count = 7
        self.daily_checkin_progress.latest_update = d
        self.daily_checkin_progress.save()

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_TODAY)
        self.assertEqual(resp_data['is_claimable_today'], True)

        response = self.client.post(self.post_claim_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 250)

        # Check point history
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        self.assertEqual(point_history.change_reason, 'Poin Check-in Bonus')

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertEqual(resp_data['reward']['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['is_claimable_today'], False)

    # POST fail claim point after claiming
    def test_post_fail(self):
        response = self.client.post(self.post_claim_url)

        self.assertEqual(response.status_code, HTTP_200_OK)
        resp_data = response.json()['data']

        self.assertEqual(resp_data['today_reward'], 10)
        response = self.client.post(self.post_claim_url)
        resp = response.json()

        self.assertEqual(resp['errors'][0], DailyCheckinMessageConst.ERROR_HAS_BEEN_CLAIMED)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        response = self.client.post(self.post_interface_url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']

        self.assertIsNotNone(resp_data['daily_check_in'])
        self.assertEqual(resp_data['daily_check_in'][0]['status'], DailyCheckinConst.STATUS_CLAIMED)
        self.assertEqual(resp_data['is_claimable_today'], False)
        self.assertEqual(resp_data['daily_check_in'][0]['value'], 10)


class LoyaltyPointHistoryTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_point = LoyaltyPointFactory(
            customer_id=self.customer.id,
            total_point=1000
        )
        self.set_up_point_history_from_daily_checkin()
        self.set_up_point_history_from_bonus_checkin()
        self.set_up_point_history_from_mission_reward()
        self.set_up_point_history_from_expired_point_earning()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.base_url = '/api/loyalty/v1/point-history'

    def set_up_point_history_from_daily_checkin(self):
        self.point_history_1 = PointHistoryFactory(
            customer_id=self.customer.id,
            old_point=1000,
            new_point=1200,
            change_reason='Poin Check-in Harian'
        )
        self.point_history_1.update_safely(
            cdate=datetime.datetime(2024, 5, 8, 10, 23, 34, tzinfo=pytz.UTC)
        )

    def set_up_point_history_from_bonus_checkin(self):
        self.point_history_2 = PointHistoryFactory(
            customer_id=self.customer.id,
            old_point=1200,
            new_point=2000,
            change_reason='Poin Check-in Bonus'
        )
        self.point_history_2.update_safely(
            cdate=datetime.datetime(2024, 5, 8, 12, 23, 34, tzinfo=pytz.UTC)
        )

    def set_up_point_history_from_mission_reward(self):
        self.point_history_3 = PointHistoryFactory(
            customer_id=self.customer.id,
            old_point=2000,
            new_point=5000,
            change_reason='Mission 1'
        )
        self.point_history_3.update_safely(
            cdate=datetime.datetime(2024, 5, 8, 14, 23, 34, tzinfo=pytz.UTC)
        )

    def set_up_point_history_from_expired_point_earning(self):
        self.point_history_4 = PointHistoryFactory(
            customer_id=self.customer.id,
            old_point=5000,
            new_point=1000,
            change_reason='Kedaluwarsa'
        )
        self.point_history_4.update_safely(
            cdate=datetime.datetime(2024, 5, 8, 17, 23, 34, tzinfo=pytz.UTC)
        )

    def test_get_point_history_without_pagination(self):
        url = self.base_url
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            [
                {
                    'title': 'Kedaluwarsa',
                    'created_at': '2024-05-08T17:23:34Z',
                    'point_amount': -4000
                },
                {
                    'title': 'Mission 1',
                    'created_at': '2024-05-08T14:23:34Z',
                    'point_amount': 3000,
                },
                                {
                    'title': 'Poin Check-in Bonus',
                    'created_at': '2024-05-08T12:23:34Z',
                    'point_amount': 800,
                },
                {
                    'title': 'Poin Check-in Harian',
                    'created_at': '2024-05-08T10:23:34Z',
                    'point_amount': 200
                }
            ]
        )
        self.assertIsNone(response.json()['next_page'])
        self.assertEqual(response.json()['page_size'], 4)

    def test_get_point_history_with_pagination(self):
        url = self.base_url + '?page=1&page_size=3'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            [
                {
                    'title': 'Kedaluwarsa',
                    'created_at': '2024-05-08T17:23:34Z',
                    'point_amount': -4000
                },
                {
                    'title': 'Mission 1',
                    'created_at': '2024-05-08T14:23:34Z',
                    'point_amount': 3000,
                },
                                {
                    'title': 'Poin Check-in Bonus',
                    'created_at': '2024-05-08T12:23:34Z',
                    'point_amount': 800,
                }
            ]
        )
        self.assertEqual(response.json()['next_page'], 2)
        self.assertEqual(response.json()['page_size'], 3)

        url = self.base_url + '?page=2&page_size=3'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(
            resp_data,
            [
                {
                    'title': 'Poin Check-in Harian',
                    'created_at': '2024-05-08T10:23:34Z',
                    'point_amount': 200
                }
            ]
        )
        self.assertIsNone(response.json()['next_page'])
        self.assertEqual(response.json()['page_size'], 1)


class TestAccountPaymentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)

    def test_get_account_payment_list(self):
        res = self.client.get('/api/loyalty/v1/account-payment')
        assert res.status_code == 200
        due_date_str = self.account_payment.due_date.strftime('%Y-%m-%d')
        expected_response = {
            "success": True,
            "data": {
                "account_payments_list": [{
                    "due_status": "Belum jatuh tempo",
                    "due_amount": 300000,
                    "due_date": due_date_str,
                    "paid_date": None,
                    "account_payment_id": self.account_payment.id
                }]
            },
            "errors": []
        }
        self.assertEqual(res.json(), expected_response)


class TestPointInformationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.loyalty_point = LoyaltyPointFactory(customer_id=self.customer.id, total_point=5000)
        self.point_redeem_fs = PointRedeemFSFactory(parameters={
            PointRedeemReferenceTypeConst.REPAYMENT: {
                'is_active': True
            }
        })

    @patch('juloserver.loyalty.services.services.timezone')
    def test_point_information(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2024, month=12, day=31, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        self.point_earnings = PointEarningFactory.create_batch(
            4,
            customer_id=self.customer.id,
            loyalty_point=self.loyalty_point,
            points=Iterator([500, 1500, 3000, 5000]),
            is_expired=Iterator([False, False, False, True]),
            expiry_date=Iterator([
                datetime.date(2024, 12, 30),
                datetime.date(2024, 12, 31),
                mock_now.date() + datetime.timedelta(days=365),
                mock_now.date()
            ])
        )

        res = self.client.get('/api/loyalty/v1/point-information')
        expected_response = {
            "success": True,
            "data": {
                "point_amount": 5000,
                "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah "
                                    "saldo cashback kamu",
                "amount_deduct": 0,
                'eligible_for_point_repayment': {
                    'is_valid': True,
                    'error_msg': None
                },
                "point_expiry_info": "2.000 Poin kamu akan kedaluwersa pada 31 Dec 2024"
            },
            "errors": []
        }
        assert res.status_code == 200
        self.assertEqual(res.json(), expected_response)
        parameters = self.point_redeem_fs.parameters
        parameters[PointRedeemReferenceTypeConst.REPAYMENT]['is_active'] = False
        self.point_redeem_fs.parameters = parameters
        self.point_redeem_fs.save()
        res = self.client.get('/api/loyalty/v1/point-information')
        expected_response = {
            "success": True,
            "data": {
                "point_amount": 5000,
                "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah "
                                    "saldo cashback kamu",
                "amount_deduct": 0,
                'eligible_for_point_repayment': {
                    'is_valid': False,
                    'error_msg': 'Pencairan point melalui metode ini untuk sementara tidak '
                                 'dapat dilakukan'
                },
                "point_expiry_info": "2.000 Poin kamu akan kedaluwersa pada 31 Dec 2024"
            },
            "errors": []
        }
        assert res.status_code == 200
        self.assertEqual(res.json(), expected_response)


class TestPointPaymentAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.loyalty_point = LoyaltyPointFactory(customer=self.customer, total_point=10_000)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.point_redeem_fs = PointRedeemFSFactory(parameters={
            PointRedeemReferenceTypeConst.REPAYMENT: {
                'is_active': True
            }
        })
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=100_000,
            loan_xid=1000003076,
            loan_status=self.status,
            loan_duration=1,
        )
        self.last_payment = self.loan.payment_set.last()
        AccountingCutOffDateFactory()
        self.account_payment = AccountPaymentFactory(account=self.account, due_amount=20_000)
        self.last_payment.update_safely(account_payment=self.account_payment)

    @patch('juloserver.loyalty.views.views_api_v1.pay_next_loan_payment')
    def test_point_payment_success(self, mock_pay_next_loan_payment):
        mock_pay_next_loan_payment.return_value = True, 100, 0, 0
        data = {'pin': '123456'}
        response = self.client.post('/api/loyalty/v1/payment', data=data, format='json')
        self.point_redeem_fs.refresh_from_db()
        assert response.status_code == 200

    @patch('juloserver.loyalty.views.views_api_v1.pay_next_loan_payment')
    def test_point_payment_failed(self, mock_pay_next_loan_payment):
        mock_pay_next_loan_payment.return_value = False, None, 0, 0
        data = {'pin': '123456'}
        response = self.client.post('/api/loyalty/v1/payment', data=data, format='json')
        assert response.status_code == 400
        assert (
            str(response.json()['errors'][0])
            == 'Tidak bisa melakukan pembayaran tagihan karena belum ada jadwal pembayaran'
        )

    @patch('django.utils.timezone.now')
    def test_test_pay_next_loan_payment(self, mock_timezone):
        # customer have 10.000 point/ account payment = 20000,
        # after deduct customer remaining 0 point/ account payment = 10.000/ status still 310
        mock_timezone.return_value = datetime.datetime(2020, 12, 1, 23, 59, 59, tzinfo=pytz.UTC)
        data = {'pin': '123456'}
        response = self.client.post('/api/loyalty/v1/payment', data=data, format='json')
        expected_response = {
            "success": True,
            "data": {
                "total_point": 0,
                "amount_deduct": 10000,
                "point_deduct": 10000,
                "request_time": '2020-12-01T23:59:59Z'
            },
            "errors": []
        }
        self.assertEqual(response.json(), expected_response)
        payments = Payment.objects.filter(loan_id=self.loan.id)
        payment = payments[0]
        account_payment = payment.account_payment
        self.assertEqual(account_payment.due_amount, 10_000)
        self.assertEqual(account_payment.paid_amount, 10_000)
        self.assertEqual(account_payment.status_id, 310)
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        expected_point_history = {
            "old_point": 10_000,
            "new_point": 0,
            "change_reason": "Potongan Tagihan Cicilan Rp 10.000",
        }
        self.assertEqual(expected_point_history, {
            "old_point": point_history.old_point,
            "new_point": point_history.new_point,
            "change_reason": point_history.change_reason,
        })
        point_usage_history = PointUsageHistory.objects.get(point_history_id=point_history.id)
        payback_transaction = PaybackTransaction.objects.filter(
            is_processed=True,
            customer=self.customer,
            payback_service='loyalty_point'
        ).last()
        expected_point_usage_history = {
            "reference_type": "repayment",
            "reference_id": payback_transaction.id,
            "point_amount": 10_000,
            "exchange_amount": 10_000,
            "exchange_amount_unit": "rupiah",
            "point_history_id": point_history.id
        }
        self.assertEqual(expected_point_usage_history, {
            "reference_type": point_usage_history.reference_type,
            "reference_id": payback_transaction.id,
            "point_amount": point_usage_history.point_amount,
            "exchange_amount": point_usage_history.exchange_amount,
            "exchange_amount_unit": point_usage_history.exchange_amount_unit,
            "point_history_id": point_history.id
        })

        # add 50.000 point for customer
        # after deduct again customer remaining 40.000 point/ account payment = 0/ status still 330
        self.loyalty_point.refresh_from_db()
        update_customer_total_points(
            customer_id=self.customer.id,
            customer_point=self.loyalty_point,
            point_amount=50_000,
            reason='add more point',
            adding=True
        )
        response = self.client.post('/api/loyalty/v1/payment', data=data, format='json')
        expected_response = {
            "success": True,
            "data": {
                "total_point": 40_000,
                "amount_deduct": 10000,
                "point_deduct": 10000,
                "request_time": '2020-12-01T23:59:59Z',
            },
            "errors": []
        }
        self.assertEqual(response.json(), expected_response)
        payments = Payment.objects.filter(loan_id=self.loan.id)
        payment = payments[0]
        account_payment = payment.account_payment
        self.assertEqual(account_payment.due_amount, 0)
        self.assertEqual(account_payment.paid_amount, 20_000)
        self.assertEqual(account_payment.status_id, 330)
        point_history = PointHistory.objects.filter(customer_id=self.customer.id).last()
        expected_point_history = {
            "old_point": 50_000,
            "new_point": 40_000,
            "change_reason": "Potongan Tagihan Cicilan Rp 10.000",
        }
        self.assertEqual(expected_point_history, {
            "old_point": point_history.old_point,
            "new_point": point_history.new_point,
            "change_reason": point_history.change_reason,
        })

        point_usage_history = PointUsageHistory.objects.get(point_history_id=point_history.id)
        payback_transaction = PaybackTransaction.objects.filter(
            is_processed=True,
            customer=self.customer,
            payback_service='loyalty_point'
        ).last()
        expected_point_usage_history = {
            "reference_type": "repayment",
            "reference_id": payback_transaction.id,
            "point_amount": 10_000,
            "exchange_amount": 10_000,
            "exchange_amount_unit": "rupiah",
            "point_history_id": point_history.id
        }
        self.assertEqual(expected_point_usage_history, {
            "reference_type": point_usage_history.reference_type,
            "reference_id": payback_transaction.id,
            "point_amount": point_usage_history.point_amount,
            "exchange_amount": point_usage_history.exchange_amount,
            "exchange_amount_unit": point_usage_history.exchange_amount_unit,
            "point_history_id": point_history.id
        })


class TestPointTransferBottomSheetAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.loyalty_point = LoyaltyPointFactory(customer_id=self.customer.id, total_point=50_000)
        self.base_url = '/api/loyalty/v1/point-transfer-bottom-sheet'

        self.setup_point_redeem_fs()
        self.setup_conversion_rate_fs()

    def setup_point_redeem_fs(self):
        self.point_redeem_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_REDEEM,
            is_active=True,
            parameters={
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
                }
            }
        )

    def setup_conversion_rate_fs(self):
        self.point_conversion_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_CONVERT,
            is_active=True,
            parameters={
                "from_point_to_rupiah": 1.3
            }
        )

    def test_missing_query_params(self):
        url = self.base_url

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)


    def test_transfer_method_not_active(self):
        self.point_redeem_fs.parameters['gopay_transfer']['is_active'] = False
        self.point_redeem_fs.save()

        url = self.base_url + '?redemption_method=gopay_transfer&nominal_amount=30000'

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json()['errors'],
            [RedemptionMethodErrorMessage.UNAVAILABLE_METHOD]
        )

    def test_transfer_method_not_exist(self):
        url = self.base_url + '?redemption_method=dana_transfer&nominal_amount=30000'

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json()['errors'],
            [RedemptionMethodErrorMessage.UNAVAILABLE_METHOD]
        )

    def test_bottom_sheet_success(self):
        url = self.base_url + '?redemption_method=gopay_transfer&nominal_amount=30000'

        res = self.client.get(url)
        expected_response = {
            "gross_nominal_amount": 30_000,
            "point_amount": 23_077,
            "admin_fee": 110, # partner_fee: 110, julo_fee: 0
            "net_nominal_amount": 29890,
            "detail_fees": {"julo_fee": 0, "partner_fee": 110},
        }
        self.assertEqual(res.status_code, HTTP_200_OK)
        self.assertEqual(res.json()['data'], expected_response)

    def test_bottom_sheet_invalid_nominal_amount(self):
        url = self.base_url + '?redemption_method=gopay_transfer&nominal_amount=80000'

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json()['errors'],
            [PointTransferErrorMessage.INVALID_NOMINAL_AMOUNT]
        )

        url = self.base_url + '?redemption_method=gopay_transfer&nominal_amount=10000'

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json()['errors'],
            [PointTransferErrorMessage.INVALID_NOMINAL_AMOUNT]
        )

    def test_bottom_sheet_insufficient_nominal_amount(self):
        self.point_conversion_fs.parameters['from_point_to_rupiah'] = 1
        self.point_conversion_fs.save()

        self.point_redeem_fs.parameters['gopay_transfer']['minimum_withdrawal'] = 50000
        self.point_redeem_fs.parameters['gopay_transfer']['partner_fee'] = 50000
        self.point_redeem_fs.save()

        url = self.base_url + '?redemption_method=gopay_transfer&nominal_amount=50000'

        res = self.client.get(url)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json()['errors'],
            [PointTransferErrorMessage.INSUFFICIENT_AMOUNT]
        )


class TestPointTransferToGopay(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.loyalty_point = LoyaltyPointFactory(customer=self.customer, total_point=110_000)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.point_redeem_fs = PointRedeemFSFactory(parameters={
            PointRedeemReferenceTypeConst.REPAYMENT: {
                'is_active': True
            },
            PointRedeemReferenceTypeConst.GOPAY_TRANSFER: {
                'is_active': True,
                'julo_fee': 1_000,
                'partner_fee': 1_000,
                'minimum_withdrawal': 10_000
            }
        })
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.bank = BankFactory(
            bank_code='gopay',
            bank_name='gopay',
            xendit_bank_code='gopay',
            swift_bank_code='01',
            bank_name_frontend='gopay'
        )

    @patch('juloserver.loyalty.views.views_api_v1.GopayService')
    def test_gopay_service_success_basic(self, mock_gopay_service):
        mock_gopay_transfer = LoyaltyGopayTransferTransactionFactory(customer_id=self.customer.id)
        mock_point_usage_history = PointUsageHistoryFactory()
        mock_gopay_service().process_transfer_loyalty_point_to_gopay.return_value = (
            'success', mock_gopay_transfer, mock_point_usage_history
        )
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/gopay_transfer', data=data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    def test_gopay_service_success_details(self, mock_check_balance, mock_create_payout,
                                           mock_gopay_client):
        mock_check_balance.return_value = True
        data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test',
                 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]
        mock_gopay_client.return_value.create_payouts.return_value = data
        mock_response_payout = {
            'payouts': [{
                'reference_no': 'test123',
                'status': 'queued'
            }]
        }
        mock_create_payout.return_value = mock_response_payout
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/gopay_transfer', data=data)
        self.assertEqual(response.status_code, 200)
        ctt = LoyaltyGopayTransferTransaction.objects.get(customer_id=self.customer.id)
        self.assertEqual(response.data['data'], {
            'id': ctt.id,
            'nominal_amount': 100_000,
            'transfer_status': 'queued',
            'transfer_amount': 98_000,
            'admin_fee': 2000,
            'point_amount': 100_000,
            "mobile_phone_number": '08987893218',
        })
        ph = PointHistory.objects.get(
            customer_id=self.loyalty_point.customer_id, change_reason='Gopay transfer'
        )
        puh = PointUsageHistory.objects.get(point_history_id=ph.id)
        expect_point_usage_history = {
            "reference_type": "gopay_transfer",
            "reference_id": puh.reference_id,
            "point_amount": 100_000,
            "exchange_amount": 100_000,
            "exchange_amount_unit": "rupiah",
            "extra_data": {"julo_fee": 1000, "partner_fee": 1000}
        }
        self.assertEqual(expect_point_usage_history, {
            "reference_type": puh.reference_type,
            "reference_id": puh.reference_id,
            "point_amount": puh.point_amount,
            "exchange_amount": puh.exchange_amount,
            "exchange_amount_unit": puh.exchange_amount_unit,
            "extra_data": puh.extra_data
        })
        self.loyalty_point.refresh_from_db()
        self.assertEqual(self.loyalty_point.total_point, 10_000)
        transfer = LoyaltyGopayTransferTransaction.objects.get(customer_id=self.customer.id)
        expect_transfer_gopay = {
            "bank_name": "gopay",
            "transfer_amount": 98_000,  # julo_fee 1_000, partner_fee = 1_000
            "redeem_amount": 100_000,
            "partner_transfer": 'gopay',
            "customer_id": self.customer.id,
            "transfer_status": "queued",
            "phone_number": "08987893218",
        }
        self.assertEqual(expect_transfer_gopay, {
            "bank_name": transfer.bank_name,
            "transfer_amount": transfer.transfer_amount,
            "redeem_amount": transfer.redeem_amount,
            "partner_transfer": transfer.partner_transfer,
            "customer_id": self.customer.id,
            "transfer_status": transfer.transfer_status,
            "phone_number": "08987893218",
        })

    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    def test_gopay_service_failed_with_minimum_withdrawal(self, mock_check_balance,
                                                          mock_gopay_client):
        mock_check_balance.return_value = True
        mock_gopay_client.return_value.approve_payouts.side_effect = GopayClientException('test')
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 1_000
        }
        response = self.client.post('/api/loyalty/v1/gopay_transfer', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'],
            ['Jumlah nominal tidak valid']
        )

    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    def test_gopay_service_failed_case_1(self, mock_check_balance, mock_create_payout,
                                  mock_gopay_client):
        mock_check_balance.return_value = True
        mock_gopay_client.return_value.approve_payouts.side_effect = GopayClientException('test')
        mock_response_payout = {
            'payouts': [{
                'reference_no': 'test123',
                'status': 'queued'
            }]
        }
        mock_create_payout.return_value = mock_response_payout
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/gopay_transfer', data=data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.approve_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    def test_gopay_service_failed_case_2(self, mock_check_balance, mock_approve_payout,
                                         mock_create_payout, mock_gopay_client):
        mock_check_balance.return_value = True
        mock_response_payout = {
            'payouts': [{
                'reference_no': 'test123',
                'status': 'queued'
            }]
        }
        mock_create_payout.return_value = mock_response_payout
        mock_approve_payout.return_value = {
            "status": "ok"
        }
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/gopay_transfer', data=data)
        self.assertEqual(response.status_code, 200)

        callbacks_url = '/api/integration/v1/callbacks/gopay-cashback'
        data = {
            'reference_no': 'test123',
            'status': 'failed',
            'error_code': '012',
            'error_message': 'exception 1'
        }
        self.client.post(callbacks_url, data, format='json')
        ph = PointHistory.objects.get(
            customer_id=self.loyalty_point.customer_id, change_reason='Gopay transfer'
        )
        puh = PointUsageHistory.objects.get(point_history_id=ph.id)
        expect_point_usage_history = {
            "reference_type": "gopay_transfer",
            "reference_id": puh.reference_id,
            "point_amount": 100_000,
            "exchange_amount": 100_000,
            "exchange_amount_unit": "rupiah",
        }
        self.assertEqual(expect_point_usage_history, {
            "reference_type": puh.reference_type,
            "reference_id": puh.reference_id,
            "point_amount": puh.point_amount,
            "exchange_amount": puh.exchange_amount,
            "exchange_amount_unit": puh.exchange_amount_unit,
        })
        self.loyalty_point.refresh_from_db()
        self.assertEqual(self.loyalty_point.total_point, 110_000)
        transfer = LoyaltyGopayTransferTransaction.objects.get(customer_id=self.customer.id)
        expect_transfer_gopay = {
            "bank_name": "gopay",
            "transfer_amount": 98_000,
            "redeem_amount": 100_000,
            "partner_transfer": 'gopay',
            "customer_id": self.customer.id,
            "transfer_status": 'failed',
            "phone_number": "08987893218",
        }
        self.assertEqual(expect_transfer_gopay, {
            "bank_name": transfer.bank_name,
            "transfer_amount": transfer.transfer_amount,
            "redeem_amount": transfer.redeem_amount,
            "partner_transfer": transfer.partner_transfer,
            "customer_id": self.customer.id,
            "transfer_status": transfer.transfer_status,
            "phone_number": "08987893218",
        })


class TestCheckGopayTransfer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.loyalty_point = LoyaltyPointFactory(customer=self.customer, total_point=10_000)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.point_redeem_fs = PointRedeemFSFactory(parameters={
            PointRedeemReferenceTypeConst.REPAYMENT: {
                'is_active': True
            },
            PointRedeemReferenceTypeConst.GOPAY_TRANSFER: {
                'is_active': True,
                'partner_fee': 1_000,
                'julo_fee': 1_000,
                'minimum_withdrawal': 10_000
            }
        })
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loyalty_gopay_transfer = LoyaltyGopayTransferTransactionFactory(
            customer_id=self.customer.id
        )
        PointUsageHistoryFactory(
            reference_type=PointRedeemReferenceTypeConst.GOPAY_TRANSFER,
            reference_id=self.loyalty_gopay_transfer.id,
        )

    def test_check_gopay_transfer(self):
        data = {
            'gopay_transfer_id': self.loyalty_gopay_transfer.id,
        }
        response = self.client.post('/api/loyalty/v1/check_gopay_transfer', data=data)
        self.assertEqual(response.status_code, 200)
        expected_response = {
            'id': self.loyalty_gopay_transfer.id,
            'transfer_status': 'queued',
            'nominal_amount': 10000,
            'transfer_amount': 9000,
            'admin_fee': 1000,
            'point_amount': 10000,
            'mobile_phone_number': '081220275465',
        }
        self.assertEqual(response.data['data'], expected_response)


class TestFloatingActionButtonAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.application_status_id = 190
        self.application.save()
        self.url = '/api/loyalty/v1/android_floating_action_button'
        self.feature_setting = FeatureSettingFactory(
            feature_name="floating_action_button",
            is_active=True,
            parameters={
                'icon_image_url': 'https://julofiles-staging.oss-ap-southeast-5.aliyuncs.com/static_test/graduation/banners/downgrade-illustration.png',
                'prefix': 'julo',
                'deeplink': 'loyalty_homepage',
            }
        )

    def test_invalid_request(self):
        response = self.client.post(self.url)
        self.assertEquals(response.status_code, HTTP_405_METHOD_NOT_ALLOWED)

    def test_application_invalid(self):
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)

        self.application.delete()
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_404_NOT_FOUND)

    def test_feature_setting_off(self):
        self.feature_setting.update_safely(is_active=False)
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.data['data'], {'is_show_fab': False}
        )

    def test_get_floating_action_button_info(self):
        expected_result = {
            'icon_image_url': 'https://julofiles-staging.oss-ap-southeast-5.aliyuncs.com/static_test/graduation/banners/downgrade-illustration.png',
            'prefix': 'julo',
            'deeplink': 'loyalty_homepage',
        }
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.data['data'], expected_result
        )
