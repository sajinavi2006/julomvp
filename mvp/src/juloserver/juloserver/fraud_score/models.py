import re
from django.contrib.postgres.fields import JSONField, ArrayField
from django.db import models

from juloserver.julo.models import (
    Application,
    Customer,
    PIIType,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
    BigOneToOneField,
)
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.fraud_score.mixins import FraudPIIMaskingModelMixin
from juloserver.fraud_score.constants import FraudPIIFieldTypeConst
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class BonzaScoringResult(TimeStampedModel):
    id = models.AutoField(db_column='bonza_scoring_results_id', primary_key=True)
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    request_id = models.TextField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    api_response = models.TextField(null=True, blank=True)
    holdout = models.BooleanField(default=False)
    version = models.CharField(max_length=200, blank=True, null=True)
    on_reverified_period = models.BooleanField(default=False)
    transaction_fraud_model_account = models.ForeignKey(
        'fraud_score.TransactionFraudModelAccount', on_delete=models.DO_NOTHING,
        db_column='transaction_fraud_model_account_id', null=True)
    is_first_loan = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'bonza_scoring_results'


class BonzaStoringResult(TimeStampedModel):
    id = models.AutoField(db_column='bonza_storing_results_id', primary_key=True)
    method_name = models.CharField(max_length=200)
    object_id = models.CharField(max_length=200)
    status = models.TextField(null=True, blank=True)
    api_response = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'bonza_storing_results'


class BonzaExpiredHoldout(TimeStampedModel):
    id = models.AutoField(db_column='bonza_expired_holdout_id', primary_key=True)
    expired_date = models.DateTimeField(auto_now_add=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id')

    class Meta(object):
        db_table = 'bonza_expired_holdout'


class TransactionFraudModelAccount(TimeStampedModel):
    id = models.AutoField(db_column='transaction_fraud_model_account_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id')
    account_status_history = models.ForeignKey(
        'account.AccountStatusHistory', models.DO_NOTHING, db_column='account_status_history_id')
    start_expire_date = models.DateTimeField()
    end_expire_date = models.DateTimeField()
    fraud_model = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'transaction_fraud_model_account'


class SeonFingerprint(TimeStampedModel):
    """
    This model is used to store the SEON fingerprint data.
    """
    id = BigAutoField(db_column='seon_fingerprint_id', primary_key=True)
    customer = BigForeignKey(
        'julo.Customer',
        models.DO_NOTHING,
        db_column='customer_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    trigger = models.TextField()
    sdk_fingerprint_hash = models.TextField(blank=True, null=True)
    ip_address = models.TextField(blank=True, null=True)
    target_type = models.TextField(db_index=True)
    target_id = models.TextField(db_index=True)

    class Meta(object):
        db_table = 'seon_fingerprint'


class SeonFraudRequestManager(PIIVaultModelManager):
    pass


class SeonFraudRequest(PIIVaultModel):
    PII_FIELDS = ['phone_number', 'email_address']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = BigAutoField(db_column='seon_fraud_request_id', primary_key=True)
    seon_fingerprint = BigForeignKey(
        'fraud_score.SeonFingerprint',
        models.DO_NOTHING,
        db_column='seon_fingerprint_id',
        blank=True,
        null=True,
        db_constraint=False,
    )

    # See action_type in https://docs.seon.io/api-reference#fraud-api-request
    action_type = models.TextField(null=True, blank=True)

    # an unique identifier for each request.
    transaction_id = models.TextField()

    email_address = models.TextField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)

    # Response time in milliseconds
    response_time = models.PositiveIntegerField(null=True, blank=True)

    response_code = models.PositiveIntegerField(null=True, blank=True)
    error_type = models.TextField(null=True, blank=True)
    seon_error_code = models.TextField(null=True, blank=True)

    email_address_tokenized = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)

    objects = SeonFraudRequestManager()

    class Meta:
        db_table = 'seon_fraud_request'


class SeonFraudResult(TimeStampedModel):
    """
    For more detailed information,
    please refer to https://docs.seon.io/api-reference#fraud-api-response
    """
    id = BigAutoField(db_column='seon_fraud_result_id', primary_key=True)
    seon_fraud_request = BigForeignKey(
        'fraud_score.SeonFraudRequest',
        models.DO_NOTHING,
        db_column='seon_fraud_request_id',
        blank=True,
        null=True,
        db_constraint=False,
    )

    fraud_score = models.FloatField(null=True, blank=True)
    state = models.TextField(null=True, blank=True)
    seon_id = models.TextField(null=True, blank=True)
    calculation_time = models.PositiveIntegerField(null=True, blank=True)
    version = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'seon_fraud_result'


