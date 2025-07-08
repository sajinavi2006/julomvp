from builtins import object

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import TimeStampedModel


class IncomeCheckLog(TimeStampedModel):
    id = BigAutoField(db_column='income_check_log_id', primary_key=True)
    is_found = models.BooleanField()
    status = models.TextField()
    message = models.TextField(null=True, blank=True)
    salary_amount = models.BigIntegerField(null=True)
    currency = models.TextField()
    service_provider = models.TextField()
    application_id = models.BigIntegerField(blank=False, null=False)

    class Meta(object):
        db_table = 'income_check_log'
        managed = False


class IncomeCheckAPILog(TimeStampedModel):
    id = BigAutoField(db_column='income_check_api_log_id', primary_key=True)
    income_check_log = models.ForeignKey(
        'IncomeCheckLog', models.DO_NOTHING, db_column='income_check_log_id', blank=True, null=True
    )
    api_type = models.TextField()
    http_status_code = models.IntegerField(
        validators=[MinValueValidator(100), MaxValueValidator(525)]
    )
    query_params = models.TextField()
    request = models.TextField(null=True, blank=True)
    response = models.TextField()
    status = models.TextField()
    latency = models.BigIntegerField(null=True)

    class Meta(object):
        db_table = 'income_check_api_log'
        managed = False
