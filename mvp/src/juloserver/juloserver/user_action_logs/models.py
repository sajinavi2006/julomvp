from django.db import models
from django.db.models.signals import post_save

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import TimeStampedModel
from django.contrib.postgres.fields import JSONField


class CustomManager(models.Manager):
    def bulk_create(self, objs, **kwargs):
        s = super(CustomManager, self).bulk_create(objs, **kwargs)
        for i in objs:
            # sending signals post_save for all objects
            post_save.send(i.__class__, instance=i, created=True)

        return s


class MobileUserActionLog(TimeStampedModel):
    objects = CustomManager()

    id = BigAutoField(db_column='mobile_user_action_log_id', primary_key=True)
    log_ts = models.DateTimeField()
    customer_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    app_version = models.TextField()
    android_id = models.TextField(null=True, blank=True)
    gcm_reg_id = models.TextField(null=True, blank=True)
    device_brand = models.TextField()
    device_model = models.TextField(null=True, blank=True)
    android_api_level = models.IntegerField()
    session_id = models.TextField()
    module = models.TextField()
    activity = models.TextField()
    activity_counter = models.IntegerField()
    fragment = models.TextField(null=True, blank=True)
    view = models.TextField(null=True, blank=True)
    event = models.TextField()
    extra_params = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = 'mobile_user_action_log'


class WebUserActionLog(TimeStampedModel):
    objects = CustomManager()

    id = BigAutoField(db_column='web_user_action_log_id', primary_key=True)
    date = models.DateTimeField()
    module = models.CharField(max_length=255)
    element = models.CharField(max_length=255)
    application_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    event = models.CharField(max_length=255)
    user_identifier_id = models.CharField(max_length=255, null=True, blank=True)
    product = models.CharField(max_length=50, null=True, blank=True)
    attributes = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = "web_user_action_log"
        managed = False
