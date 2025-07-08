from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from django.db import models
from django.contrib.postgres.fields import JSONField

from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class IdfyVideoCallManager(GetInstanceMixin, JuloModelManager):
    pass


class IdfyVideoCall(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='idfy_video_call_id')
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    reference_id = models.CharField(db_column="reference_id", max_length=50, blank=True, null=True)
    profile_id = models.CharField(db_column="profile_id", max_length=100, blank=True, null=True)
    performed_video_call_by = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    status_tasks = models.CharField(max_length=50, blank=True, null=True)
    reviewer_action = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    profile_url = models.CharField(max_length=150, blank=True, null=True)
    reject_reason = models.CharField(max_length=150, blank=True, null=True)

    objects = IdfyVideoCallManager()

    class Meta(object):
        db_table = 'idfy_video_call'
        managed = False


class IdfyCallBackLogManager(PIIVaultModelManager):
    pass


class IdfyCallBackLog(PIIVaultModel):
    id = models.AutoField(primary_key=True, db_column='idfy_callback_log_id')
    application_id = models.IntegerField(null=True, blank=True)
    callback_log = JSONField(null=True, blank=True)
    profile_id = models.CharField(max_length=100, null=True, blank=True)
    reference_id = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, null=True)

    # PII attributes
    callback_log_tokenized = models.TextField(blank=True, null=True)
    PII_FIELDS = ['callback_log']
    PII_TYPE = 'kv'

    objects = IdfyCallBackLogManager()

    class Meta:
        managed = False
        db_table = "idfy_callback_log"
