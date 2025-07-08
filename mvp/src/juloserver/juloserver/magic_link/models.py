from __future__ import unicode_literals
from builtins import object

from django.db import models
from juloserver.julo.models import TimeStampedModel, GetInstanceMixin
from juloserver.julocore.data.models import JuloModelManager


# Create your models here.
class MagicLinkHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class MagicLinkHistory(TimeStampedModel):
    id = models.AutoField(db_column='magic_link_history_id', primary_key=True)
    email_history = models.ForeignKey(
        'julo.EmailHistory', models.DO_NOTHING, db_column='email_history_id',
        null=True, blank=True)
    sms_history = models.ForeignKey(
        'julo.SmsHistory', models.
            DO_NOTHING, db_column='sms_history_id',
        null=True, blank=True)
    token = models.TextField()
    status = models.TextField(default='unused')
    expiry_time = models.DateTimeField()

    objects = MagicLinkHistoryManager()

    class Meta(object):
        db_table = 'magic_link_history'