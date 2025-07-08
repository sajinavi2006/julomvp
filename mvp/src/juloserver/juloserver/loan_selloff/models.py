from __future__ import unicode_literals

from builtins import object
from django.db import models
from juloserver.julocore.data.models import TimeStampedModel, GetInstanceMixin, JuloModelManager
from juloserver.loan_selloff.constants import SelloffBatchConst


class LoanSelloffModelManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanSelloffModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = LoanSelloffModelManager()


class LoanSelloffBatch(LoanSelloffModel):
    PARAMETER_CHOICES = (
        (SelloffBatchConst.PRINCIPAL, SelloffBatchConst.PRINCIPAL),
        (SelloffBatchConst.PRINCIPAL_AND_INTEREST, SelloffBatchConst.PRINCIPAL_AND_INTEREST),
        (SelloffBatchConst.TOTAL_OUTSTANDING, SelloffBatchConst.TOTAL_OUTSTANDING)
    )
    id = models.AutoField(db_column='loan_selloff_batch_id', primary_key=True)
    parameter = models.CharField(max_length=100, db_index=True, choices=PARAMETER_CHOICES)
    pct_of_parameter = models.FloatField()
    vendor = models.CharField(max_length=200, db_index=True)
    csv_file = models.TextField(null=True, blank=True)
    execution_schedule = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_selloff_batch'


class LoanSelloff(LoanSelloffModel):
    id = models.AutoField(db_column='loan_selloff_id', primary_key=True)
    loan = models.OneToOneField('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    loan_selloff_batch = models.ForeignKey(
        'LoanSelloffBatch', models.DO_NOTHING, db_column='loan_selloff_batch_id')
    principal_at_selloff = models.BigIntegerField(blank=True, default=0)
    interest_at_selloff = models.BigIntegerField(blank=True, default=0)
    late_fee_at_selloff = models.BigIntegerField(blank=True, default=0)
    loan_selloff_proceeds_value = models.BigIntegerField(blank=True, default=0)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    product = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_selloff'
