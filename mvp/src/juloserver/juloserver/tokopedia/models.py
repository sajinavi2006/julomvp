from django.db import models
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
)


class TokoScoreResult(TimeStampedModel):
    id = BigAutoField(db_column='toko_score_result_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False)
    response_code = models.TextField(null=True, blank=True)
    error_code = models.TextField(null=True, blank=True)
    latency = models.TextField(null=True, blank=True)
    request_message_id = models.TextField(null=True, blank=True)
    request_score_id = models.IntegerField(null=True, blank=True)
    score = models.TextField(null=True, blank=True)
    response_time = models.DateTimeField(null=True, blank=True)
    is_match = models.NullBooleanField()
    is_active = models.NullBooleanField()
    request_status = models.CharField(max_length=50, blank=True, null=True)
    score_type = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'toko_score_result'
        managed = False
