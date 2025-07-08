from __future__ import unicode_literals

from builtins import object
from django.db import models

from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager, TimeStampedModel
from juloserver.julo.models import Image


class OtherLoanManager(GetInstanceMixin, JuloModelManager):
    pass


class OtherLoan(TimeStampedModel):
    id = models.AutoField(db_column='other_loan_id', primary_key=True)
    name = models.CharField(max_length=100)
    url = models.TextField()
    short_description = models.TextField()
    is_active = models.BooleanField(default=False)

    objects = OtherLoanManager()

    class Meta(object):
        db_table = 'other_loan'

    def __str__(self):
        return self.name

    @property
    def image_url(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="other_loan_image").order_by('-id').first()
        if image:
            return image.image_url

        return None


class AndroidCardManager(GetInstanceMixin, JuloModelManager):
    pass


class AndroidCard(TimeStampedModel):
    ACTION_TYPE = (
        ('DEEP_LINK', 'DEEP_LINK'),
        ('WEB_VIEW', 'WEB_VIEW'))

    id = models.AutoField(db_column='android_card_id', primary_key=True)
    title = models.CharField(max_length=100)
    message = models.TextField(blank=True, null=True)
    button_text = models.CharField(max_length=100)
    action_url = models.TextField(blank=True, null=True)
    action_type = models.CharField(max_length=100, choices=ACTION_TYPE)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    is_permanent = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    display_order = models.IntegerField(blank=True, null=True)

    objects = AndroidCardManager()

    class Meta(object):
        db_table = 'android_card'

    def __str__(self):
        return self.title
