from __future__ import unicode_literals

from builtins import object

from django.db import models, transaction
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db.models.query_utils import Q
from django.core.exceptions import ValidationError


from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager, TimeStampedModel
from juloserver.julo.models import XidLookup

from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigAutoField
from juloserver.julo.models import (Partner,
                                    PaymentMethodLookup)
from juloserver.merchant_financing.constants import (
    MerchantHistoricalTransactionTaskStatuses,
    MerchantRiskAssessmentStatus,
)
from juloserver.pii_vault.models import PIIVaultModelManager, PIIVaultModel

ascii_validator = RegexValidator(regex='^[\u0020-\u007e]+$', message='characters not allowed')


class MerchantFinancingModelManager(GetInstanceMixin, JuloModelManager):
    pass


class MerchantFinancingModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = MerchantFinancingModelManager()


class ApplicationSubmission(MerchantFinancingModel):
    id = models.AutoField(db_column='application_submission_id', primary_key=True)
    loan_xid = models.BigIntegerField(blank=True, null=True)
    axiata_customer_data = models.ForeignKey(
        'sdk.AxiataCustomerData', models.DO_NOTHING, db_column='axiata_customer_data_id')
    application_submission_response = models.SmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, null=True, blank=True)
    is_digital_signature_eligible = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'application_submission'


class SentCreditInformation(MerchantFinancingModel):
    id = models.AutoField(db_column='sent_credit_information_id', primary_key=True)

    application_xid = models.BigIntegerField(blank=True, null=True)
    loan_xid = models.BigIntegerField(blank=True, null=True)
    partner_application_id = models.TextField(null=True, blank=True)
    decision = models.TextField()
    reject_reason = models.TextField(null=True)
    sending_status = models.TextField(null=True)

    class Meta(object):
        db_table = 'sent_credit_information'
        managed = False


class PartnerDisbursementRequest(MerchantFinancingModel):
    id = models.AutoField(db_column='partner_disbursement_request_id', primary_key=True)

    loan_xid = models.BigIntegerField(blank=True, null=True)
    partner_application_id = models.TextField(null=True, blank=True)
    response = models.SmallIntegerField(blank=False)
    status = models.TextField(null=True)

    class Meta(object):
        db_table = 'partner_disbursement_request'
        managed = False


class SentDisburseContract(MerchantFinancingModel):
    id = models.AutoField(db_column='sent_disburse_contract_id', primary_key=True)

    loan_xid = models.BigIntegerField(blank=True, null=True)
    partner_application_id = models.TextField(null=True, blank=True)
    fund_transfer_ts = models.DateTimeField(blank=True, null=True)
    disbursed_amount = models.BigIntegerField(default=0)
    disbursement_status = models.TextField(null=True)
    sending_status = models.TextField(null=True)

    class Meta(object):
        db_table = 'sent_disburse_contract'


class SentUpdateRepaymentInfo(MerchantFinancingModel):
    id = models.AutoField(db_column='sent_update_repayment_info_id', primary_key=True)

    loan_xid = models.BigIntegerField(blank=True, null=True)
    partner_application_id = models.TextField(null=True, blank=True)
    payment_amount = models.BigIntegerField(default=0)
    payment_number = models.SmallIntegerField(blank=False)
    payment_date = models.DateField()
    sending_status = models.TextField(null=True)
    status = models.TextField(null=True)

    class Meta(object):
        db_table = 'sent_update_repayment_info'


class MerchantManager(GetInstanceMixin, JuloModelManager):

    def create(self, *args, **kwargs):
        merchant = super(MerchantManager, self).create(*args, **kwargs)
        merchant.generate_xid()
        merchant.save(update_fields=["merchant_xid"])
        return merchant


class MerchantPIIVaultManager(PIIVaultModelManager, MerchantManager):
    pass


