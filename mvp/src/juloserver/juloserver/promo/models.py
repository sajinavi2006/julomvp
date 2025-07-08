from ckeditor.fields import RichTextField

from django.contrib.postgres.fields import (
    ArrayField,
    JSONField,
)
from django.db import models

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import (
    Loan,
    Payment,
    Customer,
    Application,
    Agent, ascii_validator,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julocore.customized_psycopg2.models import (
    BigAutoField,
    BigForeignKey,
)
from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
    CustomQuerySet,
)
from juloserver.promo.constants import (
    PromoCodeTypeConst,
    PromoPageConst,
    PromoCodeCriteriaConst,
)


class PromoCode(models.Model):
    BENEFIT_CHOICES = [
        ('0% INTEREST', "0% Interest on first installment"),
        ('cashback', "Cashback"),
    ]
    id = models.AutoField(db_column='promo_code_id', primary_key=True)
    promo_name = models.CharField(max_length=80, blank=True, null=True)
    promo_code = models.CharField(max_length=80, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)

    type = models.TextField(blank=True, db_index=True,
                            default=PromoCodeTypeConst.APPLICATION,
                            choices=PromoCodeTypeConst.CHOICES)

    # Only used for type=application, all criteria move to PromoCodeCriteria
    partner = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    product_line = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    credit_score = ArrayField(models.CharField(max_length=200), blank=True, null=True)
    # end of deprecated

    # Only used for type=application, all the benefit move to PromoCodeBenefit
    promo_benefit = models.CharField(max_length=30, choices=BENEFIT_CHOICES, blank=True, null=True)
    cashback_amount = models.BigIntegerField(blank=True, null=True)
    # end of deprecated

    promo_code_benefit = BigForeignKey('PromoCodeBenefit', on_delete=models.DO_NOTHING,
                                           blank=True, null=True)
    criteria = ArrayField(models.BigIntegerField(), blank=True, null=True)
    promo_code_usage_count = models.PositiveIntegerField(default=0)
    promo_code_daily_usage_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'promo_code'
        managed = False

    def __str__(self):
        """Visual identification"""
        return str(self.code)

    @property
    def code(self):
        return self.promo_code

    def minimum_transaction_amount(self):
        criteria_ids = self.criteria
        if not criteria_ids:
            return None

        promo_code_criteria = PromoCodeCriteria.objects.filter(
            id__in=criteria_ids, type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT
        ).last()
        if not promo_code_criteria:
            return None

        return promo_code_criteria.value.get('minimum_loan_amount', None)

    def promo_code_benefit_discount_value(self):
        discount = self.promo_code_benefit.value
        return discount.get('percent') or discount.get('amount')


class PromoHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class PromoHistory(TimeStampedModel):
    id = models.AutoField(db_column='promo_history_id', primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    promo_type = models.CharField(max_length=150, blank=True, null=True)
    account_payment = models.ForeignKey(
        AccountPayment,
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    account = models.ForeignKey(
        Account, models.DO_NOTHING, db_column='account_id', null=True, blank=True)

    objects = PromoHistoryManager()

    class Meta(object):
        db_table = 'promo_history'


class WaivePromoQuerySet(CustomQuerySet):
    def eligible_loans(self, promo_event_type):
        return self.filter(
            promo_event_type=promo_event_type).exclude(
            loan__loan_status_id=LoanStatusCodes.PAID_OFF
        ).order_by('loan').distinct('loan')


class WaivePromoManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return WaivePromoQuerySet(self.model)


class WaivePromo(TimeStampedModel):
    id = models.AutoField(db_column='waive_promo_id', primary_key=True)
    loan = models.ForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    remaining_installment_principal = models.BigIntegerField(blank=True, default=0)
    remaining_installment_interest = models.BigIntegerField(blank=True, default=0)
    remaining_late_fee = models.BigIntegerField(blank=True, default=0)
    promo_event_type = models.CharField(max_length=100, blank=True, null=True)

    objects = WaivePromoManager()

    class Meta(object):
        db_table = 'waive_promo'


class JsonValueMixin:
    def get_value(self, key=None, default=None, to_type=None):
        value = self.value
        if key is not None:
            value = value.get(key, default)

        if to_type is not None:
            return to_type(value)

        return value


class PromoCodeBenefit(TimeStampedModel, JsonValueMixin):
    id = BigAutoField(db_column='promo_code_benefit_id', primary_key=True)
    name = models.TextField()

    # See PromoCodeBenefitConst
    type = models.TextField(db_index=True)
    value = JSONField()
    promo_page = models.ForeignKey('PromoPage', models.DO_NOTHING,
        db_column='promo_page_id', blank=True, null=True, verbose_name='TnC')

    class Meta(object):
        db_table = 'promo_code_benefit'
        managed = False

    def __str__(self):
        return f'{self.id} - {self.name} - {self.type}'


class PromoCodeCriteriaManager(GetInstanceMixin, JuloModelManager):
    pass


class PromoCodeCriteria(TimeStampedModel, JsonValueMixin):
    id = BigAutoField(db_column='promo_code_criteria_id', primary_key=True)
    name = models.TextField()

    # See PromoCodeCriteriaConst
    type = models.TextField(db_index=True)
    value = JSONField()

    objects = PromoCodeCriteriaManager()

    class Meta(object):
        db_table = 'promo_code_criteria'
        managed = False

    def __str__(self):
        return f'{self.id} - {self.name} - {self.type}'


class PromoCodeUsage(TimeStampedModel):
    id = BigAutoField(db_column='promo_code_usage_id', primary_key=True)
    promo_code = models.ForeignKey(PromoCode, models.DO_NOTHING, db_column='promo_code_id')
    customer_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    loan_id = models.BigIntegerField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    promo_code_benefit = BigForeignKey(PromoCodeBenefit, models.DO_NOTHING,
                                       db_column='promo_code_benefit_id', blank=True, null=True)
    applied_at = models.DateTimeField(blank=True, null=True)
    benefit_amount = models.BigIntegerField(blank=True, null=True)
    configuration_log = JSONField(blank=True, null=True)
    version = models.CharField(
        max_length=10,
        blank=True, null=True,
        validators=[ascii_validator]
    )

    class Meta:
        db_table = 'promo_code_usage'
        managed = False

    @property
    def is_cancelled(self):
        """
        Returns True if the promo code usage is cancelled. Probably because of disbursement failed
        Returns False otherwise
        """
        return self.cancelled_at is not None

    @property
    def is_active(self):
        """
        The promo code is used.
        """
        return not self.is_cancelled


class PromoPage(TimeStampedModel):
    id = models.AutoField(db_column='promo_page_id', primary_key=True)
    is_active = models.BooleanField(default=True)
    title = models.TextField(unique=True)
    content = RichTextField(blank=True, null=True)

    class Meta:
        db_table = 'promo_page'
        managed = False

    def __str__(self):
        return self.title


class PromoCodeAgentMapping(TimeStampedModel):
    id = models.AutoField(db_column='promo_code_agent_mapping_id', primary_key=True)
    agent_id = models.IntegerField(blank=True, null=True)
    promo_code = models.ForeignKey(PromoCode, models.DO_NOTHING, db_column='promo_code_id')

    class Meta:
        db_table = 'promo_code_agent_mapping'
        unique_together = ('agent_id',)  # Each agent will only handle 1 promo code
        managed = False


class CriteriaControlList(TimeStampedModel):
    id = BigAutoField(db_column='criteria_control_list_id', primary_key=True)
    promo_code_criteria = models.ForeignKey(
        PromoCodeCriteria, models.DO_NOTHING, db_column='promo_code_criteria_id'
    )
    customer_id = models.BigIntegerField()
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'promo_code_control_list'
        unique_together = ('promo_code_criteria', 'customer_id')
        managed = False