class SeonFraudRawResult(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='seon_fraud_raw_result_id', primary_key=True)
    seon_fraud_result = BigOneToOneField(
        'fraud_score.SeonFraudResult',
        models.DO_NOTHING,
        db_column='seon_fraud_result_id',
        related_name='raw_result',
        blank=True,
        null=True,
        db_constraint=False,
    )
    raw = models.TextField()

    FRAUD_PII_MASKING_FIELDS = {
        'raw': [
            (FraudPIIFieldTypeConst.EMAIL, ['email_details', 'email']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['phone_details', 'number']),
        ]
    }

    class Meta:
        db_table = 'seon_fraud_raw_result'


# Deprecated as of ANTIFRAUD-492
class GrabDefenceEventTokenResult(TimeStampedModel):
    id = models.AutoField(db_column='grab_defence_event_token_result_id', primary_key=True)
    customer = BigForeignKey(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id', blank=True, null=True)
    customer_event_id = models.TextField()
    customer_event_type = models.TextField()
    guardian_event_id = models.TextField()
    status = models.TextField(blank=True, null=True)
    app_id = models.TextField(blank=True, null=True)
    tenant_id = models.TextField(blank=True, null=True)
    app_version = models.TextField(blank=True, null=True)
    country_code = models.TextField(null=True, blank=True)
    platform = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'grab_defence_event_token_result'


# Deprecated as of PLAT-1787
class GrabDefenceVerdictRawResult(TimeStampedModel):
    """
    This model is deprecated as of PLAT-1787.
    TODO: Removal of this model and the table after PLAT-1787 release.
    """

    id = BigAutoField(db_column='grab_defence_verdict_raw_result_id', primary_key=True)
    raw_response = models.TextField()
    response_time = models.PositiveIntegerField(null=True, blank=True)
    response_code = models.PositiveIntegerField(null=True, blank=True)
    response_status = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'grab_defence_verdict_raw_result'


# Deprecated as of PLAT-1787
class GrabDefenceVerdictResult(TimeStampedModel):
    id = BigAutoField(db_column='grab_defence_verdict_result_id', primary_key=True)

    grab_defence_verdict_raw_result = BigForeignKey(  # TODO: Deprecated as of PLAT-1787
        'fraud_score.GrabDefenceVerdictRawResult',
        models.DO_NOTHING,
        db_column='grab_defence_verdict_raw_result_id',
        related_name='verdict_raw_response',
        blank=True,
        null=True,
        db_constraint=False,
    )

    entity_id = models.TextField()
    entity_type = models.TextField(null=True, blank=True)
    event_id = models.TextField(null=True, blank=True)
    device_id = models.TextField(null=True, blank=True)
    customer_event_type = models.TextField(null=True, blank=True)
    customer_event_id = models.TextField(null=True, blank=True)
    verdict_list = ArrayField(models.TextField(), blank=True, null=True)

    class Meta:
        db_table = 'grab_defence_verdict_result'


# Deprecated as of ANTIFRAUD-492
class GrabDefencePredictRawResult(TimeStampedModel):
    id = BigAutoField(db_column='grab_defence_predict_raw_result_id', primary_key=True)
    grab_defence_verdict_result = BigForeignKey(
        'fraud_score.GrabDefenceVerdictResult',
        models.DO_NOTHING,
        db_column='grab_defence_verdict_result_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    raw_response = models.TextField()
    response_time = models.PositiveIntegerField(null=True, blank=True)
    response_code = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'grab_defence_predict_raw_result'


# Deprecated as of ANTIFRAUD-492
class GrabDefencePredictResult(TimeStampedModel):
    id = BigAutoField(db_column='grab_defence_predict_result_id', primary_key=True)
    grab_defence_predict_raw_result = BigForeignKey(
        'fraud_score.GrabDefencePredictRawResult',
        models.DO_NOTHING,
        db_column='grab_defence_predict_raw_result_id',
        related_name='predict_raw_response',
        blank=True,
        null=True,
        db_constraint=False,
    )

    event_type = models.TextField(null=True, blank=True)
    event_id = models.TextField(null=True, blank=True)
    recommendations = JSONField(null=True, blank=True)
    rule_results = JSONField(null=True, blank=True)

    class Meta:
        db_table = 'grab_defence_predict_result'


# Deprecated as of ANTIFRAUD-492
class GrabDefenceAssociatedDevice(TimeStampedModel):
    id = BigAutoField(db_column='grab_defence_associated_device_id', primary_key=True)
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        db_constraint=False,
        unique=True,
    )
    entity_id = models.TextField(null=False, blank=False)
    associated_customer_ids = ArrayField(models.TextField(), default=list)
    associated_entity_ids = ArrayField(models.TextField(), default=list)
    total_device = models.IntegerField(default=0)

    class Meta(object):
        db_table = 'grab_defence_associated_device'

    def update_total_device(self) -> int:
        """
        Update total device count without saving the object
        Returns:
            int: total device count
        """
        self.total_device = len(self.associated_entity_ids)
        return self.total_device


# Deprecated as of ANTIFRAUD-492
class GrabDefencePredictEventResult(FraudPIIMaskingModelMixin, TimeStampedModel):
    class Meta:
        db_table = 'grab_defence_predict_event_result'

    id = BigAutoField(db_column='grab_defence_predict_event_result_id', primary_key=True)
    event_id = models.TextField(db_index=True)
    event_ts = models.DateTimeField()
    event_type = models.TextField()
    event_features = JSONField(null=True, blank=True)
    rules = JSONField(null=True, blank=True)
    treatments = ArrayField(models.TextField(), null=True, blank=True)
    treatment_attributes = JSONField(null=True, blank=True)
    enriched_features = JSONField(null=True, blank=True)
    entity_status = models.TextField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {
        'event_features': [
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['phone_number']),
            (FraudPIIFieldTypeConst.EMAIL, ['email_address']),
        ],
        'enriched_features': [
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['phone_number_prefix_0_last_2'])
        ],
    }


