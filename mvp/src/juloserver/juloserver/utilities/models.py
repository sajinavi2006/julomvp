from __future__ import unicode_literals

from builtins import object
from django.db import models
from django.contrib.postgres.fields import ArrayField

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from juloserver.julo.models import StatusLookup


class InstanceMixinManager(GetInstanceMixin, JuloModelManager):
    pass


class DisbursementTrafficControl(TimeStampedModel):
    id = models.AutoField(db_column='disbursement_traffic_control_id', primary_key=True)
    key = models.CharField(max_length=100)
    condition = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    rule_type = models.CharField(max_length=150)
    success_value = models.CharField(max_length=150, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = InstanceMixinManager()

    class Meta(object):
        db_table = 'disbursement_traffic_control'

    def __str__(self):
        return "%s" % (self.id,)


class SlackUser(TimeStampedModel):
    id = models.AutoField(db_column='slack_ewa_user_id', primary_key=True)
    name = models.CharField(max_length=50, blank=False)
    slack_id = models.CharField(max_length=50, blank=False, unique=True)
    objects = InstanceMixinManager()

    class Meta(object):
        db_table = 'slack_ewa_user'

    def __str__(self):
        return "%s - %s" % (self.name, self.slack_id,)


class SlackEWABucket(TimeStampedModel):
    id = models.AutoField(db_column='slack_ewa_bucket_id', primary_key=True)
    status_code = models.OneToOneField(
                    StatusLookup, models.DO_NOTHING,
                    db_column='status_code_id', blank=False)
    display_text = models.CharField(max_length=100, null=True, blank=True)
    order_priority = models.IntegerField(default=0)
    disable = models.BooleanField(default=False)
    objects = InstanceMixinManager()

    class Meta(object):
        db_table = 'slack_ewa_bucket'
        ordering = ['order_priority']

    def __str__(self):
        return "Bucket Status: %s" % (self.status_code,)


class SlackEWATag(TimeStampedModel):
    id = models.AutoField(db_column='slack_ewa_tag_id', primary_key=True)
    condition = models.CharField(max_length=20)
    slack_user = models.ManyToManyField(SlackUser, blank=True)
    bucket = models.ForeignKey(
                    SlackEWABucket, db_column='bucket_id',
                    related_name='slack_ewa_tag', blank=True, null=True)
    objects = InstanceMixinManager()

    class Meta(object):
        db_table = 'slack_ewa_tag'

    def __str__(self):
        return "%s - %s" % (self.bucket, self.slack_user,)


class SlackEWAStatusEmotion(TimeStampedModel):
    id = models.AutoField(
        db_column='slack_ewa_status_emotion_id', primary_key=True)
    condition = models.CharField(max_length=20)
    emoji = models.CharField(max_length=50)
    bucket = models.ForeignKey(
                    SlackEWABucket, db_column='bucket_id',
                    related_name='slack_ewa_emoji', blank=True, null=True)
    objects = InstanceMixinManager()

    class Meta(object):
        db_table = 'slack_ewa_status_emotion'

    def __str__(self):
        return "%s - %s" % (self.bucket, self.emoji,)
