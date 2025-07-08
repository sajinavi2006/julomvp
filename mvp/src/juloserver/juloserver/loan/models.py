from __future__ import unicode_literals

from builtins import object
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from cuser.fields import CurrentUserField
from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.utils import timezone

from juloserver.julocore.data.models import (
    TimeStampedModel,
    GetInstanceMixin,
    JuloModelManager,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigOneToOneField,
    BigAutoField,
)

from juloserver.julo.models import (
    Customer,
    ProductLine,
    Loan,
)
from juloserver.loan.constants import DBRConst, LoanFailGTLReason, LoanLogIdentifierType


class LoanModelManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = LoanModelManager()


class SphpContent(TimeStampedModel):
    id = models.AutoField(db_column='sphp_content_id', primary_key=True)
    sphp_variable = models.TextField()
    message = models.TextField()
    criteria = JSONField(blank=True, null=True)
    product_line = models.ForeignKey(
        ProductLine, models.DO_NOTHING, db_column='product_line_id', blank=True, null=True
    )

    class Meta(object):
        db_table = 'sphp_content'


class TransactionRiskyCheck(TimeStampedModel):
    id = models.AutoField(db_column='transaction_risky_check_id', primary_key=True)
    loan = BigForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True, unique=True
    )
    is_vpn_detected = models.NullBooleanField()
    is_fh_detected = models.NullBooleanField()
    is_fdc_risky = models.NullBooleanField()
    is_web_location_blocked = models.NullBooleanField()
    is_hardtoreach = models.NullBooleanField()
    decision = models.ForeignKey(
        'TransactionRiskyDecision',
        models.DO_NOTHING,
        db_column='decision_id',
        null=True,
        blank=True,
    )

    class Meta(object):
        db_table = 'transaction_risky_check'


class TransactionRiskyDecision(TimeStampedModel):
    id = models.AutoField(db_column='transaction_risky_decision_id', primary_key=True)
    decision_name = models.CharField(max_length=50)

    class Meta(object):
        db_table = 'transaction_risky_decision'


class LoanAdjustedRate(TimeStampedModel):
    id = models.AutoField(db_column='loan_adjusted_rate_id', primary_key=True)
    # we don't have OneToOneField override using BigInt,
    # so we need to use BigForeignKey with unique=True
    loan = models.OneToOneField(Loan, models.DO_NOTHING, db_column='loan_id')

    # adjusted interest_rate monthly if the simple_fee more than max_fee
    # if adjusted first month interest is not null, this represents non-first month
    adjusted_monthly_interest_rate = models.FloatField()

    # provision fee after adjusted (just feel with the original if the provision is not adjusted)
    adjusted_provision_rate = models.FloatField()
    # total days X 0.4 percent (OJK and AFPI rule)
    max_fee = models.FloatField()
    # original fee percentage (provision_fee_pct + (total_days x original_daily_interest))
    simple_fee = models.FloatField()

    adjusted_first_month_interest_rate = models.FloatField(
        null=True,
        blank=True,
        help_text="available case where simple fee > max fee",
    )

    class Meta(object):
        db_table = 'loan_adjusted_rate'


