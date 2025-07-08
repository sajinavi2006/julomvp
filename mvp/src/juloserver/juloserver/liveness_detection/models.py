from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models

from juloserver.julo.models import (
    Application,
    Customer,
    GetInstanceMixin,
    Image,
    TimeStampedModel,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import JuloModelManager


class ActiveLivenessVendorResult(TimeStampedModel):
    id = models.AutoField(db_column='active_liveness_vendor_result_id', primary_key=True)
    vendor_name = models.CharField(max_length=255)
    raw_response = JSONField()
    raw_response_type = models.CharField(max_length=255)

    class Meta(object):
        db_table = 'active_liveness_vendor_result'


class PassiveLivenessVendorResult(TimeStampedModel):
    id = models.AutoField(db_column='passive_liveness_vendor_result_id', primary_key=True)
    vendor_name = models.CharField(max_length=255)
    raw_response = JSONField()
    raw_response_type = models.CharField(max_length=255)

    class Meta(object):
        db_table = 'passive_liveness_vendor_result'


class ActiveLivenessDetectionManager(GetInstanceMixin, JuloModelManager):
    pass


class ActiveLivenessDetection(TimeStampedModel):
    id = models.AutoField(db_column='active_liveness_detection_id', primary_key=True)
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    status = models.CharField(max_length=100)
    image_ids = ArrayField(models.BigIntegerField(), default=list)
    images = JSONField(default=list)
    score = models.FloatField(null=True, blank=True)
    sequence = ArrayField(models.CharField(max_length=50), default=list)
    liveness_vendor_result = models.OneToOneField(
        ActiveLivenessVendorResult,
        models.DO_NOTHING,
        db_column='active_liveness_vendor_result_id',
        null=True,
        blank=True,
    )
    latency = models.BigIntegerField(null=True, blank=True)
    configs = JSONField(default=dict)
    error_code = models.CharField(max_length=255, null=True, blank=True)
    attempt = models.SmallIntegerField(default=0)
    api_version = models.CharField(max_length=50, null=True, blank=True)
    detect_type = models.CharField(max_length=100, null=True, blank=True)
    service_type = models.CharField(max_length=100, null=True, blank=True)
    client_type = models.CharField(max_length=100, null=True, blank=True)
    internal_customer_id = models.TextField(null=True, blank=True)
    video_injection = models.TextField(null=True, blank=True)

    objects = ActiveLivenessDetectionManager()

    class Meta(object):
        db_table = 'active_liveness_detection'


class PassiveLivenessDetectionManager(GetInstanceMixin, JuloModelManager):
    pass


class PassiveLivenessDetection(TimeStampedModel):
    id = models.AutoField(db_column='passive_liveness_detection_id', primary_key=True)
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    application = models.OneToOneField(Application, models.DO_NOTHING, db_column='application_id')
    status = models.CharField(max_length=100)
    image = models.OneToOneField(
        Image, models.DO_NOTHING, db_column='image_id', blank=True, null=True
    )
    score = models.FloatField(null=True, blank=True)
    liveness_vendor_result = models.OneToOneField(
        PassiveLivenessVendorResult,
        models.DO_NOTHING,
        db_column='passive_liveness_vendor_result_id',
        null=True,
        blank=True,
    )
    latency = models.BigIntegerField(null=True, blank=True)
    configs = JSONField(default=dict)
    error_code = models.CharField(max_length=255, null=True, blank=True)
    api_version = models.CharField(max_length=50, null=True, blank=True)
    attempt = models.IntegerField(null=True, blank=True)
    service_type = models.CharField(max_length=100, null=True, blank=True)
    client_type = models.CharField(max_length=100, null=True, blank=True)

    objects = PassiveLivenessDetectionManager()

    class Meta(object):
        db_table = 'passive_liveness_detection'
