from django.db import models

from juloserver.julocore.data.models import TimeStampedModel


class CustomerClaim(TimeStampedModel):
    id = models.AutoField(db_column='customer_claim_id', primary_key=True)
    origin = models.CharField(db_column="origin", max_length=50, blank=True, null=True)
    customer = models.ForeignKey(
        db_column='customer_id',
        on_delete=models.DO_NOTHING,
        to='julo.Customer',
        related_name='customer',
    )
    claimed_customer = models.ForeignKey(
        db_column='claimed_customer_id',
        on_delete=models.DO_NOTHING,
        to='julo.Customer',
        related_name='claimed_customer',
    )

    class Meta:
        db_table = 'customer_claim'
