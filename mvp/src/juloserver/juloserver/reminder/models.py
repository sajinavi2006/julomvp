from __future__ import unicode_literals

from builtins import object
from django.db import models
from django.conf import settings

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin


class ReminderModelManager(GetInstanceMixin, JuloModelManager):
    pass


class ReminderModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = ReminderModelManager()


class CallRecordUrl(ReminderModel):
    id = models.AutoField(db_column='call_record_url_id', primary_key=True)
    conversation_uuid = models.CharField(max_length=100)
    recording_uuid = models.CharField(max_length=100)
    rec_start_time = models.DateTimeField(blank=True, null=True)
    rec_end_time = models.DateTimeField(blank=True, null=True)
    recording_url = models.CharField(max_length=200)
    is_upload_to_oss = models.BooleanField(default=False)
    oss_file_url = models.CharField(max_length=300, blank=True, null=True)

    class Meta(object):
        db_table = 'call_record_url'
