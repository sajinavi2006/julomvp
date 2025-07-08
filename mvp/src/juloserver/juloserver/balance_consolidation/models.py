from django.core.validators import RegexValidator
from django.db import models
from django.conf import settings
from model_utils import FieldTracker

from juloserver.julo.utils import get_oss_presigned_url

from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.julo.models import (
    TimeStampedModel,
    Customer,
    Agent,
    ascii_validator,
    Loan,
    Document,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigOneToOneField
from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager
from django.contrib.postgres.fields import JSONField
from juloserver.pii_vault.models import PIIVaultModelManager, PIIVaultModel
from juloserver.pii_vault.constants import PIIType


class FintechManager(GetInstanceMixin, JuloModelManager):
    pass


class Fintech(TimeStampedModel):
    id = models.AutoField(db_column='fintech_id', primary_key=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = FintechManager()

    class Meta(object):
        db_table = 'fintech'


class BalanceConsolidationManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class BalanceConsolidation(PIIVaultModel):
    PII_FIELDS = ['email', 'fullname', 'name_in_bank']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'utilization_pii_vault'

    id = models.AutoField(db_column='balance_consolidation_id', primary_key=True)
    email = models.EmailField()
    fullname = models.CharField(max_length=100, validators=[ascii_validator])
    customer = BigForeignKey(Customer, on_delete=models.DO_NOTHING, db_column='customer_id')
    fintech = models.ForeignKey(Fintech, models.DO_NOTHING, db_column='fintech_id')
    loan_agreement_number = models.CharField(
        max_length=255, validators=[ascii_validator], blank=True, null=True
    )
    loan_principal_amount = models.BigIntegerField()
    loan_outstanding_amount = models.BigIntegerField()
    disbursement_date = models.DateField()
    due_date = models.DateField()
    bank_name = models.CharField(max_length=255)
    bank_account_number = models.CharField(
        max_length=100,
        validators=[
            RegexValidator(regex='^[0-9]+$', message='Virtual account has to be numeric digits')
        ],
    )
    name_in_bank = models.CharField(max_length=100)
    loan_agreement_document = models.ForeignKey(
        Document, models.DO_NOTHING, db_column='document_id', blank=True, null=True
    )
    loan_duration = models.IntegerField(blank=True, null=True)
    signature_image = models.ForeignKey('julo.Image', models.DO_NOTHING, blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    fullname_tokenized = models.TextField(blank=True, null=True)
    name_in_bank_tokenized = models.TextField(blank=True, null=True)

    objects = BalanceConsolidationManager()

    class Meta(object):
        db_table = 'balance_consolidation'

    @property
    def loan_agreement_document_url(self):
        document = self.loan_agreement_document
        return (
            get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, document.url)
            if document and document.url
            else ''
        )


class BalanceConsolidationVerificationManager(GetInstanceMixin, JuloModelManager):
    pass


class BalanceConsolidationVerification(TimeStampedModel):
    VALIDATION_STATUS_CHOICES = (
        (BalanceConsolidationStatus.DRAFT, BalanceConsolidationStatus.DRAFT),
        (BalanceConsolidationStatus.ON_REVIEW, BalanceConsolidationStatus.ON_REVIEW),
        (BalanceConsolidationStatus.APPROVED, BalanceConsolidationStatus.APPROVED),
        (BalanceConsolidationStatus.REJECTED, BalanceConsolidationStatus.REJECTED),
        (BalanceConsolidationStatus.ABANDONED, BalanceConsolidationStatus.ABANDONED),
    )

    id = models.AutoField(db_column='balance_consolidation_verification_id', primary_key=True)
    balance_consolidation = models.OneToOneField(
        BalanceConsolidation, db_column='balance_consolidation_id', on_delete=models.DO_NOTHING
    )
    validation_status = models.CharField(
        choices=VALIDATION_STATUS_CHOICES,
        max_length=50,
        validators=[ascii_validator],
    )

    name_bank_validation = models.OneToOneField(
        'disbursement.NameBankValidation',
        models.DO_NOTHING,
        db_column='name_bank_validation_id',
        blank=True,
        null=True,
    )
    note = models.CharField(max_length=1000, null=True, blank=True)
    loan = BigOneToOneField(Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    locked_by = models.ForeignKey(
        Agent,
        models.DO_NOTHING,
        db_column='locked_by_id',
        blank=True,
        null=True,
        related_name='balance_consolidation_verification_locked',
    )
    account_limit_histories = JSONField(default=dict)
    extra_data = JSONField(default=dict)
    tracker = FieldTracker(fields=['validation_status'])
    objects = BalanceConsolidationVerificationManager()

    class Meta(object):
        db_table = 'balance_consolidation_verification'

    def validation_status_title(self):
        status = self.validation_status.replace('_', ' ')
        return status.title()

    @property
    def is_locked(self):
        return self.locked_by_id is not None

    @property
    def locked_by_info(self):
        if self.is_locked:
            return str(self.locked_by)
        return None


class BalanceConsolidationVerificationHistory(TimeStampedModel):
    id = models.AutoField(
        db_column='balance_consolidation_verification_history_id', primary_key=True
    )
    balance_consolidation_verification = models.ForeignKey(
        BalanceConsolidationVerification,
        on_delete=models.DO_NOTHING,
        db_column='balance_consolidation_verification_id',
    )
    agent = models.ForeignKey(
        Agent,
        db_column='agent_id',
        on_delete=models.DO_NOTHING,
        blank=True, null=True
    )
    field_name = models.TextField()
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()
    change_reason = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'balance_consolidation_verification_history'


class BalanceConsolidationHistory(TimeStampedModel):
    id = models.AutoField(
        db_column='balance_consolidation_history_id',
        primary_key=True
    )
    balance_consolidation = models.ForeignKey(
        BalanceConsolidation,
        on_delete=models.DO_NOTHING,
        db_column='balance_consolidation_id',
    )
    agent = models.ForeignKey(
        Agent,
        db_column='agent_id',
        on_delete=models.DO_NOTHING,
        blank=True, null=True
    )
    field_name = models.TextField()
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField()

    class Meta(object):
        db_table = 'balance_consolidation_history'


class BalanceConsolidationDelinquentFDCChecking(TimeStampedModel):
    id = models.AutoField(
        db_column='balance_consolidation_delinquent_fdc_checking_id',
        primary_key=True
    )
    customer_id = models.IntegerField()
    balance_consolidation_verification = models.ForeignKey(
        BalanceConsolidationVerification, models.DO_NOTHING, db_column='balance_consolidation_verification_id'
    )
    invalid_fdc_inquiry_loan_id = models.BigIntegerField()
    is_punishment_triggered = models.BooleanField(default=False)


    class Meta(object):
        db_table = 'balance_consolidation_delinquent_fdc_checking'
