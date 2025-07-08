from __future__ import unicode_literals

from builtins import (
    object,
    str,
)

from django.contrib.postgres.fields import (
    ArrayField,
    JSONField,
)
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.fields import NullBooleanField
from django.forms.models import model_to_dict
from django.utils import timezone

from juloserver.julo.constants import FeatureNameConst
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class ApplicationPathTag(TimeStampedModel):

    id = models.AutoField(db_column='application_path_tag_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    application_path_tag_status = models.ForeignKey(
        'ApplicationPathTagStatus', models.DO_NOTHING, db_column='application_path_tag_status_id'
    )

    class Meta(object):
        db_table = 'application_path_tag'
        managed = False


class ApplicationPathTagHistory(TimeStampedModel):

    id = BigAutoField(db_column='application_path_tag_history_id', primary_key=True)
    application_path_tag = BigForeignKey(
        'ApplicationPathTag',
        models.DO_NOTHING,
        db_column='application_path_tag_id',
        blank=True,
        null=True,
    )
    application_status_code = models.IntegerField()
    tag_status = models.IntegerField()

    class Meta(object):
        db_table = 'application_path_tag_history'
        managed = False


class ApplicationPathTagStatus(TimeStampedModel):

    id = models.AutoField(db_column='application_path_tag_status_id', primary_key=True)
    application_tag = models.CharField(max_length=200)
    status = models.IntegerField()
    definition = models.CharField(max_length=200)

    class Meta(object):
        db_table = 'application_path_tag_status'
        verbose_name_plural = 'Application Path Tag Status'
        managed = False

    @classmethod
    def get_ids_from_tag(cls, application_tag):
        return cls.objects.filter(application_tag=application_tag).values_list('id', flat=True)


class ApplicationTag(TimeStampedModel):

    id = models.AutoField(db_column='application_tag_id', primary_key=True)
    application_tag = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'application_tag'
        managed = False


class VoiceRecordingThreshold(TimeStampedModel):
    DEFAULT_THRESHOLD = {'voice_recording_loan_amount_threshold': 100000}
    id = models.AutoField(db_column='voice_recording_threshold_id', primary_key=True)
    parameters = JSONField(default=DEFAULT_THRESHOLD)
    transaction_method = models.OneToOneField(
        'payment_point.TransactionMethod', models.DO_NOTHING, db_column='transaction_method_id'
    )

    class Meta(object):
        db_table = 'voice_recording_threshold'

    def __str__(self):
        return str(self.transaction_method)


class DigitalSignatureThreshold(TimeStampedModel):
    DEFAULT_THRESHOLD = {'digital_signature_loan_amount_threshold': 100000}
    id = models.AutoField(db_column='digital_signature_threshold_id', primary_key=True)
    parameters = JSONField(default=DEFAULT_THRESHOLD)
    transaction_method = models.OneToOneField(
        'payment_point.TransactionMethod', models.DO_NOTHING, db_column='transaction_method_id'
    )

    class Meta(object):
        db_table = 'digital_signature_threshold'

    def __str__(self):
        return str(self.transaction_method)


class ReverseGeolocation(TimeStampedModel):
    id = models.AutoField(db_column='reverse_geolocation_id', primary_key=True)

    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    customer = BigForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')

    latitude = models.FloatField()
    longitude = models.FloatField()
    full_address = models.CharField(max_length=500)
    response = JSONField(default=None, blank=True, null=True)

    device_geolocation = models.ForeignKey(
        'julo.DeviceGeolocation',
        models.DO_NOTHING,
        db_column='device_geolocation_id',
        null=True,
        blank=True,
    )
    address_geolocation = models.ForeignKey(
        'julo.AddressGeolocation',
        models.DO_NOTHING,
        db_column='address_geolocation_id',
        null=True,
        blank=True,
    )

    distance_km = models.FloatField()

    class Meta(object):
        db_table = 'reverse_geolocation'


class ApplicationRiskyDecision(TimeStampedModel):
    id = models.AutoField(db_column='decision_id', primary_key=True)
    decision_name = models.CharField(max_length=200)

    class Meta(object):
        db_table = 'application_risky_decision'


class ApplicationRiskyCheckManager(GetInstanceMixin, JuloModelManager):
    pass


