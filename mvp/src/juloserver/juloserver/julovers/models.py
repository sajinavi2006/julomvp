from ckeditor.fields import RichTextField

from django.core.validators import RegexValidator
from django.db import models
from juloserver.julo.models import (
    TimeStampedModel,
    ascii_validator,
)
from juloserver.julovers.constants import JuloverPageConst
from django.contrib.postgres.fields import JSONField

class Julovers(TimeStampedModel):
    GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita')
    )
    MARITAL_STATUS_CHOICES = (
        ('Lajang', 'Lajang'),
        ('Menikah', 'Menikah'),
        ('Cerai', 'Cerai'),
        ('Janda / duda', 'Janda / duda')
    )
    JOB_TYPE_CHOICES = (
        ('Pegawai swasta', 'Pegawai swasta'),
        ('Pegawai negeri', 'Pegawai negeri'),
        ('Pengusaha', 'Pengusaha'),
        ('Freelance', 'Freelance'),
        ('Pekerja rumah tangga', 'Pekerja rumah tangga'),
        ('Lainnya', 'Lainnya'),
        ('Staf rumah tangga', 'Staf rumah tangga'),
        ('Ibu rumah tangga', 'Ibu rumah tangga'),
        ('Mahasiswa', 'Mahasiswa'),
        ('Tidak bekerja', 'Tidak bekerja')
    )
    id = models.AutoField(db_column='julovers_id', primary_key=True)
    fullname = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    address = models.CharField(max_length=100, validators=[ascii_validator], blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    birth_place = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    mobile_phone_number = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^\+?\d{10,15}$',
                message='mobile phone has to be 10 to 15 numeric digits'
            )
        ],
        unique=True,
    )
    gender = models.CharField(
        choices=GENDER_CHOICES,
        max_length=10,
        validators=[ascii_validator],
        blank=True, null=True
    )
    marital_status = models.CharField(
        choices=MARITAL_STATUS_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True, null=True
    )
    job_industry = models.CharField(
        max_length=100,
        validators=[ascii_validator],
        blank=True, null=True
    )
    job_description = models.CharField(
        max_length=100,
        validators=[ascii_validator],
        blank=True, null=True
    )
    job_type = models.CharField(
        choices=JOB_TYPE_CHOICES,
        max_length=50,
        validators=[ascii_validator],
        blank=True, null=True
    )
    job_start = models.DateField(blank=True, null=True)
    bank_name = models.CharField(
        max_length=250, validators=[ascii_validator], blank=True, null=True
    )
    bank_account_number = models.CharField(
        max_length=50, validators=[ascii_validator], blank=True, null=True
    )
    name_in_bank = models.CharField(
        max_length=100, validators=[ascii_validator], blank=True, null=True
    )
    resign_date = models.DateField(blank=True, null=True)
    set_limit = models.BigIntegerField(default=0)
    is_sync_application = models.BooleanField(default=False, blank=True)
    real_nik = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ], blank=True, null=True, unique=True)

    customer_xid = models.CharField(max_length=50, blank=True, null=True, unique=True)
    real_nik_tokenized = models.CharField(max_length=50, blank=True, null=True)
    fullname_tokenized = models.CharField(max_length=50, blank=True, null=True)
    email_tokenized = models.CharField(max_length=50, blank=True, null=True)
    mobile_phone_number_tokenized = models.CharField(max_length=50, blank=True, null=True)

    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True,
    )


    class Meta(object):
        db_table = 'julovers'


class JuloverPage(TimeStampedModel):
    id = models.AutoField(db_column='julover_page_id', primary_key=True)
    is_active = models.BooleanField(default=True)
    title = models.TextField(unique=True, choices=JuloverPageConst.CHOICES)
    content = RichTextField(blank=True)
    extra_data = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = 'julover_page'
