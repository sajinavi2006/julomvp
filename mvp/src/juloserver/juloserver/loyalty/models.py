from ckeditor.fields import RichTextField

from django.db import models
from django.db.models import Q
from django.utils import timezone

from juloserver.julo.models import Image, GetInstanceMixin
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import TimeStampedModel, JuloModelManager
from django.contrib.postgres.fields import JSONField

from juloserver.loyalty.constants import (
    MissionCategoryConst,
    MissionCriteriaTypeConst,
    MissionRewardTypeConst,
    MissionProgressStatusConst,
    PointHistoryChangeReasonConst,
    PointRedeemReferenceTypeConst,
    PointExchangeUnitConst,
    MissionTargetTypeConst,
    APIVersionConst,
)
from juloserver.promo.models import JsonValueMixin
from juloserver.loyalty.constants import ReferenceTypeConst
from juloserver.easy_income_upload.models import EasyIncomeCustomer


class LoyaltyPoint(TimeStampedModel):
    id = models.AutoField(db_column='loyalty_point_id', primary_key=True)
    customer_id = models.BigIntegerField()
    total_point = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'loyalty_point'
        managed = False


class PointHistory(TimeStampedModel):
    id = BigAutoField(db_column='point_history_id', primary_key=True)
    old_point = models.BigIntegerField(default=0)
    new_point = models.BigIntegerField(default=0)
    change_reason = models.CharField(choices=PointHistoryChangeReasonConst.CHOICES, max_length=255)
    customer_id = models.BigIntegerField()

    class Meta(object):
        db_table = 'point_history'
        managed = False


class PointEarning(TimeStampedModel):
    id = models.AutoField(db_column='point_earning_id', primary_key=True)
    points = models.BigIntegerField(default=0)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    customer_id = models.BigIntegerField()
    loyalty_point = models.ForeignKey(
        LoyaltyPoint,
        models.DO_NOTHING,
        db_column='loyalty_point_id'
    )
    point_history_id = models.BigIntegerField(null=True, blank=True)
    is_expired = models.BooleanField(default=False)
    reference_id = models.BigIntegerField(null=True, blank=True)
    reference_type = models.CharField(
        choices=ReferenceTypeConst.REFERENCE_TYPE_CHOICES,
        blank=True, null=True, max_length=255
    )

    class Meta(object):
        db_table = 'point_earning'
        managed = False

    @property
    def get_reference_obj(self):
        if self.reference_type == ReferenceTypeConst.EASY_INCOME_UPLOAD:
            return EasyIncomeCustomer.objects.filter(pk=self.reference_id).last()
        return None


class MissionConfigManager(GetInstanceMixin, JuloModelManager):
    def get_valid_mission_config_queryset(self):
        now = timezone.localtime(timezone.now())

        return self.filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=now),
            is_deleted=False,
        )

    def get_visible_mission_config_queryset(self):
        return self.get_valid_mission_config_queryset().filter(is_active=True)


class MissionConfig(TimeStampedModel):
    id = models.AutoField(db_column='mission_config_id', primary_key=True)
    category = models.CharField(
        choices=MissionCategoryConst.CHOICES,
        default=MissionCategoryConst.GENERAL,
        max_length=255
    )
    title = models.CharField(max_length=255, null=True, blank=True)
    target_recurring = models.PositiveIntegerField(default=1, null=True, blank=True)
    max_repeat = models.PositiveIntegerField(default=1, null=True, blank=True)
    repetition_delay_days = models.PositiveIntegerField(default=1, null=True, blank=True)
    display_order = models.IntegerField()
    expiry_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    description = RichTextField(null=True, blank=True)
    tnc = RichTextField(null=True, blank=True)
    api_version = models.IntegerField(choices=APIVersionConst.CHOICES)

    criteria = models.ManyToManyField(
        'MissionCriteria',
        through='MissionConfigCriteria',
        related_name='mission_configs',
    )
    targets = models.ManyToManyField(
        'MissionTarget',
        through='MissionConfigTarget',
        related_name='mission_configs',
    )
    reward = models.ForeignKey(
        'MissionReward',
        models.DO_NOTHING,
        db_column='mission_reward_id',
        null=True,
        blank=True
    )

    objects = MissionConfigManager()

    class Meta(object):
        db_table = 'mission_config'
        managed = False

    @property
    def icon(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="loyalty_icon"
        ).last()
        if image:
            return image.static_image_url

        return None


