from __future__ import unicode_literals

from builtins import object
from django.db import models

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin

# Create your models here.


class NexmoUserManager(GetInstanceMixin, JuloModelManager):
    pass


class NexmoUser(TimeStampedModel):
    id = models.AutoField(db_column='nexmo_user_id', primary_key=True)

    nexmo_id = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    is_oncall = models.BooleanField(default=False)
    last_seen = models.DateTimeField(blank=True, null=True)

    objects = NexmoUserManager()

    class Meta(object):
        db_table = 'nexmo_user'


class NexmoConversationManager(GetInstanceMixin, JuloModelManager):
    pass


class NexmoConversation(TimeStampedModel):
    id = models.AutoField(db_column='nexmo_conversation_id', primary_key=True)

    uuid = models.CharField(max_length=100, blank=True, null=True)
    to_number = models.CharField(max_length=15)
    result = models.CharField(max_length=15)
    is_executed = models.BooleanField(default=False)
    agent = models.ForeignKey(
        'NexmoUser', on_delete=models.DO_NOTHING, db_column='nexmo_user_id', blank=True, null=True)

    objects = NexmoUserManager()

    class Meta(object):
        db_table = 'nexmo_conversation'