class Merchant(PIIVaultModel):
    PII_FIELDS = ['owner_name', 'email', 'phone_number', 'nik', 'npwp']
    PII_ASYNC_QUEUE = 'partnership_pii_vault'

    id = models.AutoField(db_column='merchant_id', primary_key=True)
    customer = models.OneToOneField(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id',
        null=True, blank=True)
    historical_partner_affordability_threshold = models.ForeignKey(
        'HistoricalPartnerAffordabilityThreshold', models.DO_NOTHING,
        db_column='historical_partner_affordability_threshold',
        blank=True, null=True
    )
    merchant_score_grade = models.TextField(null=True, blank=True)
    partner_merchant_code = models.TextField(null=True, blank=True)
    owner_name = models.TextField(null=True, blank=True)
    email = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone_number = models.TextField(blank=True, null=True)
    nik = models.CharField(max_length=16, blank=True, null=True)
    type_of_business = models.TextField(blank=True, null=True)
    shop_name = models.TextField(blank=False)
    company_name = models.TextField(null=True, blank=True)
    company_registration_number = models.TextField(null=True, blank=True)
    date_of_establishment = models.DateField(null=True, blank=True)
    historical_partner_config_product_lookup = models.ForeignKey(
        'partnership.HistoricalPartnerConfigProductLookup', models.DO_NOTHING,
        db_column='historical_partner_config_product_lookup_id',
        blank=True, null=True
    )
    shop_number = models.SmallIntegerField(null=True, blank=True)
    npwp = models.TextField(blank=True, null=True)
    partner_distributor_id = models.TextField(blank=False)
    distributor = models.ForeignKey('partnership.Distributor',
                                    models.DO_NOTHING, db_column='distributor_id',
                                    blank=True, null=True)
    merchant_category = models.ForeignKey(
        'partnership.MerchantDistributorCategory',
        models.DO_NOTHING, db_column='merchant_category_id', blank=True, null=True)
    limit = models.BigIntegerField(default=0)
    merchant_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    business_rules_score = models.FloatField(blank=True, null=True)

    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)
    npwp_tokenized = models.TextField(blank=True, null=True)
    owner_name_tokenized = models.TextField(blank=True, null=True)

    objects = MerchantPIIVaultManager()

    def generate_xid(self):
        if self.id is None or self.merchant_xid is not None:
            return
        self.merchant_xid = XidLookup.get_new_xid()

    class Meta(object):
        db_table = 'merchant'


class BulkDisbursementListManager(GetInstanceMixin, JuloModelManager):
    pass


class BulkDisbursementRequest(TimeStampedModel):
    id = models.AutoField(db_column='bulk_disbursement_request_id', primary_key=True)
    disbursement = models.ForeignKey('disbursement.Disbursement',
                                     db_column='disbursement_id', null=True, blank=True)
    loan = BigForeignKey('julo.Loan',
                         db_column='loan_id')
    product_line_code = models.ForeignKey('julo.ProductLine',
                                          db_column='product_line_code_id')
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True, blank=True)
    distributor = models.ForeignKey(
        'partnership.Distributor', models.DO_NOTHING, db_column='distributor_id', blank=True,
        null=True)
    bank_account_number = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    disbursement_amount = models.BigIntegerField()
    disbursement_status = models.CharField(max_length=50)
    loan_amount = models.BigIntegerField()
    name_bank_validation_id = models.IntegerField()

    objects = BulkDisbursementListManager()

    class Meta(object):
        db_table = 'bulk_disbursement_request'
        unique_together = ('loan', 'bank_account_number')


class BulkDisbursementScheduleManager(GetInstanceMixin, JuloModelManager):
    pass


class BulkDisbursementSchedule(TimeStampedModel):
    id = models.AutoField(db_column='bulk_disbursement_schedule_id', primary_key=True)
    product_line_code = models.ForeignKey(
        'julo.ProductLine', db_column='product_line_code_id', null=True)
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True, blank=True)
    distributor = models.ForeignKey(
        'partnership.Distributor', models.DO_NOTHING, db_column='distributor_id', blank=True,
        null=True)
    crontab = models.CharField(max_length=50, default='* * * * *')
    is_active = models.BooleanField()
    is_manual_disbursement = models.BooleanField(default=False)

    objects = BulkDisbursementScheduleManager()

    class Meta(object):
        db_table = 'bulk_disbursement_schedule'


class MasterPartnerAffordabilityThreshold(TimeStampedModel):
    id = models.AutoField(db_column='master_partner_affordability_threshold_id', primary_key=True)
    partner = models.OneToOneField('julo.Partner', models.DO_NOTHING, db_column='partner_id')
    minimum_threshold = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="This value must be lower than maximum threshold"
    )
    maximum_threshold = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="This value must be greater than minimum threshold"
    )

    class Meta(object):
        db_table = 'master_partner_affordability_threshold'

    def __str__(self):
        return "{}".format(self.id)


class HistoricalPartnerAffordabilityThreshold(TimeStampedModel):
    id = models.AutoField(
        db_column='historical_partner_affordability_threshold_id', primary_key=True
    )
    master_partner_affordability_threshold = models.ForeignKey(
        'MasterPartnerAffordabilityThreshold', models.DO_NOTHING,
        db_column='master_partner_affordability_threshold_id'
    )
    minimum_threshold = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    maximum_threshold = models.PositiveIntegerField(validators=[MinValueValidator(0)])

    class Meta(object):
        db_table = 'historical_partner_affordability_threshold'

    def __str__(self):
        return "{}".format(self.id)


