from django.db import models

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import (
    TimeStampedModel,
)


class JuloAppReport(TimeStampedModel):
    """
    This model will be created on DB "logging_db" by Infra Team
    And don't need to create file migration for this model.
    """

    id = BigAutoField(db_column="julo_app_report_id", primary_key=True)
    android_id = models.TextField(blank=True, null=True)
    device_name = models.TextField(blank=True, null=True)
    endpoint = models.TextField(blank=True, null=True)
    request = models.TextField(blank=True, null=True)
    response = models.TextField(blank=True, null=True)
    application_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = "julo_app_report"
