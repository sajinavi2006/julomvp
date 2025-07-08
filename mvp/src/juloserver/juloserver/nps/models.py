from django.db import models
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
)
from juloserver.julo.models import TimeStampedModel
from django.conf import settings
from juloserver.julo.models import Customer
from juloserver.julocore.customized_psycopg2.models import BigForeignKey


class NPSSurvey(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="nps_survey_id")
    is_access_survey = models.NullBooleanField()
    comments = models.TextField(null=True, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(0, message='Harus lebih besar atau sama dengan 0'),
            MaxValueValidator(10, message='Harus lebih kecil atau sama dengan 10'),
        ],
    )
    phone = models.TextField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='user_id', db_constraint=False
    )
    customer = BigForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', db_constraint=False
    )
    email = models.EmailField(null=True, blank=True)
    android_id = models.TextField()

    class Meta:
        db_table = 'nps_survey'
