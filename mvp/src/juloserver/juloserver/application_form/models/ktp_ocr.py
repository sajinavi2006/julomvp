from django.db import models
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class OcrKtpResultManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class OcrKtpResult(PIIVaultModel):
    id = models.AutoField(primary_key=True, db_column='ktp_ocr_result_id')
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    religion = models.CharField(
        max_length=100, verbose_name="Agama", blank=True, null=True, db_column='religion'
    )
    address = models.CharField(
        max_length=255, verbose_name="Alamat", blank=True, null=True, db_column='address'
    )
    blood_group = models.CharField(
        max_length=10, verbose_name="Golongan Darah", blank=True, null=True, db_column='blood_group'
    )
    gender = models.CharField(
        max_length=10, verbose_name="Jenis Kelamin", blank=True, null=True, db_column='gender'
    )
    district = models.CharField(
        max_length=100, verbose_name="Kecamatan", blank=True, null=True, db_column='district'
    )
    nik = models.CharField(
        max_length=16, verbose_name="NIK", blank=True, null=True, db_column='nik'
    )
    fullname = models.CharField(
        max_length=255, verbose_name="Nama Lengkap", blank=True, null=True, db_column='fullname'
    )
    province = models.CharField(
        max_length=100, verbose_name="Provinsi", blank=True, null=True, db_column='province'
    )
    city = models.CharField(
        max_length=100, verbose_name="Kota/Kabupaten", blank=True, null=True, db_column='city'
    )
    place_of_birth = models.CharField(
        max_length=100,
        verbose_name="Tempat Lahir",
        blank=True,
        null=True,
        db_column='place_of_birth',
    )
    date_of_birth = models.DateField(
        verbose_name="Tanggal Lahir", blank=True, null=True, db_column='date_of_birth'
    )
    rt_rw = models.CharField(
        max_length=20, verbose_name="RT/RW", blank=True, null=True, db_column='rt_rw'
    )
    administrative_village = models.CharField(
        max_length=100,
        verbose_name="Kelurahan/Desa",
        blank=True,
        null=True,
        db_column='administrative_village',
    )
    marital_status = models.CharField(
        max_length=50,
        verbose_name="Status Perkawinan",
        blank=True,
        null=True,
        db_column='marital_status',
    )
    job = models.CharField(
        max_length=100, verbose_name="Pekerjaan", blank=True, null=True, db_column='job'
    )
    nationality = models.CharField(
        max_length=100,
        verbose_name="Kewarganegaraan",
        blank=True,
        null=True,
        db_column='nationality',
    )
    valid_until = models.CharField(
        max_length=25, blank=True, null=True, verbose_name="Berlaku Hingga", db_column='valid_until'
    )

    # PII attributes
    fullname_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)

    PII_FIELDS = ['fullname', 'nik']
    PII_TYPE = 'kv'

    objects = OcrKtpResultManager()

    class Meta:
        managed = False
        db_table = 'ocr_ktp_result'


class OcrKtpMetaDataAttributeManager(GetInstanceMixin, JuloModelManager):
    pass


class OcrKtpMetaDataAttribute(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='ocr_ktp_meta_data_attribute_id')
    attribute_name = models.CharField(
        max_length=150, blank=True, null=True, db_column='attribute_name'
    )

    objects = OcrKtpMetaDataAttributeManager()

    class Meta:
        db_table = 'ocr_ktp_meta_data_attribute'
        managed = False


class OcrKtpMetaDataManager(GetInstanceMixin, JuloModelManager):
    pass


class OcrKtpMetaData(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='ocr_ktp_meta_data_id')
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    ocr_ktp_result_id = models.BigIntegerField(
        blank=False, null=False, db_column='ocr_ktp_result_id'
    )
    request_id = models.CharField(max_length=150, blank=True, null=True, db_column='request_id')
    fill_rate = models.FloatField(blank=True, null=True)
    vendor_fill_rate = models.FloatField(blank=True, null=True)

    objects = OcrKtpMetaDataManager()

    class Meta:
        db_table = 'ocr_ktp_meta_data'
        managed = False


class OcrKtpMetaDataValueManager(GetInstanceMixin, JuloModelManager):
    pass


class OcrKtpMetaDataValue(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='ocr_ktp_meta_data_value_id')
    ocr_ktp_meta_data = BigForeignKey(
        OcrKtpMetaData, models.DO_NOTHING, db_column='ocr_ktp_meta_data_id'
    )
    ocr_ktp_meta_data_attribute = BigForeignKey(
        OcrKtpMetaDataAttribute, models.DO_NOTHING, db_column='ocr_ktp_meta_data_attribute_id'
    )
    threshold_value = models.BigIntegerField(blank=True, null=True, db_column='threshold_value')
    confidence_value = models.BigIntegerField(blank=True, null=True, db_column='confidence_value')
    existed_in_raw = models.BooleanField(default=False)
    threshold_passed = models.BooleanField(default=False)

    objects = OcrKtpMetaDataValueManager()

    class Meta:
        db_table = 'ocr_ktp_meta_data_value'
        managed = False
