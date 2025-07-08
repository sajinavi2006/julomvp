# Create your models here.
from django.db import models
from django.contrib.postgres.fields import JSONField
from django.db.models import Sum

from juloserver.early_limit_release.constants import EarlyReleaseCheckingType, ReleaseTrackingType
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel, CustomQuerySet,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigAutoField


class EarlyReleaseExperiment(TimeStampedModel):
    id = models.AutoField(db_column='experiment_id', primary_key=True)
    experiment_name = models.CharField(max_length=255)
    option = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    criteria = JSONField(default=dict)
    is_active = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)

    class Meta:
        db_table = 'early_release_experiment'
        managed = False


class ReleaseTrackingQuerySet(CustomQuerySet):
    def total_limit_release(self, loan_id, tracking_type=None):
        qs = self.filter(loan_id=loan_id)

        if tracking_type:
            qs = qs.filter(type=tracking_type)
        qs = qs.aggregate(total_limit_release_amount=Sum('limit_release_amount'))
        return qs['total_limit_release_amount'] or 0


class ReleaseTrackingManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return ReleaseTrackingQuerySet(self.model)


class ReleaseTracking(TimeStampedModel):
    # not only use for early release
    id = BigAutoField(db_column='tracking_id', primary_key=True)
    type = models.CharField(
        max_length=255,
        default=ReleaseTrackingType.EARLY_RELEASE,
        choices=ReleaseTrackingType.CHOICES
    )
    limit_release_amount = models.BigIntegerField()
    payment_id = models.BigIntegerField(null=True)
    loan_id = models.BigIntegerField(null=True)
    account_id = models.BigIntegerField()
    objects = ReleaseTrackingManager()

    class Meta:
        db_table = 'release_tracking'
        managed = False


class ReleaseTrackingHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class ReleaseTrackingHistory(TimeStampedModel):
    id = models.AutoField(
        db_column='release_tracking_history_id', primary_key=True
    )
    release_tracking = BigForeignKey(
        ReleaseTracking,
        on_delete=models.DO_NOTHING,
        db_column='release_tracking_id',
    )
    field_name = models.CharField(max_length=100)
    value_old = models.CharField(max_length=50, null=True, blank=True)
    value_new = models.CharField(max_length=50)

    objects = ReleaseTrackingHistoryManager()

    class Meta:
        db_table = 'release_tracking_history'
        managed = False


class EarlyReleaseCheckingManager(GetInstanceMixin, JuloModelManager):
    pass


class EarlyReleaseChecking(TimeStampedModel):
    id = BigAutoField(db_column='checking_id', primary_key=True)
    checking_type = models.CharField(max_length=255, choices=EarlyReleaseCheckingType.CHOICES)
    status = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True, null=True)
    payment_id = models.BigIntegerField()

    objects = EarlyReleaseCheckingManager()

    class Meta:
        db_table = 'early_release_checking'
        unique_together = (('payment_id', 'checking_type'),)
        managed = False


class EarlyReleaseCheckingHistory(TimeStampedModel):
    id = BigAutoField(db_column='checking_history_id', primary_key=True)
    checking = BigForeignKey(EarlyReleaseChecking, models.DO_NOTHING, db_column='checking_id')
    field_name = models.CharField(max_length=100)
    value_old = models.CharField(max_length=255, blank=True, null=True)
    value_new = models.CharField(max_length=255, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'early_release_checking_history'
        managed = False


class EarlyReleaseLoanMappingManager(GetInstanceMixin, JuloModelManager):
    pass


class EarlyReleaseLoanMapping(TimeStampedModel):
    id = models.AutoField(db_column='loan_mapping_id', primary_key=True)

    experiment = models.ForeignKey(
        EarlyReleaseExperiment, models.DO_NOTHING, db_column='experiment_id', blank=True, null=True
    )
    loan_id = models.BigIntegerField()
    payment_id = models.BigIntegerField(null=True, blank=True)
    is_auto = models.BooleanField(default=True)

    objects = EarlyReleaseLoanMappingManager()

    class Meta:
        db_table = 'early_release_loan_mapping'
        unique_together = ('loan_id', 'payment_id')
        managed = False


class EarlyReleaseCheckingV2Manager(GetInstanceMixin, JuloModelManager):
    pass


class EarlyReleaseCheckingV2(TimeStampedModel):
    id = BigAutoField(db_column='checking_id', primary_key=True)
    checking_result = JSONField(default=dict)
    payment_id = models.BigIntegerField()

    objects = EarlyReleaseCheckingV2Manager()

    class Meta:
        db_table = 'early_release_checking_v2'
        unique_together = ('payment_id',)
        managed = False


class EarlyReleaseCheckingHistoryV2(TimeStampedModel):
    id = BigAutoField(db_column='checking_history_id', primary_key=True)
    checking = BigForeignKey(EarlyReleaseCheckingV2, models.DO_NOTHING, db_column='checking_id')
    value_old = JSONField(default=dict)
    value_new = JSONField(default=dict)

    class Meta:
        db_table = 'early_release_checking_history_v2'
        managed = False


class OdinConsolidated(TimeStampedModel):
    id = BigAutoField(db_column='odin_consolidated_id', primary_key=True)
    partition_date = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    odin_consolidated = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = '"ana"."odin_consolidated"'
        managed = False
