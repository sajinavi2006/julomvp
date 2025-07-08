from django.db import models
from juloserver.julo.models import TimeStampedModel
from enum import Enum


class FraudBlock(TimeStampedModel):
    class Source(Enum):
        LOAN_FRAUD_BLOCK = 1

    id = models.AutoField(primary_key=True, db_column="fraud_block_id")
    source = models.IntegerField(blank=False, null=False)
    customer_id = models.IntegerField(blank=False, null=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "fraud_block"
        managed = False
