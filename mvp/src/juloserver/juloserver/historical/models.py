from __future__ import unicode_literals
from builtins import object

from django.db import models

from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager, TimeStampedModel
from django.contrib.postgres.fields import ArrayField


class BioSensorHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class BioSensorHistory(TimeStampedModel):
    id = models.AutoField(db_column='biometric_sensor_history_id', primary_key=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    accelerometer_data = ArrayField(models.FloatField(), default=list)
    gyroscope_data = ArrayField(models.FloatField(), default=list)
    gravity_data = ArrayField(models.FloatField(), default=list)
    rotation_data = ArrayField(models.FloatField(), default=list)
    orientation = models.CharField(max_length=200, blank=True, null=True)
    al_activity = models.CharField(max_length=500, blank=True, null=True)
    al_fragment = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField()
    error = ArrayField(models.TextField(), blank=True, null=True)
    android_id = models.TextField(blank=True, null=True)
    gcm_reg_id = models.TextField(blank=True, null=True)

    objects = BioSensorHistoryManager()

    class Meta(object):
        db_table = '"hst"."biometric_sensor_history"'