class PaidLetterNote(TimeStampedModel):
    id = models.AutoField(db_column='paid_letter_note_id', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    added_by = CurrentUserField()
    note_text = models.TextField()

    class Meta(object):
        db_table = 'paid_letter_note'


class RepaymentPaidLetterManager(GetInstanceMixin, JuloModelManager):
    def create(self, *args, **kwargs):
        repayment_paid_letter = super(RepaymentPaidLetterManager, self).create(*args, **kwargs)
        repayment_paid_letter.generate_reference_number()
        repayment_paid_letter.save(update_fields=["reference_number"])
        return repayment_paid_letter


class RepaymentPaidLetter(TimeStampedModel):
    id = models.AutoField(db_column='repayment_paid_letter_id', primary_key=True)
    reference_number = models.TextField(
        db_column='reference_number',
        db_index=True,
        blank=True,
        null=True,
    )
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    subject = models.TextField()
    created_by = CurrentUserField()

    objects = RepaymentPaidLetterManager()

    class Meta(object):
        db_table = 'repayment_paid_letter'

    def generate_reference_number(self):
        import roman

        if self.id is None or self.reference_number is not None:
            return
        today_date = timezone.localtime(timezone.now())
        this_year = today_date.year
        this_month = today_date.month
        last_reference_id = (
            RepaymentPaidLetter.objects.filter(
                cdate__year=this_year, reference_number__isnull=False
            )
            .order_by('id')
            .last()
        )
        last_increment_id = 0
        if last_reference_id:
            last_increment_id = int(last_reference_id.reference_number.split('/')[0] or 0)
        last_increment_id += 1
        reference_number = '{}/JTF/COLL/{}/{}'.format(
            last_increment_id, roman.toRoman(this_month), this_year
        )
        self.reference_number = reference_number


class LoanZeroInterest(TimeStampedModel):
    id = models.AutoField(db_column='loan_zero_interest_id', primary_key=True)
    loan = BigOneToOneField('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    original_loan_amount = models.BigIntegerField()
    original_monthly_interest_rate = models.FloatField()
    adjusted_provision_rate = models.FloatField()

    class Meta(object):
        db_table = 'loan_zero_interest'


class LoanPrizeChance(TimeStampedModel):
    id = models.AutoField(db_column='loan_prize_chance_id', primary_key=True)
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        db_constraint=False,
        db_index=True,
    )
    loan = BigForeignKey(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        db_constraint=False,
        db_index=True,
    )
    chances = models.IntegerField(default=0)

    class Meta(object):
        db_table = 'loan_prize_chance'


class LoanJuloCare(LoanModel):
    id = models.AutoField(db_column='loan_julo_care_id', primary_key=True)
    loan = BigOneToOneField('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    insurance_premium = models.BigIntegerField()

    # adjusted insurance_premium_rate if the simple_fee more than max_fee
    insurance_premium_rate = models.FloatField(null=True, blank=True)
    original_insurance_premium = models.BigIntegerField(null=True, blank=True)

    policy_id = models.CharField(max_length=100, null=True, blank=True)
    policy_number = models.CharField(max_length=100, null=True, blank=True)
    policy_product_code = models.CharField(max_length=100, null=True, blank=True)
    quotation_number = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=100)
    document_url = models.TextField(null=True, blank=True)
    document_filename = models.TextField(null=True, blank=True)
    document_type = models.CharField(max_length=100, null=True, blank=True)
    document_alias = models.CharField(max_length=100, null=True, blank=True)

    device_brand = models.CharField(max_length=100, null=True, blank=True)
    device_model = models.CharField(max_length=100, null=True, blank=True)
    os_version = models.IntegerField(null=True)

    class Meta(object):
        db_table = 'loan_julo_care'


class LoanAdditionalFee(LoanModel):
    id = models.AutoField(db_column='loan_additional_fee_id', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    fee_type = models.ForeignKey(
        'LoanAdditionalFeeType',
        models.DO_NOTHING,
        db_column='fee_type_id',
    )
    fee_amount = models.BigIntegerField()

    class Meta(object):
        db_table = 'loan_additional_fee'


class LoanDbrLog(TimeStampedModel):
    id = models.AutoField(db_column='loan_dbr_log_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    loan_amount = models.BigIntegerField()
    duration = models.IntegerField()
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod', models.DO_NOTHING, db_column='transaction_method_id'
    )
    monthly_income = models.BigIntegerField()
    monthly_installment = models.BigIntegerField()
    source = models.CharField(
        max_length=100,
        choices=DBRConst.DBR_SOURCE,
    )
    log_date = models.DateField(db_index=True)

    class Meta(object):
        db_table = 'loan_dbr_log'


class LoanDbrBlacklist(TimeStampedModel):
    id = models.AutoField(db_column='loan_dbr_blacklist_id', primary_key=True)
    application = models.OneToOneField(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'loan_dbr_blacklist'


class LoanAdditionalFeeType(LoanModel):
    id = models.AutoField(db_column='fee_type_id', primary_key=True)
    name = models.CharField(max_length=30, db_index=True)
    notes = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_additional_fee_type'


class AdditionalLoanInformation(LoanModel):
    id = models.AutoField(db_column='additional_loan_information_id', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey('content_type', 'content_object')

    class Meta(object):
        db_table = 'additional_loan_information'


class LoanRelatedDataHistory(LoanModel):
    id = models.AutoField(db_column='loan_related_data_history_id', primary_key=True)
    field_name = models.CharField(max_length=100)
    old_value = models.TextField()
    new_value = models.TextField()
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.BigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta(object):
        db_table = 'loan_related_data_history'


class LoanFailGTL(LoanModel):
    id = models.AutoField(db_column='loan_fail_gtl_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod', models.DO_NOTHING, db_column='transaction_method_id'
    )
    loan_amount_request = models.BigIntegerField()
    reason = models.CharField(max_length=10, choices=LoanFailGTLReason.CHOICES)

    class Meta(object):
        db_table = 'loan_fail_gtl'


class AnaBlacklistDbr(TimeStampedModel):
    id = BigAutoField(db_column='blacklist_dbr_id', primary_key=True)
    customer_id = models.BigIntegerField()

    class Meta:
        db_table = '"ana"."blacklist_dbr"'
        managed = False


class TenorBasedPricing(LoanModel):
    id = BigAutoField(db_column='tenor_based_pricing_id', primary_key=True)
    customer = BigForeignKey(
        Customer,
        models.DO_NOTHING,
        db_column='customer_id',
        db_constraint=False,
        db_index=True,
    )
    loan = BigForeignKey(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        db_constraint=False,
        db_index=True,
        null=True
    )
    customer_segment = models.CharField(max_length=100, null=True, blank=True)
    tenure = models.IntegerField()
    new_pricing = models.FloatField()
    previous_pricing = models.FloatField()
    reduce_interest = models.FloatField()
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod',
        models.DO_NOTHING,
        db_column='transaction_method_id',
    )

    class Meta(object):
        db_table = 'tenor_based_pricing'


class LoanDelayDisbursementFee(LoanModel):
    id = models.AutoField(db_column='loan_delay_disbursement_id', primary_key=True)
    loan = BigOneToOneField('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    delay_disbursement_premium_fee = models.BigIntegerField()
    delay_disbursement_premium_rate = models.FloatField(null=True, blank=True)
    policy_id = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=100)
    cashback = models.BigIntegerField()
    threshold_time = models.BigIntegerField()
    agreement_timestamp = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = 'loan_delay_disbursement'


class Platform(LoanModel):
    id = models.AutoField(db_column='platform_id', primary_key=True)
    name = models.TextField()

    class Meta(object):
        db_table = 'platform'


class LoanPlatform(LoanModel):
    id = BigAutoField(db_column='loan_platform_id', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    platform = BigForeignKey(Platform, models.DO_NOTHING, db_column='platform_id')

    class Meta(object):
        db_table = 'loan_platform'


class LoanErrorLog(TimeStampedModel):

    id = BigAutoField(db_column='loan_error_log_id', primary_key=True)
    identifier = models.CharField(max_length=100, db_index=True)
    identifier_type = models.CharField(max_length=20, choices=LoanLogIdentifierType.CHOICES)
    api_url = models.TextField(help_text='e.g. /api/qris/v1/transaction-limit-check')
    error_code = models.CharField(max_length=20, help_text='e.g. err_001, err_002')
    http_status_code = models.IntegerField(
        help_text='response status code if any: 401, 400', null=True, blank=True
    )
    error_detail = models.TextField(help_text="e.g. NO_LENDER_AVAILABLE")

    class Meta(object):
        db_table = 'loan_error_log'
        managed = False

        index_together = [
            ('identifier', 'identifier_type'),
        ]


class TransactionModelCustomerManager(GetInstanceMixin, JuloModelManager):
    pass


class TransactionModelCustomer(TimeStampedModel):
    """
    Mercury customers are high risk customers (according to ana transaction data model)
    """
    id = BigAutoField(db_column='transaction_model_customer_id', primary_key=True)
    customer_id = models.BigIntegerField(db_index=True, unique=True)
    is_mercury = models.BooleanField(default=False)
    allowed_loan_duration = ArrayField(
        models.IntegerField(validators=[MinValueValidator(1)]),
    )
    max_cashloan_amount = models.IntegerField(help_text="max cashloan limit received from ana")

    objects = TransactionModelCustomerManager()

    class Meta(object):
        db_table = 'transaction_model_customer'


class TransactionModelCustomerHistory(TimeStampedModel):
    id = BigAutoField(db_column='transaction_model_customer_history_id', primary_key=True)
    transaction_model_customer = BigForeignKey(
        to=TransactionModelCustomer,
        on_delete=models.DO_NOTHING,
        db_column='transaction_model_customer_id',
        related_name='histories',
    )
    field_name = models.TextField()
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField()

    class Meta(object):
        db_table = 'transaction_model_customer_history'


class TransactionModelCustomerLoan(TimeStampedModel):
    id = BigAutoField(db_column='transaction_model_customer_loan_id', primary_key=True)
    transaction_model_customer = BigForeignKey(
        to=TransactionModelCustomer,
        on_delete=models.DO_NOTHING,
        db_column='transaction_model_customer_id',
        related_name='loans',
    )
    loan_id = models.BigIntegerField(db_index=True)
    transaction_model_data = JSONField()

    class Meta(object):
        db_table = 'transaction_model_customer_loan'
        index_together = [
            ('loan_id', 'transaction_model_customer'),
        ]


class TransactionModelCustomerAnaHistory(TimeStampedModel):
    id = BigAutoField(db_column='transaction_model_customer_ana_history_id', primary_key=True)
    customer_id = models.BigIntegerField(db_index=True)
    ana_response = JSONField()

    class Meta(object):
        db_table = 'transaction_model_customer_ana_history'


class LoanTransactionDetail(TimeStampedModel):
    id = BigAutoField(db_column='loan_transaction_detail_id', primary_key=True)
    loan_id = models.BigIntegerField(db_index=True)
    detail = JSONField()

    class Meta(object):
        db_table = 'loan_transaction_detail'
        managed = False