# Deprecated as of ANTIFRAUD-492
class GrabDefenceEntity(FraudPIIMaskingModelMixin, TimeStampedModel):
    class Meta:
        db_table = 'grab_defence_entity'

    id = BigAutoField(db_column='grab_defence_entity_id', primary_key=True)
    customer = BigForeignKey(
        'julo.Customer',
        db_constraint=False,
        db_column='customer_id',
        null=True,
        blank=True,
    )
    checksum = models.TextField(db_index=True)
    entity_type = models.TextField()
    entity_id = models.TextField()
    attributes = JSONField()
    enriched_features = JSONField()

    FRAUD_PII_MASKING_FIELDS = {
        'attributes': [
            (FraudPIIFieldTypeConst.NAME, ['Name']),
            (FraudPIIFieldTypeConst.EMAIL, ['Email']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['PhoneNumber']),
        ]
    }

    def generate_checksum(self):
        """
        Generate the checksum and store it inside `checksum` field.
        Returns:
            str: The Checksum value
        """
        import pickle
        from hashlib import sha1
        fields = ['entity_type', 'entity_id', 'attributes', 'enriched_features']
        raw_data = {field: getattr(self, field) for field in fields if hasattr(self, field)}
        byte_data = pickle.dumps(raw_data)
        self.checksum = sha1(byte_data).hexdigest()
        return self.checksum


# Deprecated as of ANTIFRAUD-492
class GrabDefencePredictEventResultEntity(TimeStampedModel):
    class Meta:
        db_table = 'grab_defence_predict_event_result_entity'

    id = BigAutoField(db_column='grab_defence_predict_event_result_entity_id', primary_key=True)
    predict_event_result = BigForeignKey(
        GrabDefencePredictEventResult,
        db_column="grab_defence_predict_event_result_id",
        db_constraint=False
    )
    entity = BigForeignKey(
        GrabDefenceEntity,
        db_column='grab_defence_entity_id',
        db_constraint=False,
    )


class MonnaiInsightRequestManager(PIIVaultModelManager):
    pass


