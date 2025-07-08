import datetime
import operator
import pytz

from factory import Iterator
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
)
from rest_framework.test import APIClient, APITestCase
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    LoanFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
    SepulsaProductFactory,
)
from juloserver.loyalty.constants import (
    FeatureNameConst,
    PointRedeemReferenceTypeConst,
    MissionCategoryConst,
    MissionRewardTypeConst,
    MissionCriteriaTypeConst,
    MissionCriteriaValueConst,
    MissionMessageConst,
    MissionProgressStatusConst,
    MissionTargetTypeConst,
    MissionStatusMessageConst,
    MissionFilterCategoryConst,
    APIVersionConst,
)
from juloserver.loyalty.tests.factories import (
    LoyaltyPointFactory,
    PointEarningFactory,
    MissionRewardFactory,
    MissionConfigFactory,
    MissionCriteriaFactory,
    MissionConfigCriteriaFactory,
    MissionProgressFactory,
    MissionTargetFactory,
    MissionConfigTargetFactory,
    MissionTargetProgressFactory,
)
from juloserver.julo.tests.factories import (
    LoanFactory,
    ProductLineFactory,
)
from juloserver.julo.constants import (
    ProductLineCodes,
    ApplicationStatusCodes,
)
from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory


class TestPointInformationAPIV2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.status = StatusLookupFactory(status_code=220)
        self.loyalty_point = LoyaltyPointFactory(customer_id=self.customer.id, total_point=100_000)
        self.base_url = '/api/loyalty/v2/point-information'
        self.point_earnings = PointEarningFactory.create_batch(
            4,
            customer_id=self.customer.id,
            loyalty_point=self.loyalty_point,
            points=Iterator([5000, 20000, 30000, 50000]),
            is_expired=Iterator([True, False, False, False]),
            expiry_date=Iterator([
                datetime.date(2024, 12, 31),
                datetime.date(2025, 1, 5),
                datetime.date(2025, 1, 31),
                datetime.date(2025, 3, 2)
            ])
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=100_000,
            loan_status=self.status,
            loan_duration=1,
        )
        self.last_payment = self.loan.payment_set.last()
        self.account_payment = AccountPaymentFactory(account=self.account, due_amount=40_000)
        self.last_payment.update_safely(account_payment=self.account_payment)

        self.setup_point_redeem_fs()
        self.setup_expire_reminder_fs()
        self.setup_conversion_rate_fs()
        self.sepulsa_product = SepulsaProductFactory(
            type=SepulsaProductType.E_WALLET_OPEN_PAYMENT, category=SepulsaProductCategory.DANA,
            is_active=True,
            customer_price_regular=500, partner_price=500
        )

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
                    "julo_fee": 0
                },
                PointRedeemReferenceTypeConst.DANA_TRANSFER: {
                    "name": "DANA",
                    "is_active": True,
                    "tag_info": {
                        "title": "Baru",
                        "is_active": True
                    },
                    "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/333.png",
                    "is_default": False,
                    "minimum_withdrawal": 10_000,
                    "julo_fee": 0
                }
            }
        )

    def setup_expire_reminder_fs(self):
        self.point_reminder_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.POINT_EXPIRE_REMINDER_CONFIGURATION,
            is_active=True,
            parameters={
                "point_expiry_info": "{} Poin kamu akan kedaluwersa pada {}",
                "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah "
                                    "saldo cashback kamu",
                "reminder_days": 30
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


    @patch('django.utils.timezone.now')
    def test_point_information_not_show_expiry_info(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 10, 31, 0, 0, 0)

        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, HTTP_200_OK)
        self.assertTrue('point_expiry_info' not in res.json()['data'])


    @patch('django.utils.timezone.now')
    def test_point_information_show_expiry_info(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 12, 31, 0, 0, 0)

        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, HTTP_200_OK)

        expected_expiry_info = "20.000 Poin kamu akan kedaluwersa pada 05 Jan 2025"
        self.assertEqual(res.json()['data']['point_expiry_info'], expected_expiry_info)


    @patch('django.utils.timezone.now')
    def test_point_information_redemption_methods(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 12, 31, 0, 0, 0)

        expected_repayment_method = {
            "redemption_method": "repayment",
            "name": "Potong Tagihan",
            "tag_info": {
                "title": "",
                "is_active": False
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/111.png",
            "is_default": True,
            "is_valid": True,
            "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah saldo cashback kamu",
            "total_point_deduction": 40_000,
            "minimum_withdrawal": 20_000
        }
        expected_gopay_transfer = {
            "redemption_method": "gopay_transfer",
            "name": "GoPay",
            "tag_info": {
                "title": "Baru",
                "is_active": True
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/222.png",
            "is_default": False,
            "is_valid": True,
            "admin_fee": 110,
            "detail_fees": {"julo_fee": 0, "partner_fee": 110},
            "minimum_nominal_amount": 20_000,
            "maximum_nominal_amount": 130_000
        }
        expected_dana_transfer = {
            "redemption_method": "dana_transfer",
            "name": "DANA",
            "tag_info": {
                "title": "Baru",
                "is_active": True
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/333.png",
            "is_default": False,
            "is_valid": True,
            "admin_fee": 500,
            "detail_fees": {"julo_fee": 0, "partner_fee": 500},
            "minimum_nominal_amount": 10_000,
            "maximum_nominal_amount": 130_000
        }
        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, HTTP_200_OK)

        response = res.json()['data']
        self.assertEqual(len(response['redemption_methods']), 3)
        self.assertEqual(response['redemption_methods'][0], expected_repayment_method)
        self.assertTrue(expected_gopay_transfer in response['redemption_methods'])
        self.assertTrue(expected_dana_transfer in response['redemption_methods'])


    @patch('django.utils.timezone.now')
    def test_point_information_redemption_method_turn_off(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 12, 31, 0, 0, 0)
        self.point_redeem_fs.parameters['dana_transfer']['is_active'] = False
        self.point_redeem_fs.save()

        expected_repayment_method = {
            "redemption_method": "repayment",
            "name": "Potong Tagihan",
            "tag_info": {
                "title": "",
                "is_active": False
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/111.png",
            "is_default": True,
            "is_valid": True,
            "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah saldo cashback kamu",
            "total_point_deduction": 40_000,
            "minimum_withdrawal": 20_000
        }
        expected_gopay_transfer = {
            "redemption_method": "gopay_transfer",
            "name": "GoPay",
            "tag_info": {
                "title": "Baru",
                "is_active": True
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/222.png",
            "is_default": False,
            "is_valid": True,
            "admin_fee": 110,
            "detail_fees": {"julo_fee": 0, "partner_fee": 110},
            "minimum_nominal_amount": 20_000,
            "maximum_nominal_amount": 130_000
        }

        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, HTTP_200_OK)

        response = res.json()['data']
        self.assertEqual(len(response['redemption_methods']), 2)
        self.assertEqual(
            response['redemption_methods'],
            [expected_repayment_method, expected_gopay_transfer]
        )

    @patch('django.utils.timezone.now')
    def test_point_information_redemption_methods_change_default(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 12, 31, 0, 0, 0)

        self.point_redeem_fs.parameters['repayment']['is_default'] = False
        self.point_redeem_fs.parameters['gopay_transfer']['is_default'] = True
        self.point_redeem_fs.save()

        expected_repayment_method = {
            "redemption_method": "repayment",
            "name": "Potong Tagihan",
            "tag_info": {
                "title": "",
                "is_active": False
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/111.png",
            "is_default": False,
            "is_valid": True,
            "point_usage_info": "Potongan berlaku di taginan cicilan terakhir sesuai jumlah saldo cashback kamu",
            "total_point_deduction": 40_000,
            "minimum_withdrawal": 20_000
        }
        expected_gopay_transfer = {
            "redemption_method": "gopay_transfer",
            "name": "GoPay",
            "tag_info": {
                "title": "Baru",
                "is_active": True
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/222.png",
            "is_default": True,
            "is_valid": True,
            "admin_fee": 110,
            "detail_fees": {"julo_fee": 0, "partner_fee": 110},
            "minimum_nominal_amount": 20_000,
            "maximum_nominal_amount": 130_000
        }
        expected_dana_transfer = {
            "redemption_method": "dana_transfer",
            "name": "DANA",
            "tag_info": {
                "title": "Baru",
                "is_active": True
            },
            "icon": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/loyalty/333.png",
            "is_default": False,
            "is_valid": True,
            "admin_fee": 500,
            "detail_fees": {"julo_fee": 0, "partner_fee": 500},
            "minimum_nominal_amount": 10_000,
            "maximum_nominal_amount": 130_000
        }
        res = self.client.get(self.base_url)
        self.assertEqual(res.status_code, HTTP_200_OK)

        response = res.json()['data']
        self.assertEqual(len(response['redemption_methods']), 3)
        self.assertEqual(
            response['redemption_methods'],
            [expected_gopay_transfer, expected_repayment_method, expected_dana_transfer]
        )


class TestLoyaltyPointMissionDetailAPIV2(APITestCase):
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
            max_repeat=5,
            repetition_delay_days=2,
            display_order=2,
            description="<p>Description<p>",
            tnc="<p>TnC<p>",
            api_version=APIVersionConst.V2
        )
        MissionConfigCriteriaFactory(
            config=self.mission,
            criteria=self.mission_criteria
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.url = '/api/loyalty/v2/mission/details/'

    def set_up_targets(self):
        self.target_1 = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=5
        )
        self.target_2 = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=2_000_000
        )

    def set_up_config_targets(self):
        MissionConfigTargetFactory(
            config=self.mission,
            target=self.target_1
        )
        MissionConfigTargetFactory(
            config=self.mission,
            target=self.target_2
        )

    def test_get_mission_detail_not_found(self):
        url = self.url + str(0)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['errors'][0], MissionMessageConst.ERROR_MISSION_CONFIG_NOT_FOUND
        )

    @patch('django.utils.timezone.now')
    def test_get_mission_detail_without_progress(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 26, 0, 0, 0)
        self.set_up_targets()
        self.set_up_config_targets()

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
                "display_order": 2,
                "expiry_date": None,
                "completion_date": None,
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
                "detailed_progress": [
                    {
                        "target_type": MissionTargetTypeConst.RECURRING,
                        "current": 0,
                        "remaining": 5,
                        "target": 5,
                        "message": MissionStatusMessageConst.STARTED_MSG
                    },
                    {
                        "target_type": MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
                        "current": 0,
                        "remaining": 2_000_000,
                        "target": 2_000_000,
                        "message": MissionStatusMessageConst.STARTED_MSG
                    }
                ]
            },
        )

    @patch('django.utils.timezone.now')
    def test_get_mission_detail_with_target_in_progress(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 26, 0, 0, 0)
        self.set_up_targets()
        self.set_up_config_targets()
        loan = LoanFactory(customer=self.customer, loan_amount=500_000)

        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=1,
            recurring_number=0,  # No longer used
            reference_data={"loan_ids": [loan.id]},
            status=MissionProgressStatusConst.IN_PROGRESS,
            completion_date=datetime.date(2024, 3, 25)
        )
        # Progress of target 1
        MissionTargetProgressFactory(
            mission_target=self.target_1,
            mission_progress=mission_progress,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=1
        )
        # Progress of target 2
        MissionTargetProgressFactory(
            mission_target=self.target_2,
            mission_progress=mission_progress,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=500_000
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
                "display_order": 2,
                "expiry_date": None,
                "completion_date": "2024-03-24T17:00:00Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": mission_progress.id,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
                "detailed_progress": [
                    {
                        "target_type": MissionTargetTypeConst.RECURRING,
                        "current": 1,
                        "remaining": 4,
                        "target": 5,
                        "message": MissionStatusMessageConst.IN_PROGRESS_MSG[
                            MissionTargetTypeConst.RECURRING
                        ]
                    },
                    {
                        "target_type": MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
                        "current": 500_000,
                        "remaining": 1_500_000,
                        "target": 2_000_000,
                        "message": MissionStatusMessageConst.IN_PROGRESS_MSG[
                            MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT
                        ]
                    }
                ]
            },
        )

    @patch('django.utils.timezone.now')
    def test_get_mission_detail_with_target_completed(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 26, 0, 0, 0)
        self.set_up_targets()
        self.set_up_config_targets()
        loans = LoanFactory.create_batch(
            6,
            customer=self.customer,
            loan_amount=Iterator(
                [100_000, 200_000, 200_000, 400_000, 500_000, 1_000_000]
            )
        )
        mission_progress = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission,
            repeat_number=1,
            recurring_number=0,  # No longer used
            reference_data={"loan_ids": list(map(operator.attrgetter("pk"), loans))},
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.date(2024, 3, 25)
        )
        # Progress of target 1
        MissionTargetProgressFactory(
            mission_target=self.target_1,
            mission_progress=mission_progress,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=6
        )
        # Progress of target 2
        MissionTargetProgressFactory(
            mission_target=self.target_2,
            mission_progress=mission_progress,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=2_400_000
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
                "display_order": 2,
                "expiry_date": None,
                "completion_date": "2024-03-24T17:00:00Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.COMPLETED,
                "mission_progress_id": mission_progress.id,
                "description": "<p>Description<p>",
                "tnc": "<p>TnC<p>",
                "detailed_progress": [
                    {
                        "target_type": MissionTargetTypeConst.RECURRING,
                        "current": 6,
                        "remaining": 0,
                        "target": 5,
                        "message": MissionStatusMessageConst.COMPLETED_MSG
                    },
                    {
                        "target_type": MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
                        "current": 2_400_000,
                        "remaining": 0,
                        "target": 2_000_000,
                        "message": MissionStatusMessageConst.COMPLETED_MSG
                    }
                ]
            },
        )


