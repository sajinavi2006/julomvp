import os
import datetime

from django.conf import settings
from django.core.validators import (MaxValueValidator, MinValueValidator,
                                    RegexValidator)
from django.db import models
from juloserver.employee_financing.constants import (EMPLOYMENT_CHOICES,
                                                     YES_NO_UNKNOWN_CHOICES, EmploymentStatus)
from juloserver.julo.admin2.job_data_constants import JOB_INDUSTRY_LIST
from juloserver.julocore.data.models import (GetInstanceMixin,
                                             JuloModelManager,
                                             TimeStampedModel)
from juloserver.partnership.constants import (GenderChoices, MarriageStatus,
                                              EFWebFormType)
from juloserver.julo.clients import get_s3_url
from juloserver.julo.utils import get_oss_presigned_url, get_oss_public_url
from juloserver.julo.models import S3ObjectModel
from typing import Any

from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class CompanyManager(GetInstanceMixin, JuloModelManager):
    pass


class CompanyPIIVaultManager(PIIVaultModelManager, CompanyManager):
    pass


class Company(PIIVaultModel):
    LIMIT_CHOICES = (
        ('Defined', 'Defined'),
        ('Undefined', 'Undefined')
    )

    CENTRALISED_DEDUCTION_CHOICES = (
        ('Yes', 'Yes'),
        ('No', 'No')
    )
    PII_FIELDS = [
        'email',
        'name',
        'phone_number',
    ]
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(
        db_column='company_id', primary_key=True
    )
    partner = models.ForeignKey('julo.Partner', models.DO_NOTHING, db_column='partner_id')
    name = models.CharField(max_length=100, db_index=True, default=None)
    email = models.EmailField(unique=True)
    address = models.TextField(default=None)
    phone_number = models.CharField(max_length=18, unique=True, validators=[
                                    RegexValidator(regex='^[ -~]+$', message='hanya angka')])
    company_term = models.DateField(default=datetime.date.today)
    company_size = models.IntegerField(
        validators=[
            MinValueValidator(1, message='Harus lebih besar atau sama dengan 1')],
        default=1
    )
    industry = models.CharField(choices=JOB_INDUSTRY_LIST,
                                max_length=100, default='Tehnik / Computer')
    company_profitable = models.CharField(
        choices=YES_NO_UNKNOWN_CHOICES, max_length=8, default='Unknown')
    centralised_deduction = models.CharField(
        choices=CENTRALISED_DEDUCTION_CHOICES, max_length=4, default='Tidak')
    payday = models.IntegerField(
        validators=[
            MinValueValidator(1, message='Harus lebih besar atau sama dengan 1'),
            MaxValueValidator(31, message='Harus lebih kecil atau sama dengan 31')],
        default=1
    )
    limit_type = models.CharField(
        choices=LIMIT_CHOICES, max_length=9, default='Undefined')
    recipients = models.TextField(
        blank=True, null=True, help_text="please insert like this format: julo@julofinance.com, julo2@finance.com")
    is_active = models.BooleanField(default=False)
    email_tokenized = models.TextField(null=True, blank=True)
    name_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = CompanyPIIVaultManager()

    class Meta(object):
        db_table = 'company'
        verbose_name_plural = "companies"

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.name)

    def save(self, *args, **kwargs):
        if self.id:
            return super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
            CompanyConfig.objects.create(
                company=self
            )


class EmployeeManager(GetInstanceMixin, JuloModelManager):
    pass


class EmployeePIIVaultManager(PIIVaultModelManager, EmployeeManager):
    pass