# moved to frauddb
class MonnaiInsightRequest(PIIVaultModel):
    PII_FIELDS = ['phone_number', 'email_address']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = BigAutoField(db_column='monnai_insight_request_id', primary_key=True)
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        db_constraint=False,
    )
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
    )
    action_type = models.TextField(null=True, blank=True)

    # an unique identifier for each request.
    transaction_id = models.TextField(null=True, blank=True)

    ip_address = models.TextField(null=True, blank=True)
    location_latitude = models.FloatField(null=True, blank=True)
    location_longitude = models.FloatField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)
    email_address = models.TextField(null=True, blank=True)

    # Response time in milliseconds
    response_time = models.PositiveIntegerField(null=True, blank=True)

    response_code = models.PositiveIntegerField(null=True, blank=True)
    error_type = models.TextField(null=True, blank=True)
    monnai_error_code = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)
    email_address_tokenized = models.TextField(blank=True, null=True)

    objects = MonnaiInsightRequestManager()

    class Meta:
        db_table = 'monnai_insight_request'


# moved to frauddb
class MonnaiInsightRawResult(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='monnai_insight_raw_result_id', primary_key=True)
    monnai_insight_request = BigOneToOneField(
        'fraud_score.MonnaiInsightRequest',
        models.DO_NOTHING,
        db_column='monnai_insight_request_id',
        related_name='raw_result',
        blank=True,
        null=True,
        db_constraint=False,
    )
    raw = models.TextField()

    FRAUD_PII_MASKING_FIELDS = {
        'raw': [
            (FraudPIIFieldTypeConst.EMAIL, ['data', 'email']),
            (FraudPIIFieldTypeConst.NAME, ['data', 'name']),
            (FraudPIIFieldTypeConst.EMAIL, ['meta', 'inputEmail']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'inputPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'cleansedPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['data', 'phone', 'basic', 'phoneNumber']),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'emailProvider', 'google', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'skype', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'viber', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'zalo', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'line', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'emailProvider', 'google', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'socialMedia', 'facebook', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'socialMedia', 'gravatar', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'messaging', 'skype', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'professional', 'linkedin', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'email', 'social', 'profiles', 'travel', 'airbnb', 'name'],
            ),
        ]
    }

    class Meta:
        db_table = 'monnai_insight_raw_result'


class TrustGuardApiRequest(FraudPIIMaskingModelMixin, TimeStampedModel):

    id = BigAutoField(db_column='trust_guard_api_request_id', primary_key=True)
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', db_constraint=False,
    )
    black_box = models.TextField()
    device_type = models.TextField(null=True, blank=True)
    raw_request = JSONField(default=dict, blank=True, null=True)

    FRAUD_PII_MASKING_FIELDS = {
        'raw_request': [
            (FraudPIIFieldTypeConst.NAME, ['profile', 'name']),
            (FraudPIIFieldTypeConst.EMAIL, ['profile', 'email']),
            (FraudPIIFieldTypeConst.KTP, ['profile', 'id', 'id_number']),
        ],
    }

    class Meta:
        db_table = 'trust_guard_api_request'


class TrustGuardApiResult(TimeStampedModel):
    RESULT_CHOICES = (
        ('decline', 'decline'),
        ('review', 'review'),
        ('accept', 'accept'),
    )

    id = BigAutoField(db_column='trust_guard_api_result_id', primary_key=True)
    trust_guard_api_request = BigForeignKey(
        TrustGuardApiRequest,
        models.DO_NOTHING,
        db_column='trust_guard_api_request_id',
        blank=False,
        null=False,
        db_constraint=False,
    )
    request_duration = models.DurationField(blank=True, null=True)
    code = models.IntegerField(blank=True, null=True)
    score = models.IntegerField(blank=True, null=True)
    result = models.CharField(
        'Decision result', choices=RESULT_CHOICES, max_length=10, blank=True, null=True
    )
    event_type = models.CharField(max_length=25, blank=True, null=True)
    sequence_id = models.CharField(max_length=100)

    class Meta:
        db_table = 'trust_guard_api_result'


class TrustGuardApiRawResult(TimeStampedModel):
    id = BigAutoField(db_column='trust_guard_api_raw_result_id', primary_key=True)
    trust_guard_api_request = BigForeignKey(
        TrustGuardApiRequest,
        models.DO_NOTHING,
        db_column='trust_guard_api_request_id',
        blank=False,
        null=False,
        db_constraint=False,
    )
    http_code = models.IntegerField()
    response_json = JSONField(default=dict, blank=False, null=False)

    class Meta:
        db_table = 'trust_guard_api_raw_result'