class MerchantBinaryCheck(MerchantFinancingModel):
    GREATER_THAN = 'GT'
    GREATER_THAN_EQUAL = 'GTE'
    LESS_THAN = 'LT'
    LESS_THAN_EQUAL = 'LTE'
    EQUALS = 'EE'
    OPERATOR_CHOICES = [
        (GREATER_THAN, 'GREATER_THAN'),
        (GREATER_THAN_EQUAL, 'GREATER_THAN_EQUAL'),
        (LESS_THAN, 'LESS_THAN'),
        (LESS_THAN_EQUAL, 'LESS_THAN_EQUAL'),
        (EQUALS, 'EQUALS'),
    ]
    id = models.AutoField(
        db_column='merchant_binary_check_id', primary_key=True)
    is_active = models.BooleanField(default=True)
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id')
    category = models.CharField(max_length=100, null=True, blank=True)
    raw_sql_query = models.TextField()
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES, default=EQUALS)
    cut_off_limit = models.FloatField()
    binary_check_weight = models.DecimalField(default=0.5, max_digits=10, decimal_places=2)

    class Meta(object):
        db_table = 'merchant_binary_check'

    def __str__(self):
        return "{} - {}".format(self.id, self.partner.name)


class MerchantPartner(Partner):

    class Meta:
        proxy = True
        auto_created = True


class MerchantApplicationReapplyInterval(TimeStampedModel):
    """
    Model for creating interval rules for reapply application by merchant
    depends on the application status code and partner (optional)
    """

    id = models.AutoField(
        db_column='merchant_application_reapply_interval_id', primary_key=True)
    application_status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='status_code',
        limit_choices_to=Q(status_code__lt=200))
    interval_day = models.PositiveIntegerField()
    partner = models.ForeignKey(
        'julo.Partner', models.DO_NOTHING, db_column='partner_id', null=True, blank=True)

    def validate_unique(self, exclude=None):
        if MerchantApplicationReapplyInterval.objects.exclude(id=self.id) \
            .filter(
                application_status_id=self.application_status_id,
                partner__isnull=True).exists() and self.partner is None:
            raise ValidationError("Duplicate Merchant Application Reapply Interval")

        super(MerchantApplicationReapplyInterval, self).validate_unique(exclude)

    class Meta(object):
        db_table = 'merchant_application_reapply_interval'
        unique_together = ('application_status', 'partner')

    def __str__(self):
        return "{} - {} days, partner {}".format(
            self.application_status, self.interval_day, self.partner)


class MerchantPaymentMethodLookup(PaymentMethodLookup):

    class Meta:
        proxy = True
        auto_created = True


class MerchantHistoricalTransactionTask(TimeStampedModel):
    id = models.AutoField(
        db_column='merchant_historical_transaction_task_id', primary_key=True)
    path = models.TextField(blank=True, null=True)
    error_path = models.TextField(blank=True, null=True)
    application = BigForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id')
    file_name = models.TextField(blank=True, null=True)
    unique_id = models.CharField(max_length=255, unique=True)

    class Meta(object):
        db_table = 'merchant_historical_transaction_task'


class MerchantHistoricalTransactionTaskStatus(TimeStampedModel):
    id = models.AutoField(
        db_column='merchant_historical_transaction_task_status_id', primary_key=True)
    status = models.CharField(max_length=20, choices=MerchantHistoricalTransactionTaskStatuses.STATUS_CHOICES)
    merchant_historical_transaction_task = models.OneToOneField(
        MerchantHistoricalTransactionTask, models.DO_NOTHING,
        db_column='merchant_historical_transaction_task_id',
    )

    class Meta(object):
        db_table = 'merchant_historical_transaction_task_status'


class MerchantRiskAssessmentResult(TimeStampedModel):
    id = BigAutoField(db_column='merchant_risk_assessment_result_id', primary_key=True)
    application_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=50)
    risk = models.CharField(max_length=20)
    status = models.CharField(
        max_length=30,
        default=MerchantRiskAssessmentStatus.ACTIVE,
        choices=MerchantRiskAssessmentStatus.CHOICES,
        help_text="To check status risk, is active or inactive",
    )
    notes = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'merchant_risk_assessment_result'
        managed = False

    def __str__(self) -> str:
        return "application_id_{}".format(self.application_id)