class Employee(PIIVaultModel):
    PII_FIELDS = [
        'bank_account_number',
    ]
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(
        db_column='employee_id', primary_key=True
    )
    company = models.ForeignKey(
        'employee_financing.Company', models.DO_NOTHING, db_column='company_id', null=True, blank=True
    )
    job_position = models.CharField(max_length=100, blank=True, null=True)
    employment_status = models.CharField(
        choices=EMPLOYMENT_CHOICES, max_length=9, default=EmploymentStatus.CONTRACT)
    join_date = models.DateField(null=True, blank=True)
    job_term = models.DateField(null=True, blank=True)
    bank_name = models.CharField(max_length=250, validators=[ascii_validator],
                                 blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, validators=[ascii_validator],
                                           blank=True, null=True)
    net_salary = models.IntegerField(
        validators=[
            MinValueValidator(1, message='Harus lebih besar atau sama dengan 1')],
        default=1
    )
    limit_to_be_given = models.IntegerField(
        validators=[
            MinValueValidator(1, message='Harus lebih besar atau sama dengan 1')],
        default=1
    )
    customer = models.OneToOneField('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    is_active = models.BooleanField(default=False)
    bank_account_number_tokenized = models.TextField(null=True, blank=True)

    objects = EmployeePIIVaultManager()

    class Meta(object):
        db_table = 'employee'


class CompanyConfigManager(GetInstanceMixin, JuloModelManager):
    pass


class CompanyConfig(TimeStampedModel):
    company = models.OneToOneField(Company, models.DO_NOTHING)
    allow_disburse = models.BooleanField(
        default=True,
        help_text="This field will be use for allowing disburse amount where "
                  "amount_request > set_limit & tenor_selected > max_tenor"
    )

    objects = CompanyConfigManager()

    class Meta(object):
        db_table = 'company_config'


class EmFinancingWFApplicationPIIVaultManager(PIIVaultModelManager):
    pass


class EmFinancingWFApplication(PIIVaultModel):
    """
        Currently Only Running in EF Pilot Project
        This form need a ktp_photo & selfie, should be using centralize table Image
    """
    GENDER_CHOICES = (
        (GenderChoices.MALE, 'Pria'),
        (GenderChoices.FEMALE, 'Wanita'))
    MARRIAGE_STATUS = (
        (MarriageStatus.MARRIED, 'Menikah'),
        (MarriageStatus.NOT_MARRIED, 'Belum Menikah')
    )
    PII_FIELDS = [
        'email',
        'name',
        'nik',
        'phone_number',
        'mother_name',
        'mother_phone_number',
        'couple_name',
        'couple_phone_number',
    ]
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='employee_financing_web_form_application_id',
                          primary_key=True)
    email = models.EmailField(db_index=True)
    company = models.ForeignKey(
        'employee_financing.Company', models.DO_NOTHING, db_column='company_id',
        null=True, blank=True
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    nik = models.CharField(
        max_length=16, validators=[
            ascii_validator, RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ], db_index=True)
    phone_number = models.CharField(max_length=20)
    place_of_birth = models.CharField(max_length=100)
    gender = models.CharField("Jenis kelamin",
                              choices=GENDER_CHOICES,
                              max_length=10,
                              validators=[ascii_validator])
    marriage_status = models.CharField(choices=MARRIAGE_STATUS,
                                       max_length=16)
    mother_name = models.CharField(max_length=100, blank=True, null=True)
    mother_phone_number = models.CharField(max_length=20, blank=True, null=True)
    couple_name = models.CharField(max_length=100, blank=True, null=True)
    couple_phone_number = models.CharField(max_length=20, blank=True, null=True)
    expense_per_month = models.FloatField(default=0)
    expenses_monthly_house_rent = models.FloatField(default=0)
    debt_installments_per_month = models.FloatField(default=0)
    request_loan_amount = models.FloatField(default=0)
    tenor = models.IntegerField(blank=True, null=True)

    email_tokenized = models.TextField(null=True, blank=True)
    name_tokenized = models.TextField(null=True, blank=True)
    nik_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)
    mother_name_tokenized = models.TextField(null=True, blank=True)
    mother_phone_number_tokenized = models.TextField(null=True, blank=True)
    couple_name_tokenized = models.TextField(null=True, blank=True)
    couple_phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = EmFinancingWFApplicationPIIVaultManager()

    class Meta(object):
        db_table = 'employee_financing_web_form_application'

    def __str__(self) -> str:
        return self.email


class EmFinancingWFDisbursementPIIVaultManager(PIIVaultModelManager):
    pass


class EmFinancingWFDisbursement(PIIVaultModel):
    """
        Currently Only Running in EF Pilot Project
    """

    PII_FIELDS = ['nik']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    company = models.ForeignKey(
        'employee_financing.Company', models.DO_NOTHING, db_column='company_id',
        null=True, blank=True
    )
    nik = models.CharField(
        max_length=16, validators=[
            ascii_validator, RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ], db_index=True)
    request_loan_amount = models.FloatField(default=0)
    tenor = models.IntegerField()
    nik_tokenized = models.TextField(null=True, blank=True)

    objects = EmFinancingWFDisbursementPIIVaultManager()

    class Meta(object):
        db_table = 'employee_financing_web_form_disbursement'

    def __str__(self) -> str:
        return self.nik


class EmFinancingWFAccessTokenPIIVaultManager(PIIVaultModelManager):
    pass


class EmFinancingWFAccessToken(PIIVaultModel):
    """
        Currently Only Running in EF Pilot Project
    """
    WEB_FORM_TYPE = (
        (EFWebFormType.APPLICATION, 'application'),
        (EFWebFormType.DISBURSEMENT, 'disbursement'),
        (EFWebFormType.MASTER_AGREEMENT, 'master_agreement')
    )
    PII_FIELDS = ['email', 'name']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    email = models.EmailField(db_index=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    token = models.TextField()
    company = models.ForeignKey(
        'employee_financing.Company', models.DO_NOTHING, db_column='company_id',
        null=True, blank=True
    )
    expired_at = models.DateTimeField(null=True, blank=True)
    form_type = models.CharField(choices=WEB_FORM_TYPE, max_length=50)
    limit_token_creation = models.IntegerField(default=3,
                                               help_text='This filed to limit max generate token')
    is_clicked = models.BooleanField(default=False,
                                     help_text='For analytical things to know is user clicked')
    is_used = models.BooleanField(default=False,
                                  help_text="To fill if user is submit or not in web form")

    email_tokenized = models.TextField(null=True, blank=True)
    name_tokenized = models.TextField(null=True, blank=True)

    objects = EmFinancingWFAccessTokenPIIVaultManager()

    class Meta(object):
        db_table = 'employee_financing_web_form_access_token'

    def __str__(self) -> str:
        return self.email


def upload_to(instance: Any, filename: str) -> str:
    return 'image_upload/{0}/{1}'.format(instance.pk, filename)


class EmployeeFinancingFormURLEmailContent(TimeStampedModel):
    email_subject = models.CharField(max_length=255)
    email_content = models.TextField(
        help_text='Please add {{ url }} on the field to include the URL on the email'
    )
    WEB_FORM_TYPE = (
        (EFWebFormType.APPLICATION, 'application'),
        (EFWebFormType.DISBURSEMENT, 'disbursement')
    )
    form_type = models.CharField(choices=WEB_FORM_TYPE, max_length=16, blank=True, null=True)

    class Meta(object):
        db_table = 'employee_financing_form_url_email_content'

    def __str__(self) -> str:
        return str(self.get_form_type_display())
