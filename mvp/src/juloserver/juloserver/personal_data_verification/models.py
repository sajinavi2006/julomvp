from copy import deepcopy
from django.db import models

from juloserver.julo.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import GetInstanceMixin
from juloserver.fraud_score.mixins import FraudPIIMaskingModelMixin
from juloserver.fraud_score.constants import FraudPIIFieldTypeConst
from juloserver.personal_data_verification.constants import (
    DukcapilDirectConst,
    DukcapilDirectError,
    MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
)
from django.contrib.postgres.fields import JSONField

from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager
from juloserver.pii_vault.constants import PIIType


class DukcapilResponse(TimeStampedModel):
    DUKCAPIL_SOURCE_CHOICES = (('Dukcapil', 'Dukcapil'), ('AsliRI', 'AsliRI'))
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    trx_id = models.TextField(null=True, blank=True)
    ref_id = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    name = models.NullBooleanField()
    birthdate = models.NullBooleanField()
    birthplace = models.NullBooleanField()
    address = models.TextField(null=True, blank=True)
    source = models.CharField(max_length=100, null=True, blank=True)
    gender = models.NullBooleanField()
    marital_status = models.NullBooleanField()
    job_type = models.NullBooleanField()
    address_street = models.NullBooleanField()
    address_kelurahan = models.NullBooleanField()
    address_kecamatan = models.NullBooleanField()
    address_kabupaten = models.NullBooleanField()
    address_provinsi = models.NullBooleanField()

    class Meta(object):
        db_table = 'dukcapil_response'

    def __str__(self):
        return str(self.id)

    def is_eligible(self):
        from juloserver.julolog.julolog import JuloLog
        from juloserver.personal_data_verification.services import (
            get_dukcapil_verification_setting_leadgen,
            get_dukcapil_verification_setting,
        )

        logger = JuloLog(__name__)
        logger.info({"msg": "is_eligible", "application": self.application.id})
        if (
            self.status in DukcapilDirectError.not_eligible()
            or self.errors in DukcapilDirectError.not_eligible()
        ):
            logger.info(
                {
                    "msg": "Dukcapil is eligible",
                    "status": self.status,
                    "status_in": self.status in DukcapilDirectError.not_eligible(),
                    "errors": self.errors,
                    "errors_in": self.errors in DukcapilDirectError.not_eligible(),
                    "application": self.application.id,
                }
            )
            return False

        results = [getattr(self, field) for field in DukcapilDirectConst.VERIFICATION_FIELDS]
        logger.info(
            {"msg": "Dukcapil is eligible", "fields": results, "application": self.application.id}
        )
        if None in results:
            return False

        pass_criteria = MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS

        if self.application.is_partnership_leadgen():
            setting = get_dukcapil_verification_setting_leadgen(self.application.partner.name)
        else:
            setting = get_dukcapil_verification_setting()

        if setting.is_active:
            pass_criteria = setting.minimum_checks_to_pass

            logger.info(
                {
                    "msg": "Dukcapil is eligible",
                    "pass_criteria": pass_criteria,
                    "application": self.application.id,
                }
            )

        return sum(results) >= pass_criteria

    def is_fraud(self):
        """
        Check is dukcapil_response is fraud or not.

        Returns:
            bool
        """
        return self.errors in DukcapilDirectError.is_fraud()

    def highlight_dukcapil_tab(self):
        return not self.is_eligible()


class DukcapilAsliriBalance(TimeStampedModel):
    id = models.AutoField(db_column='dukcapil_asliri_balance_id', primary_key=True)
    status = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    remaining_balance = models.IntegerField(null=True, blank=True)
    url = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'dukcapil_asliri_balance'


class DukcapilAPILogManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class DukcapilAPILog(PIIVaultModel):
    id = BigAutoField(db_column='dukcapil_api_log_id', primary_key=True)
    dukcapil_response_id = models.BigIntegerField(null=True, blank=True)
    api_type = models.CharField(max_length=100, null=True, blank=True)
    http_status_code = models.CharField(max_length=100, null=True, blank=True)
    request = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    latency = models.FloatField(null=True, blank=True)

    request_tokenized = models.CharField(max_length=50, null=True, blank=True)
    response_tokenized = models.CharField(max_length=50, null=True, blank=True)

    # PII model attributes
    PII_FIELDS = ['request', 'response']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'

    objects = DukcapilAPILogManager()

    class Meta(object):
        db_table = 'dukcapil_api_log'
        managed = False


class DukcapilCallbackInfoAPILogManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class DukcapilCallbackInfoAPILog(PIIVaultModel):
    id = BigAutoField(db_column='dukcapil_callback_info_api_log_id', primary_key=True)
    application_id = models.BigIntegerField()
    api_type = models.CharField(max_length=100, null=True, blank=True)
    http_status_code = models.CharField(max_length=100, null=True, blank=True)
    request = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    latency = models.FloatField(null=True, blank=True)

    request_tokenized = models.CharField(max_length=50, null=True, blank=True)

    # PII model attributes
    PII_FIELDS = ['request']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'

    objects = DukcapilCallbackInfoAPILogManager

    class Meta(object):
        db_table = 'dukcapil_callback_info_api_log'
        managed = False


class DukcapilFaceRecognitionCheckManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class DukcapilFaceRecognitionCheck(PIIVaultModel):
    id = BigAutoField(db_column='dukcapil_face_recognition_check_id', primary_key=True)
    application_id = models.BigIntegerField()
    transaction_id = models.CharField(max_length=20, unique=True, null=True)
    transaction_source = models.TextField()
    client_customer_id = models.TextField()
    nik = models.TextField()
    threshold = models.PositiveSmallIntegerField()
    image_id = models.BigIntegerField()
    template = models.TextField()
    type = models.TextField()
    position = models.TextField()
    response_code = models.TextField(null=True, blank=True)
    response_score = models.TextField(null=True, blank=True)
    raw_response = models.TextField(null=True, blank=True)
    quota_limiter = models.TextField(null=True, blank=True)

    nik_tokenized = models.CharField(max_length=50, null=True, blank=True)
    raw_response_tokenized = models.CharField(max_length=50, null=True, blank=True)

    # PII model attributes
    PII_FIELDS = ['nik', 'raw_response']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'onboarding_pii_vault'

    objects = DukcapilFaceRecognitionCheckManager

    class Meta(object):
        db_table = 'dukcapil_face_recognition_check'
        managed = False


class BureauEmailSocial(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='bureau_email_social_id', primary_key=True)
    raw_data = JSONField()
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {
        'raw_data': [
            (FraudPIIFieldTypeConst.EMAIL, ['email']),
            (FraudPIIFieldTypeConst.NAME, ['ok', 'name']),
        ]
    }

    def get_fraud_pii_masking_fields(self):
        """
        For each key possibly have name value
        """
        pii_fields = deepcopy(self.FRAUD_PII_MASKING_FIELDS)
        filter_field = [p[1][0] for p in pii_fields['raw_data']]
        for parent, child in self.raw_data.items():
            if not isinstance(child, dict):
                continue
            if parent in filter_field:
                continue
            for key, item in child.items():
                if key != 'name':
                    continue
                if not item:
                    continue
                pii_fields['raw_data'].append((FraudPIIFieldTypeConst.NAME, [parent, key]))
        return pii_fields

    class Meta(object):
        db_table = 'bureau_email_social'


class BureauPhoneSocial(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='bureau_phone_social_id', primary_key=True)
    raw_data = JSONField()
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {'raw_data': [(FraudPIIFieldTypeConst.PHONE_NUMBER, ['number'])]}

    def get_fraud_pii_masking_fields(self):
        """
        For each key possibly have name value
        """
        pii_fields = deepcopy(self.FRAUD_PII_MASKING_FIELDS)
        filter_field = [p[1][0] for p in pii_fields['raw_data']]
        for parent, child in self.raw_data.items():
            if not isinstance(child, dict):
                continue
            if parent in filter_field:
                continue
            for key, item in child.items():
                if key != 'name':
                    continue
                if not item:
                    continue
                pii_fields['raw_data'].append((FraudPIIFieldTypeConst.NAME, [parent, key]))
        return pii_fields

    class Meta(object):
        db_table = 'bureau_phone_social'


class BureauMobileIntelligence(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='bureau_mobile_intelligence_id', primary_key=True)
    raw_data = JSONField()
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {
        'raw_data': [
            (FraudPIIFieldTypeConst.NAME, ['firstName']),
            (FraudPIIFieldTypeConst.NAME, ['lastName']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['cleansedSmsPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['cleansedCallPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['originalCompletePhoneNumber']),
        ]
    }

    class Meta(object):
        db_table = 'bureau_mobile_intelligence'


class BureauEmailAttributes(TimeStampedModel):
    id = BigAutoField(db_column='bureau_email_attributes_id', primary_key=True)
    raw_data = JSONField()
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'bureau_email_attributes'


class BureauDeviceIntelligence(TimeStampedModel):
    id = BigAutoField(db_column='bureau_device_intelligence_id', primary_key=True)
    raw_data = JSONField()
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    status = models.TextField(null=True, blank=True)
    errors = models.TextField(null=True, blank=True)
    session_id = models.TextField()

    class Meta(object):
        db_table = 'bureau_device_intelligence'
