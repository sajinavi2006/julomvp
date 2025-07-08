from ckeditor.fields import RichTextField

from django.db import models

from juloserver.julocore.data.models import TimeStampedModel


class Faq(TimeStampedModel):
    id = models.AutoField(db_column='faq_id', primary_key=True)
    feature_name = models.CharField(max_length=120)
    question = models.CharField(max_length=120)
    answer = RichTextField(null=True, blank=True)
    order_priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'faq'
