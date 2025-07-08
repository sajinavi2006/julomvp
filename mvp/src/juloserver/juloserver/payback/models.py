from __future__ import unicode_literals

from builtins import str
from builtins import object
from django.db import models
from django.db.models import Sum
from django.conf import settings

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from juloserver.julo.models import Loan, Payment, Customer
from .constants import WaiverConst
from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment

from juloserver.pii_vault.models import (
    PIIVaultModel,
    PIIVaultModelManager,
)

from django.core.validators import RegexValidator
from juloserver.julocore.customized_psycopg2.models import BigAutoField


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class PaybackModelManager(GetInstanceMixin, JuloModelManager):
    pass


class PaybackModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = PaybackModelManager()


class CashbackPromo(PaybackModel):
    DECISION_CHOICES = (
        ('rejected', 'rejected'),
        ('approved', 'approved'))
    DEPARTMENT_CHOICES = (('Marketing', 'Marketing'),
                          ('Finance', 'Finance'),
                          ('Product - Collections', 'Product - Collections'),
                          ('Product - Cashback', 'Product - Cashback'),
                          ('Product - Onboarding', 'Product - Onboarding'))

    id = models.AutoField(db_column='cashback_promo_id', primary_key=True)
    promo_name = models.CharField(max_length=100)
    department = models.CharField(max_length=200,
                                  choices=DEPARTMENT_CHOICES)
    pic_email = models.CharField(max_length=200)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='requester_id', blank=True, null=True,
        related_name="cashback_promo_requester")
    decision_ts = models.DateTimeField(blank=True, null=True)
    decision = models.CharField(max_length=50, blank=True, null=True,
                                choices=DECISION_CHOICES)
    decided_by = models.CharField(max_length=200, blank=True, null=True)
    number_of_customers = models.IntegerField(blank=True, null=True)
    total_money = models.BigIntegerField(blank=True, null=True)
    approval_token = models.CharField(max_length=250, blank=True, null=True)
    is_completed = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'cashback_promo'

    def __str__(self):
        return self.promo_name


class WaiverTemp(PaybackModel):
    STATUS_CHOICES = (
        (WaiverConst.IMPLEMENTED_STATUS, WaiverConst.IMPLEMENTED_STATUS),
        (WaiverConst.EXPIRED_STATUS, WaiverConst.EXPIRED_STATUS),
        (WaiverConst.ACTIVE_STATUS, WaiverConst.ACTIVE_STATUS)
    )
    id = models.AutoField(db_column='waiver_temp_id', primary_key=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING,
                             null=True, blank=True,
                             db_column='loan_id')
    payment = models.ForeignKey(Payment,
                             models.DO_NOTHING,
                             db_column='payment_id',
                             null=True, blank=True)
    late_fee_waiver_amt = models.BigIntegerField(default=0)
    interest_waiver_amt = models.BigIntegerField(default=0)
    principal_waiver_amt = models.BigIntegerField(default=0)
    need_to_pay = models.BigIntegerField(blank=True, null=True)
    waiver_date = models.DateField()
    status = models.CharField(max_length=50,
                                  choices=STATUS_CHOICES, default='active')
    late_fee_waiver_note = models.TextField()
    interest_waiver_note = models.TextField()
    principal_waiver_note = models.TextField(blank=True, null=True, default=None)
    valid_until = models.DateField(blank=True, null=True, default=None)
    waiver_request = models.ForeignKey(WaiverRequest,
                                       models.DO_NOTHING,
                                       blank=True,
                                       null=True,
                                       db_column='waiver_request')
    is_automated = models.BooleanField(default=False)
    is_proactive = models.BooleanField(default=False)
    last_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, blank=True, null=True,
        db_column='last_approved_by_id', related_name='%(class)s_last_approved_by')
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')

    class Meta(object):
        db_table = 'waiver_temp'

    @property
    def waiver_payment_temp(self):
        return self.waiverpaymenttemp_set

    @property
    def payment_ids(self):
        waiver_payments = self.waiver_payment_temp.order_by("payment__payment_number")
        if waiver_payments:
            payment_ids = []
            for waiver_payment in waiver_payments:
                payment_ids.append(str(waiver_payment.payment_id))
            return ", ".join(payment_ids)

        return None

    @property
    def account_payment_ids(self):
        waiver_account_payments = self.waiverpaymenttemp_set.order_by("account_payment__due_date")
        if waiver_account_payments:
            account_payment_ids = []
            for waiver_account_payment in waiver_account_payments:
                account_payment_ids.append(str(waiver_account_payment.account_payment_id))
            return ", ".join(account_payment_ids)

        return None

    def waiver_payment_temp_by_payment(self, payment):
        return self.waiver_payment_temp.filter(payment=payment).last()

    def waiver_payment_temp_by_account_payment(self, account_payment):
        return self.waiver_payment_temp.filter(account_payment=account_payment).last()

    def get_waiver_amount(self, field, params=dict()):
        return self.waiver_payment_temp.exclude(**params).aggregate(
            total_amount=Sum(field))['total_amount'] or 0

    def get_unrounded_waiver_percentage(self, waiver_type):
        if waiver_type not in ("principal", "interest", "late_fee"):
            return None

        waiver_request = self.waiver_request
        if not waiver_request:
            return None

        waiver_approval = waiver_request.waiverapproval_set.last()
        if waiver_approval:
            field = 'unrounded_approved_%s_waiver_percentage' % waiver_type
            if hasattr(waiver_approval, field):
                return getattr(waiver_approval, field)

        field = 'unrounded_requested_%s_waiver_percentage' % (waiver_type)
        if hasattr(waiver_request, field):
            return getattr(waiver_request, field)

        return None


