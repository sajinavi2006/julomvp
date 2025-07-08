from builtins import object

from django.db import models
from django.contrib.postgres.fields import JSONField

from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julo.models import GetInstanceMixin, TimeStampedModel
from juloserver.julocore.data.models import JuloModelManager


class LendeastModelManager(GetInstanceMixin, JuloModelManager):
    pass


class LendeastModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = LendeastModelManager()


class LendeastReportMonthly(LendeastModel):
    id = models.AutoField(db_column='lendeast_report_monthly_id', primary_key=True)
    statement_month = models.TextField()
    outstanding_amount = models.BigIntegerField()
    total_loan = models.IntegerField()
    page_size = models.IntegerField()
    page_done = models.IntegerField(default=0)
    summary = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'lendeast_report_monthly'


class LendeastDataMonthly(LendeastModel):
    id = models.AutoField(db_column='lendeast_data_monthly_id', primary_key=True)
    data_date = models.DateField()
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    loan_status = models.TextField()
    loan_data = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'lendeast_data_monthly'
