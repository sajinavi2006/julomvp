from builtins import object

from django.contrib.postgres.fields import JSONField
from django.db import models

from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class PusdafilUploadManager(GetInstanceMixin, JuloModelManager):
    pass


class PusdafilUpload(TimeStampedModel):
    STATUS_INITIATED = "initiated"
    STATUS_QUERIED = "queried"
    STATUS_QUERIED_ERROR = "queried_error"
    STATUS_ERROR = "sent_error"
    STATUS_SUCCESS = "sent_success"
    STATUS_FAILED = "api_failed"

    STATUSES = (
        (STATUS_INITIATED, STATUS_INITIATED),
        (STATUS_QUERIED, STATUS_QUERIED),
        (STATUS_QUERIED_ERROR, STATUS_QUERIED_ERROR),
        (STATUS_ERROR, STATUS_ERROR),
        (STATUS_SUCCESS, STATUS_SUCCESS),
        (STATUS_FAILED, STATUS_FAILED),
    )

    id = models.AutoField(db_column='pusdafil_upload_id', primary_key=True)
    name = models.CharField(max_length=50, default='-', db_index=True)
    identifier = models.BigIntegerField(default=0, db_index=True)
    retry_count = models.IntegerField(default=0, db_index=True)
    status = models.CharField(
        "Status", choices=STATUSES, max_length=20, default=STATUS_INITIATED, db_index=True
    )
    error = JSONField(blank=True, null=True)
    upload_data = JSONField(blank=True, null=True)

    objects = PusdafilUploadManager()

    class Meta(object):
        db_table = 'pusdafil_upload'