class WaiverPaymentTemp(TimeStampedModel):
    id = models.AutoField(db_column='waiver_payment_temp_id', primary_key=True)
    waiver_temp = models.ForeignKey(WaiverTemp, on_delete=models.DO_NOTHING,
                                    db_column='waiver_temp_id')
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id', null=True,
                                blank=True)
    late_fee_waiver_amount = models.BigIntegerField(blank=True, null=True)
    interest_waiver_amount = models.BigIntegerField(blank=True, null=True)
    principal_waiver_amount = models.BigIntegerField(blank=True, null=True)
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, db_column='account_payment_id')

    class Meta(object):
        db_table = 'waiver_payment_temp'


class GopayAccountLinkStatus(PaybackModel):
    id = models.AutoField(db_column='gopay_account_link_status_id', primary_key=True)
    pay_account_id = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    token = models.TextField(blank=True, null=True)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')
    registration_url_id = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'gopay_account_link_status'


class GopayCustomerBalance(PaybackModel):
    id = models.AutoField(db_column='gopay_customer_balance_id', primary_key=True)
    gopay_account = models.ForeignKey(
        GopayAccountLinkStatus,
        models.DO_NOTHING, null=True, blank=True, db_column='gopay_account_id')
    is_active = models.BooleanField(default=False)
    balance = models.BigIntegerField(default=0)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')

    class Meta(object):
        db_table = 'gopay_customer_balance'


class GopayRepaymentTransaction(PaybackModel):
    id = models.AutoField(db_column='gopay_repayment_transaction_id', primary_key=True)
    gopay_account = models.ForeignKey(
        GopayAccountLinkStatus,
        models.DO_NOTHING, null=True, blank=True, db_column='gopay_account_id')
    transaction_id = models.TextField(blank=True, null=True)
    external_transaction_id = models.TextField(blank=True, null=True)
    amount = models.BigIntegerField(blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    status_code = models.IntegerField(blank=True, null=True)
    status_message = models.TextField(blank=True, null=True)
    source = models.TextField(null=True)

    class Meta(object):
        db_table = 'gopay_repayment_transaction'


class GopayAutodebetTransaction(PaybackModel):
    id = models.AutoField(db_column='gopay_autodebet_transaction_id', primary_key=True)
    gopay_account = models.ForeignKey(
        GopayAccountLinkStatus,
        models.DO_NOTHING, null=True, blank=True, db_column='gopay_account_id')
    customer = models.ForeignKey(
        Customer, 
        models.DO_NOTHING, null=True, blank=True, db_column='customer_id')
    name = models.CharField(max_length=50, blank=True, null=True)
    subscription_id = models.TextField(blank=True, null=True)
    transaction_id = models.TextField(blank=True, null=True)
    external_transaction_id = models.TextField(blank=True, null=True)
    amount = models.BigIntegerField(blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    status_code = models.IntegerField(blank=True, null=True)
    status_desc = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=False)
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING, null=True, blank=True, db_column='account_payment')
    forced_inactive_by_julo = models.BooleanField(default=False)
    paid_amount = models.BigIntegerField(blank=True, null=True)
    is_partial = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'gopay_autodebet_transaction'


