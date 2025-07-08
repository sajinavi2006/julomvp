from __future__ import unicode_literals

from builtins import object

from django.contrib.postgres.fields.jsonb import JSONField
from django.db import models

from juloserver.julo.models import Application, Customer

# Create your models here.
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class BpjsTaskManager(GetInstanceMixin, JuloModelManager):
    pass


class BpjsTask(TimeStampedModel):
    id = models.AutoField(db_column="bpjs_task_id", primary_key=True)
    data_source = models.TextField(blank=True, null=True)
    task_id = models.TextField(blank=True, null=True)
    status_code = models.IntegerField(blank=True, null=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column="customer_id")
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column="application_id")
    objects = BpjsTaskManager()

    class Meta(object):
        db_table = "bpjs_task"


class BpjsTaskEventManager(GetInstanceMixin, JuloModelManager):
    pass


class BpjsTaskEvent(TimeStampedModel):
    id = models.AutoField(db_column="bpjs_task_event_id", primary_key=True)
    bpjs_task = models.ForeignKey(BpjsTask, models.DO_NOTHING, db_column="bpjs_task_id")
    status_code = models.IntegerField(blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    objects = BpjsTaskEventManager()

    class Meta(object):
        db_table = "bpjs_task_event"


class SdBpjsProfile(TimeStampedModel):
    id = models.AutoField(db_column="sd_bpjs_profile_id", primary_key=True)
    birthday = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    kpj = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    real_name = models.TextField(null=True, blank=True)
    identity_number = models.TextField(null=True, blank=True)
    email = models.TextField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    application_id = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."sd_bpjs_profile"'
        managed = False


class SdBpjsCompany(TimeStampedModel):
    id = models.AutoField(db_column="sd_bpjs_company_id", primary_key=True)
    sd_bpjs_profile = models.ForeignKey(
        "SdBpjsProfile", models.DO_NOTHING, db_column="sd_bpjs_profile_id"
    )
    insurance_type = models.TextField(null=True, blank=True)
    employees_num = models.IntegerField(blank=True, null=True)
    retirement_date = models.DateField(blank=True, null=True)
    last_payment_date = models.DateField(blank=True, null=True)
    company = models.TextField(null=True, blank=True)
    current_salary = models.BigIntegerField(blank=True, null=True)
    insurance_status = models.TextField(null=True, blank=True)
    pension_guarantee_period = models.IntegerField(blank=True, null=True)
    balance = models.BigIntegerField(blank=True, null=True)

    class Meta(object):
        managed = False
        db_table = '"ana"."sd_bpjs_company"'


class SdBpjsProfileScrapeManager(PIIVaultModelManager):
    pass


class SdBpjsProfileScrape(PIIVaultModel):

    id = models.AutoField(db_column="sd_bpjs_profile_id", primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    real_name = models.TextField(null=True, blank=True)
    identity_number = models.TextField(null=True, blank=True)
    npwp_number = models.TextField(null=True, blank=True)
    birthday = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    gender = models.TextField(null=True, blank=True)
    bpjs_cards = JSONField(null=True, blank=True)
    total_balance = models.TextField(null=True, blank=True)
    type = models.TextField(null=True, blank=True)
    application_status_code = models.IntegerField(null=True, blank=True)

    # PII attributes
    real_name_tokenized = models.TextField(blank=True, null=True)
    identity_number_tokenized = models.TextField(blank=True, null=True)
    npwp_number_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)
    PII_FIELDS = ['real_name', 'identity_number', 'npwp_number', 'phone']
    PII_TYPE = 'kv'

    objects = SdBpjsProfileScrapeManager()

    class Meta(object):
        db_table = "sd_bpjs_profile"
        managed = False


class SdBpjsCompanyScrape(TimeStampedModel):

    id = models.AutoField(db_column="sd_bpjs_company_id", primary_key=True)
    profile = models.ForeignKey(
        SdBpjsProfileScrape,
        on_delete=models.PROTECT,
        db_column="sd_bpjs_profile_id",
        related_name="companies",
    )
    company = models.TextField(null=True, blank=True)
    current_salary = models.TextField(null=True, blank=True)
    last_payment_date = models.TextField(null=True, blank=True)
    employment_status = models.TextField(null=True, blank=True)
    employment_month_duration = models.TextField(null=True, blank=True)
    bpjs_card_number = models.TextField(null=True, blank=True)
    application_status_code = models.IntegerField(null=True, blank=True)

    class Meta(object):
        db_table = "sd_bpjs_company"
        managed = False


class SdBpjsPaymentScrape(TimeStampedModel):

    id = models.AutoField(db_column="sd_bpjs_payment_id", primary_key=True)
    company = models.ForeignKey(
        SdBpjsCompanyScrape,
        on_delete=models.PROTECT,
        db_column="sd_bpjs_company_id",
        related_name="payments",
    )
    payment_amount = models.BigIntegerField(null=True, blank=True)
    payment_date = models.TextField(null=True, blank=True)
    application_status_code = models.IntegerField(null=True, blank=True)

    class Meta(object):
        db_table = "sd_bpjs_payment"
        managed = False


class BpjsAPILogManager(GetInstanceMixin, JuloModelManager):
    pass


class BpjsAPILog(TimeStampedModel):
    id = models.AutoField(db_column="bpjs_api_log_id", primary_key=True)
    service_provider = models.TextField(blank=True, null=True)
    api_type = models.TextField(blank=True, null=True)
    http_status_code = models.TextField(blank=True, null=True)
    query_params = models.TextField(blank=True, null=True)
    request = models.TextField(blank=True, null=True)
    response = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, null=True, db_column="application_id"
    )
    customer = models.ForeignKey(Customer, models.DO_NOTHING, null=True, db_column="customer_id")
    http_referer = models.TextField(blank=True, null=True)
    application_status_code = models.IntegerField(null=True, blank=True)
    objects = BpjsAPILogManager()

    class Meta(object):
        db_table = "bpjs_api_log"


class BpjsUserAccess(TimeStampedModel):
    id = models.AutoField(db_column="sd_bpjs_company_id", primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    data_source = models.TextField(blank=True, null=True)
    user_access_credential = JSONField(blank=True, null=True)
    service_provider = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = "bpjs_user_access"
        managed = False