class FinscoreApiRequest(TimeStampedModel):
    id = BigAutoField(db_column='finscore_api_request_id', primary_key=True)
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', db_constraint=False,
    )
    device_id = models.TextField(null=True)

    class Meta:
        db_table = 'finscore_api_request'


class FinscoreApiResult(TimeStampedModel):
    id = BigAutoField(db_column='finscore_api_result_id', primary_key=True)
    finscore_api_request = BigForeignKey(
        FinscoreApiRequest,
        models.DO_NOTHING,
        db_column='finscore_api_request_id',
        blank=False,
        null=False,
        db_constraint=False,
    )
    request_duration = models.DurationField(blank=True, null=True)
    code = models.IntegerField(blank=True, null=True)
    reason_code = models.IntegerField(blank=True, null=True)
    value = models.FloatField(blank=True, null=True)

    class Meta:
        db_table = 'finscore_api_result'


class FinscoreApiRawResult(TimeStampedModel):
    id = BigAutoField(db_column='finscore_api_raw_result_id', primary_key=True)
    finscore_api_request = BigForeignKey(
        FinscoreApiRequest,
        models.DO_NOTHING,
        db_column='finscore_api_request_id',
        blank=False,
        null=False,
        db_constraint=False,
    )
    http_code = models.IntegerField()
    response_json = JSONField(default=dict, blank=False, null=False)

    class Meta:
        db_table = 'finscore_api_raw_result'


class JuicyScoreResult(FraudPIIMaskingModelMixin, TimeStampedModel):
    id = BigAutoField(db_column='juicy_score_result_id', primary_key=True)
    application_id = models.BigIntegerField()
    customer_id = models.BigIntegerField()
    session_id = models.TextField()
    http_status_code = models.IntegerField(null=True, blank=True)
    latency = models.FloatField(null=True, blank=True)
    raw_request = JSONField(null=True, blank=True)
    raw_response = JSONField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {'raw_request': [(FraudPIIFieldTypeConst.PHONE_NUMBER, ['phone'])]}

    class Meta:
        db_table = 'juicy_score_result'

    def mask_data_pre_save(self):
        super().mask_data_pre_save()

        """
        sometimes we got a raw response like
        `404 Client Error: Not Found for url: https://api...&phone=123456&`
        """
        if not self.raw_response:
            return
        if not isinstance(self.raw_response, str):
            return
        if not (self.raw_request and isinstance(self.raw_request, dict)):
            return
        phone = self.raw_request.get('phone')
        if not phone:
            return
        self.raw_response = re.sub('phone=([^&]*)', 'phone=' + phone, self.raw_response)


# moved to frauddb
class MonnaiPhoneBasicInsight(FraudPIIMaskingModelMixin, TimeStampedModel):
    monnai_phone_basic_insight_id = BigAutoField(
        db_column='monnai_phone_basic_insight_id', primary_key=True
    )
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
        null=True,
    )
    monnai_insight_request = BigOneToOneField(
        'fraud_score.MonnaiInsightRequest',
        models.DO_NOTHING,
        db_column='monnai_insight_request_id',
        related_name='phone_basic_insight',
        db_constraint=False,
    )
    phone_disposable = models.NullBooleanField(null=True, blank=True)
    active = models.NullBooleanField(null=True, blank=True)
    activation_date = models.DateTimeField(null=True, blank=True)
    active_since_x_days = models.PositiveIntegerField(null=True, blank=True)
    sim_type = models.TextField(null=True, blank=True)
    phone_number_age = models.PositiveIntegerField(null=True, blank=True)
    phone_number_age_description = models.TextField(null=True, blank=True)
    phone_tenure = models.PositiveIntegerField(null=True, blank=True)
    last_deactivated = models.DateTimeField(null=True, blank=True)
    is_spam = models.NullBooleanField(null=True, blank=True)
    raw_response = JSONField(null=True, blank=True)

    FRAUD_PII_MASKING_FIELDS = {
        'raw_response': [
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['data', 'phone', 'basic', 'phoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'inputPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'cleansedPhoneNumber']),
            (FraudPIIFieldTypeConst.EMAIL, ['data', 'email']),
            (FraudPIIFieldTypeConst.NAME, ['data', 'name']),
            (FraudPIIFieldTypeConst.EMAIL, ['meta', 'inputEmail']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'inputPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['meta', 'cleansedPhoneNumber']),
            (FraudPIIFieldTypeConst.PHONE_NUMBER, ['data', 'phone', 'basic', 'phoneNumber']),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'emailProvider', 'google', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'skype', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'viber', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'zalo', 'name'],
            ),
            (
                FraudPIIFieldTypeConst.NAME,
                ['data', 'phone', 'social', 'profiles', 'messaging', 'line', 'name'],
            ),
        ]
    }

    class Meta:
        db_table = 'monnai_phone_basic_insight'