class MissionCriteria(TimeStampedModel, JsonValueMixin):
    id = models.AutoField(db_column='mission_criteria_id', primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(
        choices=MissionCategoryConst.CHOICES,
        default=MissionCategoryConst.GENERAL,
        max_length=255
    )
    type = models.CharField(choices=MissionCriteriaTypeConst.CHOICES, max_length=255)
    value = JSONField()

    class Meta(object):
        db_table = 'mission_criteria'
        managed = False


class MissionReward(TimeStampedModel, JsonValueMixin):
    id = models.AutoField(db_column='mission_reward_id', primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(
        choices=MissionCategoryConst.CHOICES,
        default=MissionCategoryConst.GENERAL,
        max_length=255
    )
    type = models.CharField(choices=MissionRewardTypeConst.CHOICES, max_length=255)
    value = JSONField()

    class Meta(object):
        db_table = 'mission_reward'
        managed = False


class MissionConfigCriteria(TimeStampedModel):
    id = models.AutoField(db_column='mission_config_criteria_id', primary_key=True)
    config = models.ForeignKey(
        'MissionConfig',
        models.DO_NOTHING,
        db_column='mission_config_id'
    )
    criteria = models.ForeignKey(
        'MissionCriteria',
        models.DO_NOTHING,
        db_column='mission_criteria_id'
    )

    class Meta(object):
        db_table = 'mission_config_criteria'
        managed = False


class MissionTarget(TimeStampedModel, JsonValueMixin):
    id = models.AutoField(db_column='mission_target_id', primary_key=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(
        choices=MissionCategoryConst.CHOICES,
        default=MissionCategoryConst.GENERAL,
        max_length=255
    )
    type = models.CharField(choices=MissionTargetTypeConst.CHOICES, max_length=255)
    value = models.BigIntegerField()

    class Meta(object):
        db_table = 'mission_target'
        managed = False


class MissionConfigTarget(TimeStampedModel):
    id = models.AutoField(db_column='mission_config_target_id', primary_key=True)
    config = models.ForeignKey(
        'MissionConfig',
        models.DO_NOTHING,
        db_column='mission_config_id'
    )
    target = models.ForeignKey(
        'MissionTarget',
        models.DO_NOTHING,
        db_column='mission_target_id'
    )

    class Meta(object):
        db_table = 'mission_config_target'
        managed = False


class MissionProgress(TimeStampedModel):
    id = models.AutoField(db_column='mission_progress_id', primary_key=True)
    status = models.CharField(choices=MissionProgressStatusConst.CHOICES, max_length=255)
    recurring_number = models.PositiveIntegerField(default=0)
    repeat_number = models.PositiveIntegerField(default=1)
    reference_data = JSONField(default=dict)
    completion_date = models.DateTimeField(null=True, blank=True)
    is_latest = models.BooleanField(default=False)
    customer_id = models.BigIntegerField()
    mission_config = models.ForeignKey(
        MissionConfig,
        models.DO_NOTHING,
        db_column='mission_config_id'
    )
    point_earning = models.ForeignKey(
        PointEarning,
        models.DO_NOTHING,
        db_column='point_earning_id',
        null=True,
        blank=True
    )

    class Meta(object):
        db_table = 'mission_progress'
        unique_together = ('customer_id', 'mission_config', 'repeat_number')
        managed = False


class MissionProgressHistory(TimeStampedModel):
    id = models.AutoField(db_column='mission_progress_history_id', primary_key=True)
    mission_progress = models.ForeignKey(
        MissionProgress,
        models.DO_NOTHING,
        db_column='mission_progress_id',
        null=True,
        blank=True
    )
    field = models.CharField(max_length=255)
    old_value = models.CharField(max_length=255, null=True, blank=True)
    new_value = models.CharField(max_length=255, null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'mission_progress_history'
        managed = False


class MissionTargetProgress(TimeStampedModel, JsonValueMixin):
    id = models.AutoField(db_column='mission_target_progress_id', primary_key=True)
    category = models.CharField(
        choices=MissionCategoryConst.CHOICES,
        default=MissionCategoryConst.GENERAL,
        max_length=255
    )
    type = models.CharField(choices=MissionTargetTypeConst.CHOICES, max_length=255)
    value = models.BigIntegerField()
    mission_target = models.ForeignKey(
        MissionTarget,
        models.DO_NOTHING,
        db_column='mission_target_id'
    )
    mission_progress = models.ForeignKey(
        MissionProgress,
        models.DO_NOTHING,
        db_column='mission_progress_id'
    )

    class Meta(object):
        db_table = 'mission_target_progress'
        managed = False


class DailyCheckin(TimeStampedModel):
    id = models.AutoField(db_column='daily_checkin_id', primary_key=True)
    daily_reward = JSONField(default=dict)
    reward = models.IntegerField(default=0)
    max_days_reach_bonus = models.IntegerField(default=0)
    is_latest = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'daily_checkin'
        managed = False


class DailyCheckinProgress(TimeStampedModel):
    id = models.AutoField(db_column='daily_checkin_progress_id', primary_key=True)
    days_count = models.IntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    latest_update = models.DateField(null=True, blank=True)
    total_claimed = models.IntegerField(default=0)
    is_latest = models.BooleanField(default=False)
    daily_checkin = models.ForeignKey(
        DailyCheckin,
        models.DO_NOTHING,
        db_column='daily_checkin_id'
    )
    customer_id = models.BigIntegerField()

    class Meta(object):
        db_table = 'daily_checkin_progress'
        managed = False


class PointUsageHistory(TimeStampedModel):
    id = models.AutoField(db_column='point_usage_history_id', primary_key=True)
    reference_type = models.CharField(
        choices=PointRedeemReferenceTypeConst.CHOICES, max_length=255
    )
    reference_id = models.BigIntegerField(blank=True, null=True)
    point_amount = models.IntegerField()
    exchange_amount = models.IntegerField()
    exchange_amount_unit = models.CharField(
        choices=PointExchangeUnitConst.CHOICES, max_length=255
    )
    point_history_id = models.BigIntegerField(null=True, blank=True)
    extra_data = JSONField(default=dict)

    class Meta(object):
        db_table = 'point_usage_history'
        managed = False


class LoyaltyGopayTransferTransactionManager(GetInstanceMixin, JuloModelManager):
    pass


class LoyaltyGopayTransferTransaction(TimeStampedModel):
    id = models.AutoField(db_column='loyalty_gopay_transfer_transaction_id', primary_key=True)
    customer_id = models.BigIntegerField()
    bank_name = models.CharField(max_length=100)
    bank_code = models.CharField(max_length=50, null=True)
    bank_number = models.CharField(max_length=50)
    name_in_bank = models.CharField(max_length=250)
    validation_status = models.CharField(max_length=50, null=True)
    validation_id = models.CharField(max_length=250, null=True)
    validated_name = models.CharField(max_length=250, null=True)
    transfer_status = models.CharField(max_length=50, null=True)
    transfer_id = models.CharField(max_length=250, null=True)
    failure_code = models.CharField(max_length=250, null=True)
    failure_message = models.TextField(null=True)
    transfer_amount = models.BigIntegerField()
    redeem_amount = models.BigIntegerField()
    external_id = models.CharField(max_length=250, blank=True, null=True)
    retry_times = models.IntegerField(default=0, blank=True, null=True)
    partner_transfer = models.CharField(max_length=20, blank=True, null=True)
    fund_transfer_ts = models.DateTimeField(null=True)

    objects = LoyaltyGopayTransferTransactionManager()

    class Meta(object):
        db_table = 'loyalty_gopay_transfer_transaction'
        managed = False