class TestLoyaltyPointInfoAPIV2(APITestCase):
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
        self.url = '/api/loyalty/v2/info'
        self.query_params = {'categories': 'Semua'}

        LoyaltyPointFactory(customer_id=self.customer.id, total_point=24000)
        self.loans = LoanFactory.create_batch(
            3,
            customer=self.customer, loan_amount=Iterator([200_000, 500_000, 800_000])
        )
        self.set_up_feature_settings()
        self.set_up_mission_rewards()
        self.set_up_mission_configs()
        self.set_up_mission_criteria()
        self.set_up_mission_config_and_criteria()
        self.set_up_mission_target()
        self.set_up_mission_config_and_target()
        self.set_up_mission_progresses()
        self.set_up_mission_target_and_progress()

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
        self.mission_3 = MissionConfigFactory(
            title="Mission 3",
            icon=None,
            reward=self.transaction_reward,
            target_recurring=3,
            max_repeat=5,
            repetition_delay_days=3,
            category=MissionCategoryConst.TRANSACTION,
            display_order=5,
            is_active=True,
            expiry_date=datetime.datetime(2024, 3, 30, 12, 23, 34, tzinfo=pytz.UTC),
            api_version=APIVersionConst.V2,
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
            type=MissionCriteriaTypeConst.MINIMUM_LOAN_AMOUNT,
            value={
                MissionCriteriaValueConst.MINIMUM_LOAN_AMOUNT: 500_000
            }
        )

    def set_up_mission_config_and_criteria(self):
        MissionConfigCriteriaFactory(
            config=self.mission_2,
            criteria=self.mission_criteria_1
        )
        MissionConfigCriteriaFactory(
            config=self.mission_3,
            criteria=self.mission_criteria_1
        )
        MissionConfigCriteriaFactory(
            config=self.mission_3,
            criteria=self.mission_criteria_2
        )

    def set_up_mission_target(self):
        self.target_1 = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=5
        )
        self.target_2 = MissionTargetFactory(
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=3_000_000
        )

    def set_up_mission_config_and_target(self):
        MissionConfigTargetFactory(
            config=self.mission_2,
            target=self.target_1
        )
        MissionConfigTargetFactory(
            config=self.mission_3,
            target=self.target_1
        )
        MissionConfigTargetFactory(
            config=self.mission_3,
            target=self.target_2
        )

    def set_up_mission_progresses(self):
        self.mission_progress_1 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_2,
            repeat_number=1,
            recurring_number=0,
            status=MissionProgressStatusConst.IN_PROGRESS,
            reference_data={"loan_ids": [self.loans[0].id]}
        )
        self.mission_progress_2 = MissionProgressFactory(
            customer_id=self.customer.id,
            mission_config=self.mission_3,
            repeat_number=2,
            recurring_number=0,
            status=MissionProgressStatusConst.IN_PROGRESS,
            reference_data={"loan_ids": list(map(operator.attrgetter("pk"), self.loans))}
        )

    def set_up_mission_target_and_progress(self):
        self.target_progress_1 = MissionTargetProgressFactory(
            mission_target=self.target_1,
            mission_progress=self.mission_progress_1,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=1
        )
        self.target_progress_2 = MissionTargetProgressFactory(
            mission_target=self.target_1,
            mission_progress=self.mission_progress_2,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.RECURRING,
            value=3
        )
        self.target_progress_3 = MissionTargetProgressFactory(
            mission_target=self.target_2,
            mission_progress=self.mission_progress_2,
            category=MissionCategoryConst.TRANSACTION,
            type=MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT,
            value=1_500_000
        )

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

    @patch('django.utils.timezone.now')
    def test_get_mission_list(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": None,
                "overall_progress": 55.0,
                'message': MissionStatusMessageConst.IN_PROGRESS_MSG["default"],
            },
            {
                "mission_id": self.mission_2.id,
                "title": "Mission 2",
                "icon": None,
                "reward_points": 2000,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_1.id,
                "completion_date": None,
                "overall_progress": 20.0,
                "target_type": MissionTargetTypeConst.RECURRING,
                "current": 1,
                "remaining": 4,
                "target": 5,
                "message": MissionStatusMessageConst.IN_PROGRESS_MSG[
                    MissionTargetTypeConst.RECURRING
                ],
            },
            {
                "mission_id": self.mission_1.id,
                "title": "Mission 1",
                "icon": None,
                "reward_points": 3000,
                "display_order": 2,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
                "overall_progress": 0,
                'message': MissionStatusMessageConst.STARTED_MSG,
            }
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_list_no_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)
        loans = LoanFactory.create_batch(
            6,
            customer=self.customer, loan_amount=Iterator(
                [500_000, 500_000, 500_000, 500_000, 500_000, 1_000_000]
            )
        )
        self.mission_progress_2.update_safely(
            reference_data={"loan_ids": list(map(operator.attrgetter("pk"), loans))},
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.datetime(2024, 3, 25, 14, 45, 50, tzinfo=pytz.UTC)
        )
        self.target_progress_2.update_safely(value=6)
        self.target_progress_3.update_safely(value=3_500_000)


        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.COMPLETED,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": '2024-03-25T14:45:50Z',
                "overall_progress": 100.0,
                'message': MissionStatusMessageConst.COMPLETED_MSG,
            },
            {
                "mission_id": self.mission_2.id,
                "title": "Mission 2",
                "icon": None,
                "reward_points": 2000,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_1.id,
                "completion_date": None,
                "overall_progress": 20.0,
                "target_type": MissionTargetTypeConst.RECURRING,
                "current": 1,
                "remaining": 4,
                "target": 5,
                "message": MissionStatusMessageConst.IN_PROGRESS_MSG[
                    MissionTargetTypeConst.RECURRING
                ],
            },
            {
                "mission_id": self.mission_1.id,
                "title": "Mission 1",
                "icon": None,
                "reward_points": 3000,
                "display_order": 2,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
                "overall_progress": 0,
                'message': MissionStatusMessageConst.STARTED_MSG,
            }
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_list_resetable(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        loans = LoanFactory.create_batch(
            6,
            customer=self.customer, loan_amount=Iterator(
                [500_000, 500_000, 500_000, 500_000, 500_000, 1_000_000]
            )
        )
        self.mission_progress_2.update_safely(
            reference_data={"loan_ids": list(map(operator.attrgetter("pk"), loans))},
            status=MissionProgressStatusConst.CLAIMED,
            completion_date=datetime.datetime(2024, 3, 25, 14, 45, 50, tzinfo=pytz.UTC)
        )
        self.target_progress_2.update_safely(value=6)
        self.target_progress_3.update_safely(value=3_500_000)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_2.id,
                "title": "Mission 2",
                "icon": None,
                "reward_points": 2000,
                "display_order": 4,
                "expiry_date": "2024-03-30T15:20:55Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_1.id,
                "completion_date": None,
                "overall_progress": 20.0,
                "target_type": MissionTargetTypeConst.RECURRING,
                "current": 1,
                "remaining": 4,
                "target": 5,
                "message": MissionStatusMessageConst.IN_PROGRESS_MSG[
                    MissionTargetTypeConst.RECURRING
                ],
            },
            {
                "mission_id": self.mission_1.id,
                "title": "Mission 1",
                "icon": None,
                "reward_points": 3000,
                "display_order": 2,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.GENERAL,
                "transaction_method_id": None,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
                "overall_progress": 0,
                'message': MissionStatusMessageConst.STARTED_MSG,
            },
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.STARTED,
                "mission_progress_id": None,
                "completion_date": None,
                "overall_progress": 0,
                'message': MissionStatusMessageConst.STARTED_MSG,
            },
        ]

        self.assertEqual(resp_data['missions'], expected_mission_data)

    @patch('django.utils.timezone.now')
    def test_get_mission_list_with_completed_category(self, mock_now):
        # No resetable
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)
        loans = LoanFactory.create_batch(
            6,
            customer=self.customer, loan_amount=Iterator(
                [500_000, 500_000, 500_000, 500_000, 500_000, 1_000_000]
            )
        )
        self.mission_progress_2.update_safely(
            reference_data={"loan_ids": list(map(operator.attrgetter("pk"), loans))},
            status=MissionProgressStatusConst.COMPLETED,
            completion_date=datetime.datetime(2024, 3, 25, 14, 45, 50, tzinfo=pytz.UTC)
        )
        self.target_progress_2.update_safely(value=6)
        self.target_progress_3.update_safely(value=3_500_000)

        expected_mission_data = [
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.COMPLETED,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": '2024-03-25T14:45:50Z',
                "overall_progress": 100.0,
                'message': MissionStatusMessageConst.COMPLETED_MSG,
            }
        ]

        query_params = {'category': 'Selesai'}
        response = self.client.get(self.url, data=query_params)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(resp_data['missions'], expected_mission_data)

        # Resetable
        mock_now.return_value = datetime.datetime(2024, 3, 29, 0, 0, 0)
        query_params = {'category': 'Selesai'}
        response = self.client.get(self.url, data=query_params)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertEqual(resp_data['missions'], [])

    @patch('django.utils.timezone.now')
    def test_get_mission_list_with_expired_category(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)

        user2 = AuthUserFactory()
        CustomerFactory(user=user2)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user2.auth_expiry_token.key)

        query_params = {'category': 'Kedaluwarsa'}
        response = self.client.get(self.url, data=query_params)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'], [])

    @patch('django.utils.timezone.now')
    def test_get_mission_list_with_deleted_mission(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 3, 27, 0, 0, 0)
        self.mission_1.update_safely(is_deleted=True)
        self.mission_2.update_safely(is_deleted=True)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, HTTP_200_OK)

        resp_data = response.json()['data']
        self.assertIsNotNone(resp_data['missions'])

        expected_mission_data = [
            {
                "mission_id": self.mission_3.id,
                "title": "Mission 3",
                "icon": None,
                "reward_points": 2000,
                "display_order": 5,
                "expiry_date": "2024-03-30T12:23:34Z",
                "category": MissionCategoryConst.TRANSACTION,
                "transaction_method_id": 2,
                "status": MissionProgressStatusConst.IN_PROGRESS,
                "mission_progress_id": self.mission_progress_2.id,
                "completion_date": None,
                "overall_progress": 55.0,
                'message': MissionStatusMessageConst.IN_PROGRESS_MSG["default"],
            }
        ]
        self.assertEqual(resp_data['missions'], expected_mission_data)
