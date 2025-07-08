from __future__ import unicode_literals

from builtins import object
from django.db import models
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.google_analytics.constants import GaDownloadBatchStatus


class GaBatchDownloadTask(TimeStampedModel):
    id = models.AutoField(db_column='ga_batch_download_task_id', primary_key=True)
    status = models.TextField(default=GaDownloadBatchStatus.PENDING)
    error_message = models.TextField(blank=True, null=True)
    data_count = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'ga_batch_download_task'