# moved to frauddb
class MonnaiPhoneSocialInsight(FraudPIIMaskingModelMixin, TimeStampedModel):
    monnai_phone_social_insight_id = BigAutoField(
        db_column='monnai_phone_social_insight_id', primary_key=True
    )
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
        null=True,
    )
    monnai_insight_request = BigOneToOneField(
        'fraud_score.MonnaiInsightRequest',
        models.DO_NOTHING,
        db_column='monnai_insight_request_id',
        related_name='phone_social_insight',
        db_constraint=False,
    )
    registered_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_email_provider_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_ecommerce_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_social_media_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_professional_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_messaging_profiles = models.PositiveIntegerField(null=True, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)
    number_of_names_returned = models.IntegerField(null=True, blank=True)
    number_of_photos_returned = models.IntegerField(null=True, blank=True)
    messaging_telegram_registered = models.NullBooleanField(null=True, blank=True)
    messaging_whatsapp_registered = models.NullBooleanField(null=True, blank=True)
    messaging_viber_registered = models.NullBooleanField(null=True, blank=True)
    messaging_kakao_registered = models.NullBooleanField(null=True, blank=True)
    messaging_skype_registered = models.NullBooleanField(null=True, blank=True)
    messaging_ok_registered = models.NullBooleanField(null=True, blank=True)
    messaging_zalo_registered = models.NullBooleanField(null=True, blank=True)
    messaging_line_registered = models.NullBooleanField(null=True, blank=True)
    messaging_snapchat_registered = models.NullBooleanField(null=True, blank=True)
    email_provider_google_registered = models.NullBooleanField(null=True, blank=True)
    social_media_facebook_registered = models.NullBooleanField(null=True, blank=True)
    social_media_twitter_registered = models.NullBooleanField(null=True, blank=True)
    social_media_instagram_registered = models.NullBooleanField(null=True, blank=True)
    raw_response = JSONField()

    FRAUD_PII_MASKING_FIELDS = {
        'raw_response': [
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'emailProvider', 'google', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'messaging', 'skype', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'messaging', 'viber', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'messaging', 'zalo', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'messaging', 'line', 'name']),
        ]
    }

    class Meta:
        db_table = 'monnai_phone_social_insight'


# moved to frauddb
class MonnaiEmailBasicInsight(TimeStampedModel):
    monnai_email_basic_insight_id = BigAutoField(
        db_column='monnai_email_basic_insight_id', primary_key=True
    )
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
        null=True,
    )
    monnai_insight_request = BigOneToOneField(
        'fraud_score.MonnaiInsightRequest',
        models.DO_NOTHING,
        db_column='monnai_insight_request_id',
        related_name='email_basic_insight',
        db_constraint=False,
    )

    deliverable = models.NullBooleanField(null=True, blank=True)
    domain_name = models.CharField(max_length=255, null=True, blank=True)
    tld = models.CharField(max_length=10, null=True, blank=True)
    creation_time = models.DateTimeField(null=True, blank=True)
    update_time = models.DateTimeField(null=True, blank=True)
    expiry_time = models.DateTimeField(null=True, blank=True)
    registered = models.NullBooleanField(null=True, blank=True)
    company_name = models.CharField(max_length=255, null=True, blank=True)
    registrar_name = models.CharField(max_length=255, null=True, blank=True)
    disposable = models.NullBooleanField(null=True, blank=True)
    free_provider = models.NullBooleanField(null=True, blank=True)
    dmarc_compliance = models.NullBooleanField(null=True, blank=True)
    spf_strict = models.NullBooleanField(null=True, blank=True)
    suspicious_tld = models.NullBooleanField(null=True, blank=True)
    website_exists = models.NullBooleanField(null=True, blank=True)
    accept_all = models.NullBooleanField(null=True, blank=True)
    custom = models.NullBooleanField(null=True, blank=True)
    is_breached = models.NullBooleanField(null=True, blank=True)
    breaches = JSONField(null=True, blank=True, verbose_name="Breach Details")
    no_of_breaches = models.IntegerField(null=True, blank=True)
    first_breach = models.DateField(null=True, blank=True)
    last_breach = models.DateField(null=True, blank=True)
    raw_response = JSONField()

    class Meta:
        db_table = 'monnai_email_basic_insight'