class ApplicationRiskyCheck(TimeStampedModel):
    id = models.AutoField(db_column='application_risky_check_id', primary_key=True)
    application = models.OneToOneField(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    device = models.ForeignKey(
        'julo.Device', models.DO_NOTHING, db_column='device_id', null=True, blank=True
    )
    is_rooted_device = NullBooleanField()
    is_address_suspicious = NullBooleanField()
    is_special_event = NullBooleanField()
    is_bpjs_name_suspicious = NullBooleanField()
    is_bank_name_suspicious = NullBooleanField()
    is_bpjs_nik_suspicious = NullBooleanField()
    is_sus_ektp_generator_app = NullBooleanField()
    decision = models.ForeignKey(
        'ApplicationRiskyDecision',
        models.DO_NOTHING,
        db_column='decision_id',
        null=True,
        blank=True,
    )
    is_sus_camera_app = NullBooleanField()
    is_vpn_detected = NullBooleanField()
    is_fh_detected = NullBooleanField()
    is_similar_face_suspicious = NullBooleanField()
    is_sus_app_detected = NullBooleanField()
    sus_app_detected_list = ArrayField(models.CharField(max_length=255), default=None, null=True)
    is_dukcapil_not_match = NullBooleanField()
    is_mycroft_holdout = NullBooleanField()
    is_fraud_face_suspicious = NullBooleanField()
    is_high_risk_asn_mycroft = NullBooleanField(default=None)
    is_early_warning_leverage_bank = NullBooleanField(default=None)
    is_window_dressing_leverage_bank = NullBooleanField(default=None)

    objects = ApplicationRiskyCheckManager()

    class Meta(object):
        db_table = 'application_risky_check'

    def clean_check_name(self, name):
        result = name.replace('is_', '').replace('_', ' ').upper()
        return result

    def get_fraud_list(self):
        from juloserver.julo.constants import ExperimentConst
        from juloserver.julo.models import ExperimentSetting

        model_dict = model_to_dict(self)
        del model_dict['is_mycroft_holdout']
        result = [
            self.clean_check_name(key) for (key, value) in model_dict.items() if value is True
        ]
        if self.is_fh_detected:
            today = timezone.localtime(timezone.now()).date()
            fh_reverse_experiment = (
                ExperimentSetting.objects.filter(
                    code=ExperimentConst.FRAUD_HOTSPOT_REVERSE_EXPERIMENT, is_active=True
                )
                .filter(
                    (Q(start_date__date__lte=today) & Q(end_date__date__gte=today))
                    | Q(is_permanent=True)
                )
                .last()
            )
            if fh_reverse_experiment:
                in_experiment = self.application.experimentgroup_set.filter(
                    experiment_setting=fh_reverse_experiment, group='experiment'
                ).exists()
                if in_experiment:
                    result.remove(self.clean_check_name('is_fh_detected'))
        return result


class SuspiciousFraudApps(TimeStampedModel):
    id = models.AutoField(db_column='suspicious_fraud_app_id', primary_key=True)
    package_names = ArrayField(models.CharField(max_length=250), default=list)
    transaction_risky_check = models.CharField(max_length=250)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        managed = False
        db_table = 'suspicious_fraud_apps'

    def __str__(self):
        return str(self.transaction_risky_check)


class EmulatorCheck(TimeStampedModel):
    id = models.AutoField(db_column='emulator_check_id', primary_key=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    service_provider = models.CharField(max_length=250, blank=True)
    timestamp_ms = models.DateTimeField(null=True, blank=True)
    nonce = models.TextField(null=True, blank=True)
    apk_package_name = models.TextField(null=True, blank=True)
    apk_certificate_digest_sha_256 = models.TextField(null=True, blank=True)
    cts_profile_match = NullBooleanField()
    basic_integrity = NullBooleanField()
    evaluation_type = models.CharField(max_length=250, blank=True, null=True)
    advice = models.TextField(null=True, blank=True)
    error_msg = models.TextField(null=True, blank=True)
    error_occurrences = ArrayField(models.TextField(), blank=True, null=True, default=None)
    app_recognition_verdict = models.TextField(null=True, blank=True)
    device_recognition_verdict = JSONField(null=True, blank=True)
    app_licensing_verdict = models.TextField(null=True, blank=True)
    app_access_risk_verdict = JSONField(null=True, blank=True)
    play_protect_verdict = models.TextField(null=True, blank=True)
    device_activity_level = models.TextField(null=True, blank=True)
    original_response = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = 'emulator_check'

    def __str__(self):
        return str(self.application.id)


class EmulatorCheckEligibilityLog(TimeStampedModel):
    id = BigAutoField(db_column='emulator_check_eligibility_log_id', primary_key=True)
    application = BigForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', db_constraint=False
    )
    is_eligible = models.NullBooleanField()
    application_status = models.IntegerField()
    passed_binary_checks = models.NullBooleanField()
    remarks = models.TextField()

    class Meta(object):
        db_table = 'emulator_check_eligibility_log'

    def __str__(self):
        return str(self.application.id)


class EmulatorCheckIOS(TimeStampedModel):
    id = BigAutoField(db_column='emulator_check_ios_id', primary_key=True)
    application_id = models.BigIntegerField()
    is_emulator = models.BooleanField()
    brand = models.CharField(max_length=100, blank=True, null=True)
    os_name = models.CharField(max_length=100, blank=True, null=True)
    os_version = models.CharField(max_length=100, blank=True, null=True)
    cpu_arch = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'emulator_check_ios'


class ShopeeScoring(TimeStampedModel):
    id = models.AutoField(db_column='shopee_scoring_id', primary_key=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    code = models.CharField(max_length=200, blank=True, null=True)
    msg = models.CharField(max_length=200, blank=True, null=True)
    sign = models.TextField(blank=True, null=True)
    sign_type = models.CharField(max_length=200, blank=True, null=True)
    encrypt = models.CharField(max_length=200, blank=True, null=True)
    encrypt_type = models.CharField(max_length=200, blank=True, null=True)
    flow_no = models.CharField(max_length=200, blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    biz_code = models.CharField(max_length=200, blank=True, null=True)
    biz_msg = models.CharField(max_length=200, blank=True, null=True)
    biz_data = JSONField(max_length=200, blank=True, null=True)
    latency = models.FloatField(null=True, blank=True)
    is_passed = models.NullBooleanField(null=True, blank=True)
    log = JSONField(blank=True, null=True)
    passed_reason = models.CharField(max_length=255, null=True, blank=True)
    type = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'shopee_scoring'


class ShopeeScoringFailedLog(TimeStampedModel):
    id = models.AutoField(db_column='shopee_scoring_failed_log_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    method = models.CharField(max_length=50)
    request = models.TextField()
    response = models.TextField()
    status_code = models.IntegerField(default=500)
    latency = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = 'shopee_scoring_failed_log'


class IziDataScoring(TimeStampedModel):
    id = models.AutoField(db_column='izidata_credit_score_id', primary_key=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    raw_response = models.CharField(max_length=255)
    credit_score = models.IntegerField(blank=True, null=True)
    status = models.IntegerField()
    status_message = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = 'izidata_credit_score'


class MycroftThreshold(TimeStampedModel):
    LOGICAL_OPERATORS = (
        ('<=', '<='),
        ('<', '<'),
        ('>=', '>='),
        ('>', '>'),
    )

    id = models.AutoField(db_column='mycroft_threshold_id', primary_key=True)
    score = models.FloatField()
    logical_operator = models.CharField(max_length=2, choices=LOGICAL_OPERATORS)
    is_active = models.BooleanField()

    class Meta(object):
        db_table = 'mycroft_threshold'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._initial_values = {
            field.name: getattr(self, field.name) for field in self._meta.fields
        }

    def clean(self):
        from juloserver.julo.models import FeatureSetting

        super().clean()
        if not 0 <= self.score <= 1:
            raise ValidationError('Score cannot be less than 0 or more than 1.')

        if self.id and (
            self.score != self._initial_values.get('score')
            or self.logical_operator != self._initial_values.get('logical_operator')
        ):
            if MycroftResult.objects.filter(mycroft_threshold=self).exists():
                raise ValidationError(
                    'Not allowed to edit as this threshold is already used by MycroftResult '
                    'record(s).'
                )

        if (
            not self.is_active
            and FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
            ).exists()
        ):
            other_active_thresholds = MycroftThreshold.objects.filter(is_active=True).exclude(
                id=self.id
            )
            if not other_active_thresholds.exists():
                raise ValidationError(
                    'Cannot deactivate MycroftThreshold when FeatureSetting is active and no other '
                    'active MycroftThreshold exists.'
                )

    def save(self, *args, **kwargs):
        self.clean()
        if self.is_active:
            # If saving or updating an active MycroftThreshold, deactivate other active thresholds
            MycroftThreshold.objects.filter(is_active=True).exclude(id=self.id).update(
                is_active=False
            )

        super().save(*args, **kwargs)


class MycroftResult(TimeStampedModel):
    id = models.AutoField(db_column='mycroft_result_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    customer = models.ForeignKey('julo.Customer', models.DO_NOTHING, db_column='customer_id')
    mycroft_threshold = models.ForeignKey(
        'application_flow.MycroftThreshold', models.DO_NOTHING, db_column='mycroft_threshold_id'
    )

    score = models.FloatField()
    result = models.BooleanField()

    class Meta(object):
        db_table = 'mycroft_result'


class ApplicationNameBankValidationChange(TimeStampedModel):
    id = models.AutoField(db_column='application_name_bank_validation_change_id', primary_key=True)
    application_id = models.BigIntegerField(blank=False, null=False, db_column='application_id')
    old_name_bank_validation_id = models.BigIntegerField()
    new_name_bank_validation_id = models.BigIntegerField()

    class Meta(object):
        db_table = 'application_name_bank_validation_change'
        managed = False


class LevenshteinLogManager(GetInstanceMixin, JuloModelManager):
    pass


class LevenshteinLog(TimeStampedModel):
    id = models.AutoField(db_column="levenshtein_log_id", primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    start_sync_at = models.DateTimeField()
    start_async_at = models.DateTimeField(blank=True, null=True)
    end_sync_at = models.DateTimeField(blank=True, null=True)
    end_async_at = models.DateTimeField(blank=True, null=True)
    is_passed = models.NullBooleanField()
    end_reason = models.CharField(max_length=200, blank=True, null=True)
    calculation = JSONField(default={})

    objects = LevenshteinLogManager()

    class Meta(object):
        db_table = 'levenshtein_log'


class BankStatementProviderLog(TimeStampedModel):
    id = BigAutoField(db_column="bank_statement_provider_log_id", primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    provider = models.CharField(max_length=50)
    kind = models.CharField(max_length=100, blank=True, null=True)
    log = models.TextField()
    clicked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "bank_statement_provider_log"
        managed = False


class BpjsAlertLog(TimeStampedModel):
    id = BigAutoField(db_column="bpjs_alert_log_id", primary_key=True)
    customer_id = models.BigIntegerField(db_index=True)
    provider = models.CharField(max_length=50)
    log = models.TextField()

    class Meta:
        db_table = "bpjs_alert_log"
        managed = False


class ClikScoringResult(TimeStampedModel):
    id = BigAutoField(db_column="clik_scoring_result_id", primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    enquiry_type = models.CharField(max_length=50)
    score_raw = models.TextField()
    total_overdue_amount = models.TextField()
    reporting_providers_number = models.TextField()
    score_range = models.TextField()
    score_message_desc = models.TextField()
    type = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "clik_scoring_result"


class PerfiosInstitutionLookup(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='perfios_institution_lookup_id')
    perfios_institution_id = models.IntegerField(null=False)
    perfios_institution_name = models.CharField(max_length=200, null=False, blank=False)
    bank_name = models.CharField(max_length=200, null=False, blank=False, db_index=True)

    class Meta:
        db_table = "perfios_institution_lookup"
        managed = False


class TelcoScoringResult(TimeStampedModel):
    id = BigAutoField(db_column="telco_scoring_result_id", primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    scoring_type = models.PositiveSmallIntegerField(null=True)
    score = models.TextField(null=True, blank=True)
    type = models.TextField()
    raw_response = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "telco_scoring_result"
        managed = False


class HsfbpIncomeVerification(TimeStampedModel):
    id = BigAutoField(db_column="hsfbp_income_verification_id", primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    stated_income = models.BigIntegerField(blank=True, null=True)
    verified_income = models.BigIntegerField(blank=True, null=True)
    expired_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "hsfbp_income_verification"
        managed = False
