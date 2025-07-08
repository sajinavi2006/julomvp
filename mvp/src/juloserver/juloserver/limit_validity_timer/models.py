from django.db import models
from django.utils import timezone
from juloserver.julocore.data.models import TimeStampedModel
from django.contrib.postgres.fields import JSONField


class LimitValidityTimer(TimeStampedModel):
    id = models.AutoField(db_column='limit_validity_timer_id', primary_key=True)
    campaign_name = models.TextField(null=True, max_length=255)
    description = models.TextField(null=True, blank=True, max_length=1000)
    is_active = models.BooleanField(default=False)
    content = JSONField(default=dict)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(default=timezone.now)
    minimum_available_limit = models.PositiveIntegerField(default=0)
    upload_url = models.TextField(default="")
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod',
        models.DO_NOTHING,
        db_column='transaction_method_id',
        null=True
    )
    deeplink_url = models.CharField(null=True, max_length=2000)

    class Meta(object):
        db_table = 'limit_validity_timer'