class DanaBillerStatus(PaybackModel):
    id = models.AutoField(db_column='dana_biller_status_id', primary_key=True)
    is_success = models.BooleanField(default=False)
    code = models.TextField(db_index=True)
    message = models.TextField()

    class Meta(object):
        db_table = 'dana_biller_status'


class DanaBillerInquiry(PaybackModel):
    id = models.AutoField(db_column='dana_biller_inquiry_id', primary_key=True)
    inquiry_id = models.TextField(unique=True, db_index=True)
    primary_param = models.TextField()
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING, null=True, blank=True, db_column='account_payment_id')
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')
    amount = models.BigIntegerField(blank=True, null=True)
    dana_biller_status = models.ForeignKey(DanaBillerStatus, models.DO_NOTHING,
                                           db_column='dana_biller_status_id')

    class Meta(object):
        db_table = 'dana_biller_inquiry'


class DanaBillerOrder(PaybackModel):
    id = models.AutoField(db_column='dana_biller_order_id', primary_key=True)
    primary_param = models.TextField(db_index=True)
    request_id = models.TextField(db_index=True)
    order_id = models.TextField(db_index=True, blank=True, null=True)
    dana_biller_inquiry = models.OneToOneField(
        DanaBillerInquiry, models.DO_NOTHING, null=True, blank=True,
        db_column='dana_biller_inquiry_id'
    )
    payback_transaction = models.ForeignKey(
        'julo.PaybackTransaction',
        models.DO_NOTHING,
        db_column='payback_transaction_id',
        blank=True,
        null=True,
    )
    dana_biller_status = models.ForeignKey(DanaBillerStatus, models.DO_NOTHING,
                                           db_column='dana_biller_status_id')

    class Meta(object):
        db_table = 'dana_biller_order'


class DokuVirtualAccountSuffixManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class DokuVirtualAccountSuffix(PIIVaultModel):
    PII_FIELDS = ['virtual_account_suffix']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = BigAutoField(db_column='doku_virtual_account_suffix_id', primary_key=True)
    virtual_account_suffix = models.CharField(
        max_length=7,
        blank=True,
        validators=[
            RegexValidator(
                regex='^[0-9]+$', message='Virtual account suffix has to be numeric digits'
            )
        ],
        unique=True,
    )
    loan_id = models.BigIntegerField(db_column='loan_id', null=True, blank=True)
    line_of_credit_id = models.BigIntegerField(db_column='line_of_credit_id', null=True, blank=True)
    account_id = models.BigIntegerField(db_column='account_id', null=True, blank=True)
    virtual_account_suffix_tokenized = models.TextField(null=True, blank=True)
    objects = DokuVirtualAccountSuffixManager()

    class Meta(object):
        db_table = 'doku_virtual_account_suffix'
        managed = False


class PaybackAPILog(PaybackModel):
    id = models.AutoField(db_column='payback_api_log_id', primary_key=True)
    customer_id = models.BigIntegerField(db_column='customer_id', null=True, blank=True)
    loan_id = models.BigIntegerField(db_column='loan_id', null=True, blank=True)
    account_payment_id = models.BigIntegerField(
        db_column='account_payment_id', null=True, blank=True
    )
    payback_transaction_id = models.BigIntegerField(
        db_column='payback_transaction_id', null=True, blank=True
    )
    request_type = models.TextField()
    http_status_code = models.IntegerField()
    request = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    vendor = models.TextField(null=True, blank=True)
    header = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'payback_api_log'
        managed = False
