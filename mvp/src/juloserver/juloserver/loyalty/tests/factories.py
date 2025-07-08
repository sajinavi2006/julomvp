from factory import SubFactory, LazyAttribute
from factory.django import DjangoModelFactory

from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.loyalty.constants import (
    MissionRewardTypeConst,
    MissionCategoryConst,
    MissionProgressStatusConst,
    FeatureNameConst,
    PointRedeemReferenceTypeConst,
    PointExchangeUnitConst,
    MissionTargetTypeConst,
)
from juloserver.loyalty.models import (
    DailyCheckin,
    DailyCheckinProgress,
    LoyaltyPoint,
    PointHistory,
    PointEarning,
    MissionConfig,
    MissionProgress,
    MissionCriteria,
    MissionConfigCriteria,
    MissionTarget,
    MissionConfigTarget,
    MissionReward,
    LoyaltyGopayTransferTransaction,
    PointUsageHistory,
    MissionTargetProgress,
    APIVersionConst,
)
from juloserver.julo.models import FeatureSetting


class LoyaltyPointFactory(DjangoModelFactory):
    class Meta:
        model = LoyaltyPoint
        exclude = ['customer']

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)
    total_point = 0


class PointHistoryFactory(DjangoModelFactory):
    class Meta:
        model = PointHistory
        exclude = ['customer']

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)
    old_point = 1000
    new_point = 2000


class PointEarningFactory(DjangoModelFactory):
    class Meta:
        model = PointEarning
        exclude = ['customer']

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)
    loyalty_point = SubFactory(LoyaltyPointFactory)
    points = 10000


class DailyCheckinFactory(DjangoModelFactory):
    class Meta:
        model = DailyCheckin

    daily_reward = {}


class DailyCheckinProgressFactory(DjangoModelFactory):
    class Meta:
        model = DailyCheckinProgress
        exclude = ['customer']

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)


class MissionRewardFactory(DjangoModelFactory):
    class Meta:
        model = MissionReward

    type = MissionRewardTypeConst.FIXED
    value = {"fixed": 1000}


class MissionConfigFactory(DjangoModelFactory):
    class Meta:
        model = MissionConfig
        database = DbConnectionAlias.UTILIZATION_DB

    title = ''
    reward = SubFactory(MissionRewardFactory)
    category = MissionCategoryConst.GENERAL
    target_recurring = 1
    max_repeat = 1
    is_active = True
    is_deleted = False
    repetition_delay_days = 1
    display_order = 1
    expiry_date = None
    api_version = APIVersionConst.V1


class MissionTargetFactory(DjangoModelFactory):
    class Meta:
        model = MissionTarget
        database = DbConnectionAlias.UTILIZATION_DB

    name = 'default mission target'
    category = MissionCategoryConst.GENERAL
    type = MissionTargetTypeConst.RECURRING
    value = 3


class MissionConfigTargetFactory(DjangoModelFactory):
    class Meta:
        model = MissionConfigTarget
        database = DbConnectionAlias.UTILIZATION_DB

    config = SubFactory(MissionConfigFactory)
    target = SubFactory(MissionTarget)


class MissionProgressFactory(DjangoModelFactory):
    class Meta:
        model = MissionProgress
        exclude = ['customer']
        database = DbConnectionAlias.UTILIZATION_DB

    customer = SubFactory(CustomerFactory)
    customer_id = LazyAttribute(lambda o: o.customer.id)
    mission_config = SubFactory(MissionConfigFactory)
    point_earning = SubFactory(PointEarningFactory)
    is_latest = True
    status = MissionProgressStatusConst.IN_PROGRESS
    recurring_number = 0
    repeat_number = 1
    reference_data = {}
    completion_date = None


class MissionTargetProgressFactory(DjangoModelFactory):
    class Meta:
        model = MissionTargetProgress
        database = DbConnectionAlias.UTILIZATION_DB

    category = MissionCategoryConst.GENERAL
    type = MissionTargetTypeConst.RECURRING
    value = 2
    mission_target = SubFactory(MissionTarget)
    mission_progress = SubFactory(MissionProgress)


class MissionCriteriaFactory(DjangoModelFactory):
    class Meta:
        model = MissionCriteria


class MissionConfigCriteriaFactory(DjangoModelFactory):
    class Meta:
        model = MissionConfigCriteria


class PointRedeemFSFactory(DjangoModelFactory):
    class Meta:
        model = FeatureSetting

    feature_name = FeatureNameConst.POINT_REDEEM
    is_active = True


class LoyaltyGopayTransferTransactionFactory(DjangoModelFactory):
    class Meta:
        model = LoyaltyGopayTransferTransaction

    bank_name = 'gopay'
    bank_code = 'gopay'
    transfer_status = 'queued'
    bank_number = '081220275465'
    name_in_bank = 'NguyenVanE'
    transfer_amount = 9_000
    redeem_amount = 10_000


class PointUsageHistoryFactory(DjangoModelFactory):
    class Meta:
        model = PointUsageHistory

    reference_type = PointRedeemReferenceTypeConst.GOPAY_TRANSFER
    reference_id = 1
    point_amount = 10_000
    exchange_amount = 10_000
    exchange_amount_unit = PointExchangeUnitConst.RUPIAH
