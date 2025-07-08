from __future__ import unicode_literals

from builtins import object
from django.db import models

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from django.core.validators import RegexValidator
import logging

from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager

logger = logging.getLogger(__name__)
ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class AxiataCustomerDataManager(GetInstanceMixin, PIIVaultModelManager, JuloModelManager):
    pass


# Create your models here.
class AxiataCustomerData(PIIVaultModel):
    HOME_STATUS_CHOICES = (
        ('Kontrak', 'Kontrak'),
        ('Kos', 'Kos'),
        ('Milik orang tua', 'Milik orang tua'),
        ('Milik keluarga', 'Milik keluarga'),
        ('Milik sendiri, lunas', 'Milik sendiri, lunas'),
        ('Milik sendiri, mencicil', 'Milik sendiri, mencicil'),
        ('Mess karyawan', 'Mess karyawan'),
    )

    LAST_EDUCATION_CHOICES = (
        ('SD', 'SD'),
        ('SLTP', 'SLTP'),
        ('SLTA', 'SLTA'),
        ('Diploma', 'Diploma'),
        ('S1', 'S1'),
        ('S2', 'S2'),
        ('S3', 'S3'),
    )

    PII_FIELDS = ['fullname', 'ktp', 'email', 'phone_number', 'npwp']
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='axiata_customer_data_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id',
        null=True, blank=True)
    acceptance_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    partner_application_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    account_number = models.CharField(max_length=100, null=True, blank=True)
    disbursement_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    disbursement_time = models.TimeField(auto_now_add=True, null=True, blank=True)
    ip_address = models.CharField(max_length=100, null=True, blank=True)
    first_payment_date = models.DateField(null=True, blank=True)
    partner_score_grade = models.CharField(max_length=50, null=True, blank=True)
    insurance_fee = models.BigIntegerField(default=0)
    funder = models.CharField(max_length=50, null=True, blank=True)
    partner_product_line = models.CharField(max_length=50, null=True, blank=True)
    fullname = models.CharField(max_length=100, null=True, blank=True)
    ktp = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ])
    brand_name = models.CharField(max_length=100, null=True, blank=True)
    company_name = models.CharField(max_length=100, null=True, blank=True)
    company_registration_number = models.CharField(max_length=100, null=True, blank=True)
    business_category = models.CharField(max_length=100, null=True, blank=True)
    type_of_business = models.CharField(max_length=100, null=True, blank=True)
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    dob = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=50, null=True, blank=True)
    marital_status = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    address_street_num = models.TextField(null=True, blank=True)
    shops_number = models.CharField(max_length=50, null=True, blank=True)
    distributor = models.CharField(max_length=50, null=True, blank=True)
    partner_id = models.CharField(max_length=10, null=True, blank=True)
    interest_rate = models.FloatField(default=0)
    loan_amount = models.BigIntegerField(default=0)
    loan_duration = models.IntegerField(default=0)
    loan_duration_unit = models.CharField(max_length=50, null=True, blank=True)
    monthly_installment = models.FloatField(default=0)
    final_monthly_installment = models.FloatField(default=0)
    reject_reason = models.TextField(null=True, blank=True)
    origination_fee = models.FloatField(null=True, blank=True)
    admin_fee = models.IntegerField(null=True, blank=True)
    invoice_id = models.CharField(max_length=50, null=True, blank=True)

    partner_application_id = models.TextField(null=True, blank=True)
    date_of_establishment = models.DateField(null=True, blank=True)
    merchant_score_grade = models.TextField(blank=True, null=True)
    limit = models.BigIntegerField(default=0)
    referral_code = models.TextField(blank=True, null=True)
    npwp = models.TextField(blank=True, null=True)
    ktp_image = models.TextField(blank=True, null=True)
    selfie_image = models.TextField(blank=True, null=True)
    loan_xid = models.BigIntegerField(blank=True, null=True)
    address_provinsi = models.CharField(max_length=100, validators=[ascii_validator],
                                        blank=True, null=True)
    address_kabupaten = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kecamatan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kelurahan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kodepos = models.CharField(max_length=5, blank=True, null=True,
                                       validators=[
                                           ascii_validator,
                                           RegexValidator(
                                               regex='^[0-9]{5}$',
                                               message='Kode pos has to be 5 numeric digits')
                                       ])
    loan_purpose = models.CharField("Tujuan pinjaman", max_length=100, blank=True, null=True)
    user_type = models.CharField(max_length=50, blank=True, null=True)
    income = models.BigIntegerField(blank=True, null=True)
    last_education = models.CharField(
        "Pendidikan terakhir",
        choices=LAST_EDUCATION_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True,
        null=True,
    )
    home_status = models.CharField(
        "Status domisili",
        choices=HOME_STATUS_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True,
        null=True,
    )
    certificate_number = models.CharField("Nomor akta", max_length=100, blank=True, null=True)
    certificate_date = models.DateField("Tanggal akta", blank=True, null=True)
    fullname_tokenized = models.TextField(blank=True, null=True)
    ktp_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)
    kin_name = models.TextField(blank=True, null=True)
    kin_mobile_phone = models.TextField(blank=True, null=True)
    npwp_tokenized = models.TextField(blank=True, null=True)

    objects = AxiataCustomerDataManager()

    class Meta(object):
        db_table = 'axiata_customer_data'


