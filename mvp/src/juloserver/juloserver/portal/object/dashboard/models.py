from __future__ import absolute_import, unicode_literals

import logging
from builtins import object

from django.contrib.auth.models import User
from django.db import models

from juloserver.julocore.data.models import TimeStampedModel

logger = logging.getLogger(__name__)


class CRMSetting(models.Model):
    user = models.OneToOneField(User)
    role_select = models.CharField(max_length=60, null=True, blank=True)
    role_default = models.CharField(max_length=60, null=True, blank=True)

    cdate = models.DateTimeField(auto_now_add=True, editable=False)
    udate = models.DateTimeField(auto_now=True, null=True, blank=True, editable=False)

    def __str__(self):
        return self.user.username

    class Meta(object):
        verbose_name_plural = u'CRM Settings'

    def save(self, *args, **kwargs):
        # Calling Parent save() function
        super(CRMSetting, self).save(*args, **kwargs)


class CRMBucketColor(TimeStampedModel):
    id = models.AutoField(db_column='crm_bucket_color_id', primary_key=True)
    color = models.CharField(max_length=7, blank=True, null=True)
    content_color = models.CharField(max_length=7, blank=True, null=True)
    color_name = models.CharField(max_length=20, blank=True, null=True)
    display_text = models.CharField(max_length=3, blank=True, null=True)

    class Meta(object):
        ordering = ('display_text',)
        db_table = 'crm_bucket_color'

    def __str__(self):
        return '%s' % (self.color_name,)


class CRMBucketStatusColor(TimeStampedModel):
    id = models.AutoField(db_column='crm_bucket_status_color_id', primary_key=True)
    status_code = models.CharField(max_length=20, blank=True, null=True, unique=True)
    color = models.ForeignKey(CRMBucketColor, blank=True, null=True)

    class Meta(object):
        ordering = ('status_code',)
        db_table = 'crm_bucket_status_color'

    def __str__(self):
        return '%s: %s' % (self.status_code, self.color)
