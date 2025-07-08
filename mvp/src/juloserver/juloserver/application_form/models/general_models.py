from django.db import models
from django.core.validators import (
    RegexValidator,
)

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from django_bulk_update.manager import BulkUpdateManager

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class ApplicationPhoneRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationPhoneRecord(TimeStampedModel):

    id = BigAutoField(db_column="application_phone_record_id", primary_key=True)
    application_id = models.BigIntegerField(
        null=True,
        blank=True,
    )
    customer_id = models.BigIntegerField(
        null=False,
        blank=False,
        unique=True,
    )
    mobile_phone_number = models.CharField(
        max_length=50,
        blank=False,
        null=False,
    )

    class Meta(object):
        db_table = "application_phone_record"
        managed = False


class CompanyLookupManager(GetInstanceMixin, JuloModelManager):
    pass


class CompanyLookup(TimeStampedModel):

    id = BigAutoField(primary_key=True, db_column='company_lookup_id')
    company_name = models.TextField(blank=True, null=True, default=None, db_index=True)
    company_address = models.TextField(blank=True, null=True, default=None)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    company_phone_number = models.CharField(max_length=50, blank=True, null=True)

    objects = BulkUpdateManager()

    class Meta(object):
        db_table = "company_lookup"
        managed = False