# moved to frauddb
class MonnaiEmailSocialInsight(FraudPIIMaskingModelMixin, TimeStampedModel):
    monnai_email_social_insight_id = BigAutoField(primary_key=True)
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_constraint=False,
        null=True,
    )
    monnai_insight_request = BigOneToOneField(
        'fraud_score.MonnaiInsightRequest',
        models.DO_NOTHING,
        related_name='email_social_insight',
        db_constraint=False,
    )
    registered_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_consumer_electronics_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_email_provider_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_ecommerce_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_social_media_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_messaging_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_professional_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_entertainment_profiles = models.PositiveIntegerField(null=True, blank=True)
    registered_travel_profiles = models.PositiveIntegerField(null=True, blank=True)
    age_on_social = models.FloatField(null=True, blank=True)
    number_of_names_returned = models.PositiveIntegerField(null=True, blank=True)
    number_of_photos_returned = models.PositiveIntegerField(null=True, blank=True)
    facebook_registered = models.NullBooleanField(null=True, blank=True)
    instagram_registered = models.NullBooleanField(null=True, blank=True)
    twitter_registered = models.NullBooleanField(null=True, blank=True)
    quora_registered = models.NullBooleanField(null=True, blank=True)
    github_registered = models.NullBooleanField(null=True, blank=True)
    linkedin_registered = models.NullBooleanField(null=True, blank=True)
    linkedin_url = models.URLField(null=True, blank=True)
    linkedin_name = models.CharField(max_length=255, null=True, blank=True)
    linkedin_company = models.CharField(max_length=255, null=True, blank=True)
    raw_response = JSONField()

    FRAUD_PII_MASKING_FIELDS = {
        'raw_response': [
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'emailProvider', 'google', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'socialMedia', 'facebook', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'socialMedia', 'gravatar', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'messaging', 'skype', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'professional', 'linkedin', 'name']),
            (FraudPIIFieldTypeConst.NAME, ['profiles', 'travel', 'airbnb', 'name']),
            (FraudPIIFieldTypeConst.EMAIL, ['meta', 'inputEmail']),
        ]
    }

    class Meta:
        db_table = 'monnai_email_social_insight'


class TelcoLocationResult(TimeStampedModel):
    id = BigAutoField(db_column='fraud_telco_location_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    loan_id = models.BigIntegerField(db_index=True, blank=True, null=True)
    vendor = models.CharField(max_length=100)
    tsp = models.CharField(max_length=100)
    cell_tower_ranking = models.IntegerField(blank=True, null=True)
    cell_tower_density = models.CharField(max_length=100, blank=True, null=True)
    location_type = models.CharField(max_length=100, blank=True, null=True)
    dist_min = models.FloatField(null=True, blank=True)
    dist_max = models.FloatField(null=True, blank=True)
    input_lat = models.CharField(max_length=100, blank=True, null=True)
    input_long = models.CharField(max_length=100, blank=True, null=True)
    location_confidence = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'fraud_telco_location_result'


class MaidResult(TimeStampedModel):
    id = BigAutoField(db_column='monnai_maid_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    loan_id = models.BigIntegerField(db_index=True, blank=True, null=True)
    day_lat = models.FloatField(null=True, blank=True)
    day_long = models.FloatField(null=True, blank=True)
    night_lat = models.FloatField(null=True, blank=True)
    night_long = models.FloatField(null=True, blank=True)
    most_seen_lat = models.FloatField(null=True, blank=True)
    most_seen_long = models.FloatField(null=True, blank=True)
    input_lat = models.CharField(max_length=100, blank=True, null=True)
    input_long = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'monnai_maid_result'
