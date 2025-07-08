from cuser.fields import CurrentUserField
from django.contrib.postgres.fields import JSONField
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import (
    Manager,
    QuerySet,
)

from juloserver.fraud_security.constants import (
    FraudFlagSource,
    FraudFlagTrigger,
    FraudFlagType,
)
from juloserver.julo.models import (
    Application,
    Customer,
    PIIType,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.julocore.data.models import (
    CustomQuerySet,
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from django.contrib.auth.models import User
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class SecurityWhitelist(TimeStampedModel):
    id = BigAutoField(db_column='security_whitelist_id', primary_key=True)
    customer = BigForeignKey(to=Customer, db_column='customer_id')
    object_type = models.TextField()
    object_id = models.TextField(db_index=True)
    reason = models.TextField()
    added_by = CurrentUserField(db_column='added_by_user_id')
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta:
        db_table = 'security_whitelist'

    def __repr__(self):
        return f"{__class__}(id={self.id},customer_id={self.customer_id})"


class FraudFlagQuerySet(CustomQuerySet):
    def suspicious_device_change(self, android_id: str) -> QuerySet:
        return self.filter(
            fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
            flag_source_type=FraudFlagSource.ANDROID,
            trigger=FraudFlagTrigger.LOGIN_SUCCESS,
            flag_source_id=android_id,
        )

    def blocked_loan_device_change(self) -> QuerySet:
        return self.filter(
            fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
            flag_source_type=FraudFlagSource.LOAN,
            trigger=FraudFlagTrigger.LOAN_CREATION,
        )


class FraudFlag(TimeStampedModel):
    """
    This model/table is historical for fraud flagging to any resource/model.
    Don't use table for any flag that can be edited for removed.
    """

    id = BigAutoField(db_column='fraud_flag_id', primary_key=True)

    # See FraudFlagType for the list.
    fraud_type = models.TextField(db_index=True)

    # See FraudFlagSource for the list.
    flag_source_type = models.TextField()

    flag_source_id = models.TextField(db_index=True)

    # See FraudFlagTrigger for the list.
    trigger = models.TextField()

    extra = JSONField(blank=True, null=True)

    # This is represent the owner of the source.
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        db_constraint=False,
        null=True,
        blank=True,
    )

    objects = Manager.from_queryset(FraudFlagQuerySet)()

    class Meta:
        db_table = 'fraud_flag'

    def __repr__(self):
        return f"{__class__}(id={self.id},fraud_type={self.fraud_type})"


class FraudVelocityModelResultsCheck(TimeStampedModel):
    id = BigAutoField(db_column='fraud_velocity_model_results_check_id', primary_key=True)
    is_fraud = models.BooleanField()
    similar_selfie_bg = models.NullBooleanField()
    guided_selfie = models.NullBooleanField()
    active_liveness_match = models.NullBooleanField()
    fraudulent_payslip = models.NullBooleanField()
    fraudulent_ktp = models.NullBooleanField()
    invalid_phone_1 = models.NullBooleanField()
    invalid_phone_2 = models.NullBooleanField()
    invalid_kin_phone = models.NullBooleanField()
    invalid_close_kin_phone = models.NullBooleanField()
    invalid_spouse_phone = models.NullBooleanField()
    invalid_company_phone = models.NullBooleanField()
    sus_acc_from_phone_2 = models.NullBooleanField()
    sus_acc_from_kin_phone = models.NullBooleanField()
    sus_acc_from_close_kin_phone = models.NullBooleanField()
    sus_acc_from_spouse_phone = models.NullBooleanField()
    address_suspicious = models.NullBooleanField()
    job_detail_sus = models.NullBooleanField()
    monthly_income_sus = models.NullBooleanField()
    monthly_expense_sus = models.NullBooleanField()
    loan_purpose_sus = models.NullBooleanField()
    registration_time_taken_sus = models.NullBooleanField()
    remarks = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'fraud_velocity_model_results_check'


class FraudVerificationResults(TimeStampedModel):
    id = BigAutoField(db_column='fraud_verification_result_id', primary_key=True)
    geohash = models.TextField(blank=True, null=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    fraud_velocity_model_results_check = BigForeignKey(
        FraudVelocityModelResultsCheck,
        models.DO_NOTHING,
        db_column='fraud_velocity_model_results_check_id',
        blank=True,
        null=True,
    )
    bucket = models.TextField()
    android_id = models.TextField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    radius = models.FloatField(blank=True, null=True)
    previous_status_code = models.IntegerField(null=True, blank=True)
    next_status_code = models.IntegerField(null=True, blank=True)
    agent_user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='agent_user_id',
        blank=True,
        null=True,
        related_name='fraud_verification_results',
    )
    reason = models.TextField()

    class Meta:
        db_table = 'fraud_verification_results'


class FraudVelocityModelGeohash(TimeStampedModel):
    id = BigAutoField(db_column='fraud_velocity_model_geohash_id', primary_key=True)
    geohash = models.TextField(null=True, blank=True, db_index=True)
    risky_date = models.DateField(null=True, blank=True, db_index=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    x105_date = models.DateField(null=True, blank=True)
    x105_complete_duration = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'fraud_velocity_model_geohash'


class FraudVelocityModelGeohashBucket(TimeStampedModel):
    id = BigAutoField(db_column='fraud_velocity_model_geohash_bucket_id', primary_key=True)
    geohash = models.TextField()
    fraud_velocity_model_results_check = BigForeignKey(
        FraudVelocityModelResultsCheck,
        models.DO_NOTHING,
        db_column='fraud_velocity_model_results_check_id',
        blank=True,
        null=True,
    )
    agent_user = models.ForeignKey(
        User, on_delete=models.DO_NOTHING, db_column='agent_user_id', blank=True, null=True
    )

    class Meta:
        db_table = 'fraud_velocity_model_geohash_bucket'

    @property
    def is_verified(self):
        return self.fraud_velocity_model_results_check_id is not None


class FraudApplicationBucket(TimeStampedModel):
    id = BigAutoField(db_column='fraud_application_bucket_id', primary_key=True)
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_index=True,
        db_constraint=False,
    )
    type = models.TextField(db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'fraud_application_bucket'


class FraudBlacklistedCompanyManager(GetInstanceMixin, JuloModelManager):
    def is_blacklisted(self, company_name: str) -> bool:
        """
        Return True if the company_name is found in the blacklisted table.
        The filter is case insensitive.
        Args:
            company_name (str): The company name text

        Returns:
            bool
        """
        return self.get_queryset().filter(company_name__iexact=company_name).exists()


class FraudBlacklistedCompany(TimeStampedModel):
    id = models.AutoField(db_column='fraud_blacklisted_company_id', primary_key=True)
    company_name = models.TextField(db_index=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    objects = FraudBlacklistedCompanyManager()

    class Meta:
        managed = False
        db_table = 'fraud_blacklisted_company'
        verbose_name_plural = 'Fraud Blacklisted Companies'


class FraudHighRiskAsn(TimeStampedModel):
    id = models.AutoField(db_column='fraud_high_risk_asn_id', primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        managed = False
        db_table = 'fraud_high_risk_asn'
        verbose_name_plural = 'High Risk ASN'

    def __str__(self):
        return self.name


class FraudBlacklistedASN(TimeStampedModel):
    id = models.AutoField(db_column="fraud_blacklisted_asn_id", primary_key=True)
    asn_data = models.TextField(unique=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        managed = False
        db_table = 'fraud_blacklisted_asn'


class FraudBlacklistedPostalCode(TimeStampedModel):
    id = models.AutoField(db_column="fraud_blacklisted_postal_code_id", primary_key=True)
    postal_code = models.CharField(max_length=5, unique=True, db_index=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        managed = False
        db_table = 'fraud_blacklisted_postal_code'


class FraudBlacklistedGeohash5(TimeStampedModel):
    id = models.AutoField(db_column='fraud_blacklisted_geohash5_id', primary_key=True)
    geohash5 = models.CharField(max_length=5, db_index=True, unique=True)
    updated_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        managed = False
        db_table = 'fraud_blacklisted_geohash5'

    def __str__(self):
        return self.geohash5


class FraudSwiftLimitDrainerAccountManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudBlacklistedEmergencyContactManager(PIIVaultModelManager):
    pass


# Deprecated as of ANTIFRAUD-492
class FraudGdDeviceSharingAccountManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudTelcoMaidTemporaryBlockManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudBlockAccountManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudSwiftLimitDrainerAccount(TimeStampedModel):
    """
    High churn model for transient data related to Swift Limit Drainer Feature.
    We use this table because the querying process for retrieving the account for swift limit
        is complex and can be heavy.
    """

    id = models.AutoField(db_column='fraud_swift_limit_drainer_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True
    )

    objects = FraudSwiftLimitDrainerAccountManager()

    class Meta(object):
        db_table = 'fraud_swift_limit_drainer_account'


# Deprecated as of ANTIFRAUD-492
class FraudGdDeviceSharingAccount(TimeStampedModel):

    id = models.AutoField(db_column='fraud_gd_device_sharing_account_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True
    )

    objects = FraudGdDeviceSharingAccountManager()

    class Meta(object):
        db_table = 'fraud_gd_device_sharing_account'


class FraudTelcoMaidTemporaryBlock(TimeStampedModel):

    id = models.AutoField(db_column='fraud_telco_maid_temporary_block_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True
    )

    objects = FraudTelcoMaidTemporaryBlockManager()

    class Meta(object):
        db_table = 'fraud_telco_maid_temporary_block'


class FraudAppealTemporaryBlock(TimeStampedModel):

    id = models.AutoField(db_column='fraud_appeal_temporary_block_id', primary_key=True)
    account_id = models.IntegerField(db_column='account_id', db_index=True, unique=True)

    class Meta(object):
        db_table = 'fraud_appeal_temporary_block'
        verbose_name_plural = 'Fraud Appeal Temporary Block'


class FraudBlacklistedEmergencyContact(PIIVaultModel):
    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='fraud_blacklisted_emergency_contacts_id', primary_key=True)
    phone_number = models.CharField(max_length=20, unique=True)
    reason = models.TextField()
    date_added_ts = models.DateTimeField(auto_now_add=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)

    objects = FraudBlacklistedEmergencyContactManager()

    class Meta:
        db_table = "fraud_blacklisted_emergency_contacts"


class BankNameVelocityThresholdHistory(TimeStampedModel):
    id = models.AutoField(db_column="bank_name_velocity_threshold_history_id", primary_key=True)
    threshold_date = models.DateTimeField(blank=True, null=True)
    threshold = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = 'bank_name_velocity_threshold_history'


class FraudBlockAccount(TimeStampedModel):
    id = models.AutoField(db_column='fraud_block_account_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', null=True, blank=True
    )
    feature_name = models.TextField(blank=True, null=True)
    is_appeal = models.BooleanField(default=False)
    is_confirmed_fraud = models.BooleanField(default=False)
    is_block = models.BooleanField(default=False)
    is_need_action = models.BooleanField(default=True)
    is_verified_by_agent = models.BooleanField(default=False)

    objects = FraudBlockAccountManager()

    class Meta(object):
        db_table = 'fraud_block_account'


class FraudBlacklistedNIKManager(GetInstanceMixin, JuloModelManager):
    pass


class FraudBlacklistedNIK(PIIVaultModel):
    PII_FIELDS = ['nik']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='fraud_blacklisted_nik_id', primary_key=True)
    nik = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='NIK has to be 16 numeric digits')
        ], unique=True)
    nik_tokenized = models.TextField(blank=True, null=True)

    objects = FraudBlacklistedNIKManager()

    class Meta:
        db_table = 'fraud_blacklisted_nik'