class SdkLog(TimeStampedModel):
    id = models.AutoField(db_column='sdk_log_id', primary_key=True)
    application_xid = models.CharField(max_length=100, blank=True, null=True)
    app_version = models.CharField(max_length=50)
    nav_log_ts = models.CharField(max_length=200)
    action = models.CharField(max_length=200)
    device_model_name = models.CharField(max_length=150)

    class Meta(object):
        db_table = 'sdk_log'


class AxiataRepaymentData(TimeStampedModel):
    id = models.AutoField(db_column='axiata_repayment_data_id', primary_key=True)
    application_xid = models.BigIntegerField(default=0, blank=True, null=True)
    payment_number = models.BigIntegerField(default=0)
    payment_amount = models.BigIntegerField(default=0)
    due_date = models.DateField(blank=True, null=True)
    payment_date = models.DateField(blank=True, null=True)
    messages = models.TextField(blank=True, null=True)
    partner_application_id = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'axiata_repayment_data'
        managed = False


class AxiataTemporaryDataPIIVaultManager(PIIVaultModelManager):
    pass


class AxiataTemporaryData(PIIVaultModel):
    PII_FIELDS = [
        'account_number',
        'fullname',
        'ktp',
        'phone_number',
        'email',
    ]
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='axiata_temporary_data_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id',
        null=True, blank=True)
    acceptance_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    partner_application_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    account_number = models.CharField(max_length=100, null=True, blank=True)
    disbursement_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    disbursement_time = models.TimeField(auto_now_add=True, null=True, blank=True)
    ip_address = models.CharField(max_length=100, null=True, blank=True)
    first_payment_date = models.DateField(null=True, blank=True)
    partner_score_grade = models.CharField(max_length=50, default="A")
    insurance_fee = models.BigIntegerField(default=0)
    funder = models.CharField(max_length=50, default="ADCI")
    partner_product_line = models.CharField(max_length=50, default="ISCF")
    fullname = models.CharField(max_length=100, null=True, blank=True)
    ktp = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ])
    brand_name = models.CharField(max_length=100, default="", null=True, blank=True)
    company_name = models.CharField(max_length=100, default="", null=True, blank=True)
    company_registration_number = models.CharField(max_length=100, null=True, blank=True)
    business_category = models.CharField(max_length=100, null=True, blank=True)
    type_of_business = models.CharField(max_length=100, default="Perorangan", null=True, blank=True)
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    dob = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=50, null=True, blank=True)
    marital_status = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    address_street_num = models.TextField(null=True, blank=True)
    shops_number = models.CharField(max_length=50, default="1")
    distributor = models.CharField(max_length=50, null=True, blank=True)
    partner_id = models.CharField(max_length=10, default="", null=True, blank=True)
    interest_rate = models.FloatField(default=0)
    loan_amount = models.BigIntegerField(default=0)
    loan_duration = models.IntegerField(default=0)
    loan_duration_unit = models.CharField(max_length=50, default="Days")
    monthly_installment = models.FloatField(default=0)
    final_monthly_installment = models.FloatField(default=0)
    reject_reason = models.TextField(null=True, blank=True)
    origination_fee = models.FloatField(null=True, blank=True)
    admin_fee = models.IntegerField(default=0)
    invoice_id = models.CharField(max_length=50, default=0)

    partner_application_id = models.TextField(null=True, blank=True)
    ktp_image = models.TextField(blank=True, null=True)
    selfie_image = models.TextField(blank=True, null=True)
    address_provinsi = models.CharField(max_length=100, validators=[ascii_validator],
                                        blank=True, null=True)
    address_kabupaten = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kecamatan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kelurahan = models.CharField(max_length=100, validators=[ascii_validator],
                                         blank=True, null=True)
    address_kodepos = models.CharField(max_length=5, blank=True, null=True,
                                       validators=[
                                           ascii_validator,
                                           RegexValidator(
                                               regex='^[0-9]{5}$',
                                               message='Kode pos has to be 5 numeric digits')
                                       ])
    loan_purpose = models.CharField("Tujuan pinjaman", max_length=100, default="Modal usaha")
    is_uploaded = models.BooleanField(default=False)
    is_submitted = models.BooleanField(default=False)
    axiata_customer_data = models.OneToOneField(
        AxiataCustomerData, models.DO_NOTHING, db_column='axiata_customer_data_id',
        null=True, blank=True
    )
    account_number_tokenized = models.TextField(null=True, blank=True)
    fullname_tokenized = models.TextField(null=True, blank=True)
    ktp_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)
    email_tokenized = models.TextField(null=True, blank=True)

    objects = AxiataTemporaryDataPIIVaultManager()

    class Meta(object):
        db_table = 'axiata_temporary_data'
