from __future__ import unicode_literals
from builtins import object
import logging

from django.db import models, transaction
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from datetime import datetime, date, timedelta
from django.conf import settings
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.postgres.fields import JSONField

from juloserver.julocore.data.models import GetInstanceMixin, JuloModelManager, TimeStampedModel
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
                                    StatusLookup,
                                    Application,
                                    FeatureSetting,
                                    Loan,
                                    Document,
                                    Image,
                                    XidLookup)
from phonenumber_field.modelfields import PhoneNumberField
from juloserver.followthemoney.constants import (
    LenderStatus,
    LenderWithdrawalStatus,
    LoanAgreementType,
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey, BigAutoField

logger = logging.getLogger(__name__)

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class FollowTheMoneyModelManager(GetInstanceMixin, JuloModelManager):
    pass


class FollowTheMoneyModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = FollowTheMoneyModelManager()


class LenderBucketManager(GetInstanceMixin, models.Manager):

    def create(self, *args, **kwargs):
        lender_bucket = super(LenderBucketManager, self).create(*args, **kwargs)
        lender_bucket.generate_xid()
        lender_bucket.save(update_fields=["lender_bucket_xid"])
        return lender_bucket


class LenderBucket(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_bucket_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING,
                                db_column='partner_id')
    total_approved = models.IntegerField(default=0)
    total_rejected = models.IntegerField(default=0)
    total_disbursement = models.BigIntegerField(default=0)
    total_loan_amount = models.BigIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_disbursed = models.BooleanField(default=False)
    application_ids = JSONField(null=True, blank=True)
    loan_ids = JSONField(null=True, blank=True)
    action_time = models.DateTimeField(null=True, blank=True)
    action_name = models.CharField(null=True, blank=True, max_length=100)
    is_signed = models.BooleanField(default=False)
    lender_bucket_xid = models.BigIntegerField(null=True, blank=True)

    objects = LenderBucketManager()

    class Meta(object):
        db_table = 'lender_bucket'

    def approved(self):
        applications = []
        for application_id in self.application_ids['approved']:
            applications.append(Application.objects.get_or_none(pk=application_id))
        return applications

    def rejected(self):
        applications = []
        for application_id in self.application_ids['rejected']:
            applications.append(Application.objects.get_or_none(pk=application_id))
        return applications

    def total(self):
        return self.total_approved + self.total_rejected

    def generate_xid(self):
        if self.id is None or self.lender_bucket_xid is not None:
            return
        with transaction.atomic():
            xid_lookup = XidLookup.objects.select_for_update().filter(
                is_used_application=False
            ).first()
            if xid_lookup:
                xid_lookup.is_used_application = True
                xid_lookup.save()
            else:
                # We already have a cronjob for pupulating xid_lookup
                last_xid = XidLookup.objects.values_list("xid", flat=True).last()
                if last_xid:
                    xid_lookup = XidLookup.objects.create(
                        xid=last_xid + 1, is_used_application=True
                    )
            if xid_lookup:
                self.lender_bucket_xid = xid_lookup.xid


class FeatureSettingProxy(FeatureSetting):
    class Meta:
        proxy = True
        verbose_name = 'Ftm configuration'

    def __str__(self):
        return self.feature_name


class ApplicationLenderHistory(FollowTheMoneyModel):
    id = models.AutoField(db_column='application_lender_history_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id',
                                blank=True,
                                null=True)
    application = models.ForeignKey('julo.Application',
                                models.DO_NOTHING,
                                db_column='application_id')

    class Meta(object):
        db_table = 'application_lender_history'


class LoanAgreementTemplate(FollowTheMoneyModel):
    id = models.AutoField(db_column='loan_agreement_template_id', primary_key=True)
    lender = models.ForeignKey(
        'LenderCurrent', models.DO_NOTHING, db_column='lender_id',
        blank=True, null=True
    )
    body = models.TextField(
        help_text="For custom parameter text use double bracket \
        and split using dot(.) for table and field.\
        i.e: {{lender.lender_name}}"
    )
    is_active = models.BooleanField(default=False)
    agreement_type = models.CharField(max_length=100, default=LoanAgreementType.GENERAL)

    class Meta(object):
        db_table = 'loan_agreement_template'
        unique_together = ('lender', 'agreement_type',)


class LenderApproval(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_approval_id', primary_key=True)
    partner = models.OneToOneField('julo.Partner',
                                models.DO_NOTHING,
                                db_column='partner_id')
    is_auto = models.BooleanField(default=False)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    delay = models.TimeField(blank=True, null=True)
    expired_in = models.TimeField(blank=True, null=True)
    expired_start_time = models.TimeField(blank=True, null=True)
    expired_end_time = models.TimeField(blank=True, null=True)
    is_endless = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'lender_approval'

    def __str__(self):
        return self.partner.name

    @property
    def formated_start_date(self):
        return self.start_date.strftime("%Y/%m/%d %H:%M:%S") if self.start_date else ''

    @property
    def formated_end_date(self):
        return self.end_date.strftime("%Y/%m/%d %H:%M:%S") if self.end_date else ''

    @property
    def formated_expired_start_time(self):
        return self.expired_start_time.strftime("%H:%M:%S") if self.expired_start_time else ''

    @property
    def formated_expired_end_time(self):
        return self.expired_end_time.strftime("%H:%M:%S") if self.expired_end_time else ''


class LenderApprovalTransactionMethod(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_approval_transaction_method_id', primary_key=True)
    lender_approval = models.ForeignKey(
        'LenderApproval',
        models.DO_NOTHING,
        db_column='lender_approval_id'
    )
    transaction_method = models.ForeignKey(
        'payment_point.TransactionMethod',
        models.DO_NOTHING,
        db_column='transaction_method_id'
    )
    delay = models.TimeField()

    class Meta:
        db_table = 'lender_approval_transaction_method'
        unique_together = (("lender_approval", "transaction_method"),)


class LenderCurrent(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_id', primary_key=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL,
                                  on_delete=models.CASCADE,
                                  db_column='auth_user_id',
                                  blank=True,
                                  null=True)

    lender_status = models.TextField(default="unprocessed")
    lender_name = models.TextField()

    poc_name = models.TextField()
    poc_position = models.TextField(max_length=100, null=True, blank=True)
    poc_email = models.TextField()
    poc_phone = PhoneNumberField()

    lender_display_name = models.TextField(null=True, blank=True)
    lender_address = models.TextField()
    lender_address_city = models.TextField(null=True, blank=True)
    lender_address_province = models.TextField(null=True, blank=True)
    business_type = models.TextField(max_length=100, null=True, blank=True)
    source_of_fund = models.TextField()
    pks_number = models.TextField()
    service_fee = models.FloatField()
    addendum_number = models.TextField(blank=True, null=True)
    insurance = models.ForeignKey('LenderInsurance',
                                models.DO_NOTHING,
                                db_column='lender_insurance_id',
                                blank=True,
                                null=True)
    company_name = models.TextField(null=True, blank=True)
    license_number = models.TextField(null=True, blank=True)
    xfers_token = models.TextField(max_length=100, null=True, blank=True)

    is_master_lender = models.NullBooleanField(default=False)
    is_manual_lender_balance = models.NullBooleanField(default=False)
    is_low_balance_notification = models.NullBooleanField(default=False)
    is_xfers_lender_flow = models.NullBooleanField(default=False)
    is_bss_balance_include = models.NullBooleanField(default=False)
    is_only_escrow_balance = models.NullBooleanField(default=False)
    is_pre_fund_channeling_flow = models.NullBooleanField(default=False)
    minimum_balance = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'lender'

    def __str__(self):
        return self.lender_name

    def get_document(self, image_type):
        return Document.objects.filter(document_source=self.id,
            document_type=image_type).order_by('-id').last()

    def npwp(self):
        return self.get_document('npwp')

    def akta(self):
        return self.get_document('akta')

    def tdp(self):
        return self.get_document('tdp')

    def siup(self):
        return self.get_document('siup')

    def nib(self):
        return self.get_document('nib')

    def sk_menteri(self):
        return self.get_document('sk_menteri')

    def skdp(self):
        return self.get_document('skdp')

    @classmethod
    def get_xfers_token_by_lender(cls, lender_id):
        """return xfers token by lender id"""
        lender = cls.objects.get(pk=lender_id)
        if not (lender and lender.xfers_token):
            raise JuloException('Xfer token not found')

        return lender.xfers_token

    @property
    def logo(self):
        image = Image.objects.filter(
            image_source=self.id, image_type="lender_logo"
            ).order_by('-id').last()
        if image:
            return image.image_url

        return None

    @property
    def is_active_lender(self):
        return self.lender_status == LenderStatus.ACTIVE

    @classmethod
    def master_lender(cls):
        lender = cls.objects.filter(is_master_lender=True).first()
        if lender:
            return lender.lender_name
        return None

    @classmethod
    def manual_lender_list(cls):
        return cls.objects.filter(
            is_manual_lender_balance=True
        ).values_list("lender_name", flat=True)

    @classmethod
    def lender_notification_list(cls):
        return cls.objects.filter(
            is_low_balance_notification=True
        ).values_list("lender_name", flat=True)

    @classmethod
    def bss_lender_list(cls):
        return cls.objects.filter(
            is_bss_balance_include=True
        ).values_list("lender_name", flat=True)

    @classmethod
    def escrow_lender_list(cls):
        return cls.objects.filter(is_only_escrow_balance=True).values_list("lender_name", flat=True)


class LenderTransactionType(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_transaction_type_id', primary_key=True)
    transaction_type = models.TextField()

    class Meta(object):
        db_table = 'lender_transaction_type'


class LenderBalanceCurrent(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_balance_current_id', primary_key=True)
    lender = models.OneToOneField('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id')
    available_balance = models.BigIntegerField(default=0)
    outstanding_principal = models.BigIntegerField(default=0)
    outstanding_interest = models.BigIntegerField(default=0)
    committed_amount = models.BigIntegerField(default=0)
    paid_principal = models.BigIntegerField(default=0)
    paid_interest = models.BigIntegerField(default=0)
    pending_withdrawal = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'lender_balance_current'


class LenderBalanceHistory(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_balance_history_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id')
    snapshot_type = models.TextField(blank=True, null=True)
    available_balance = models.BigIntegerField(default=0)
    outstanding_principal = models.BigIntegerField(default=0)
    outstanding_interest = models.BigIntegerField(default=0)
    committed_amount = models.BigIntegerField(default=0)
    paid_principal = models.BigIntegerField(default=0)
    paid_interest = models.BigIntegerField(default=0)
    pending_withdrawal = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'lender_balance_history'


class LenderTransaction(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_transaction_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id')
    lender_balance_current = models.ForeignKey('LenderBalanceCurrent',
                                models.DO_NOTHING,
                                db_column='lender_balance_current_id')
    transaction_type = models.ForeignKey('LenderTransactionType',
                                models.DO_NOTHING,
                                db_column='lender_transaction_type_id')
    transaction_amount = models.BigIntegerField(default=0)
    transaction_description = models.TextField(blank=True, null=True)

    @property
    def type_transaction(self):
        return self.transaction_type.transaction_type

    class Meta(object):
        db_table = 'lender_transaction'


class LenderTransactionMapping(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_transaction_mapping_id', primary_key=True)
    lender_transaction = models.ForeignKey('LenderTransaction',
                                models.DO_NOTHING,
                                db_column='lender_transaction_id',
                                blank=True,
                                null=True)
    lender_withdrawal = models.ForeignKey('LenderWithdrawal',
                                models.DO_NOTHING,
                                db_column='lender_withdrawal_id',
                                blank=True,
                                null=True)
    disbursement = models.ForeignKey('disbursement.Disbursement',
                                models.DO_NOTHING,
                                db_column='disbursement_id',
                                blank=True,
                                null=True)
    payment_event = models.ForeignKey('julo.PaymentEvent',
                                models.DO_NOTHING,
                                db_column='payment_event_id',
                                blank=True,
                                null=True)
    old_id = models.BigIntegerField(blank=True, null=True)
    sepulsa_transaction = models.ForeignKey(
        'julo.SepulsaTransaction',
        db_column='sepulsa_transaction_id',
        blank=True,
        null=True,
        related_name='sepulsa_transaction'
    )
    qris_transaction = models.ForeignKey(
        'qris.DokuQrisTransactionPayment',
        db_column='doku_qris_transaction_payment_id',
        blank=True,
        null=True,
        related_name='qris_transaction'
    )
    juloshop_transaction = models.ForeignKey(
        'ecommerce.JuloShopTransaction',
        db_column='juloshop_transaction_id',
        blank=True,
        null=True,
        related_name='juloshop_transaction'
    )
    channeling_transaction = models.ForeignKey(
        'channeling_loan.ChannelingLoanHistory',
        db_column='channeling_history_id',
        blank=True,
        null=True,
        related_name='channeling_transaction'
    )

    class Meta(object):
        db_table = 'lender_transaction_mapping'


class LoanWriteOff(FollowTheMoneyModel):
    id = models.AutoField(db_column='loan_write_off_id', primary_key=True)
    loan = models.ForeignKey(Loan,
                                models.DO_NOTHING,
                                db_column='loan_id',
                                null=False,
                                blank=False)
    wo_period = models.IntegerField(null=True, blank=True, db_index=True)
    wo_date = models.DateField(null=True, blank=True)
    total_paid = models.BigIntegerField(default=0)
    paid_interest = models.BigIntegerField(default=0)
    paid_principal = models.BigIntegerField(default=0)
    paid_latefee = models.BigIntegerField(default=0)
    due_amount = models.BigIntegerField(default=0)
    loan_amount = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'loan_writeoff'


class LenderBankAccount(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_bank_account_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id')
    bank_account_type = models.TextField()
    bank_name = models.TextField()
    account_name = models.TextField()
    account_number = models.TextField()
    bank_account_status = models.TextField()
    name_bank_validation = models.OneToOneField('disbursement.NameBankValidation',
                                                models.DO_NOTHING,
                                                blank=True,
                                                null=True)

    class Meta(object):
        db_table = 'lender_bank_account'


class LenderWithdrawal(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_withdrawal_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                               models.DO_NOTHING,
                               db_column='lender_id')
    withdrawal_amount = models.BigIntegerField(default=0, db_column='withdrawal_amount')
    lender_bank_account = models.ForeignKey('LenderBankAccount',
                                            models.DO_NOTHING,
                                            db_column='lender_bank_account_id')
    bank_reference_code = models.CharField(max_length=100, blank=True, null=True)
    reason = models.CharField(max_length=100, blank=True, null=True)
    retry_times = models.IntegerField(default=0)
    status = models.CharField(max_length=100, choices=LenderWithdrawalStatus.CHOICES,
                              default=LenderWithdrawalStatus.REQUESTED)

    class Meta(object):
        db_table = 'lender_withdrawal'

    def __str__(self):
        return self.lender.lender_name


class LenderRepaymentTransaction(FollowTheMoneyModel):
    id = models.AutoField(db_column='transaction_id', primary_key=True)
    transaction_date = models.DateField()
    reference_id = models.CharField(max_length=20, blank=True, null=True)
    currency_code = models.CharField(max_length=10)
    amount = models.IntegerField()
    beneficiary_account_number = models.CharField(max_length=100)
    beneficiary_bank_code = models.CharField(max_length=20)
    beneficiary_name = models.CharField(max_length=100)
    remark= models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=100, null=True, blank=True)
    response_code = models.CharField(max_length=100, null=True, blank=True)
    additional_info = JSONField(null=True, blank=True)
    group_id = models.CharField(max_length=100, null=True)
    lender_transaction = models.ForeignKey('LenderTransaction',
                                models.DO_NOTHING,
                                db_column='lender_transaction_id',
                                blank=True,
                                null=True)
    transfer_type = models.CharField(max_length=20)
    lender = models.ForeignKey('LenderCurrent',
                               models.DO_NOTHING,
                               db_column='lender_id',
                               blank=True,
                               null=True)
    repayment_type = models.CharField(max_length=100, null=True)

    class Meta(object):
        db_table = 'lender_repayment_transaction'


class LenderDisbursementMethod(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_disbursement_method_id', primary_key=True)
    partner = models.ForeignKey('julo.Partner',
        models.DO_NOTHING, db_column='partner_id')
    product_lines = models.CharField(max_length=100)
    is_bulk = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'lender_disbursement_method'
        unique_together = ('partner', 'product_lines', )

    def __str__(self):
        return self.partner.name


class LenderInsurance(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_insurance_id', primary_key=True)
    name = models.CharField(max_length=250)

    class Meta(object):
        db_table = 'lender_insurance'

    def __str__(self):
        return self.name


class LenderSignature(FollowTheMoneyModel):
    loan = models.OneToOneField('julo.Loan',
        models.DO_NOTHING, db_column='loan_id')
    lender_bucket_xid = models.BigIntegerField(null=True, blank=True)
    signature_method = models.CharField(max_length=100, blank=True, null=True)
    signed_ts = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'lender_signature'


class LenderReversalTransaction(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_reversal_transaction_id', primary_key=True)
    source_lender = models.ForeignKey('LenderCurrent',
                                      models.DO_NOTHING,
                                      db_column='source_lender',
                                      related_name='source_lender',)
    amount = models.IntegerField()
    destination_lender = models.ForeignKey('LenderCurrent',
                                           models.DO_NOTHING,
                                           db_column='destination_lender',
                                           related_name='destination_lender',
                                           blank=True,
                                           null=True)
    bank_name = models.TextField(blank=True, null=True)
    va_number = models.TextField(blank=True, null=True)
    loan_description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=100, default='requested')
    voided_payment_event = models.ForeignKey('julo.PaymentEvent',
                                             models.DO_NOTHING,
                                             db_column='voided_payment_event_id',)
    step = models.IntegerField(null=True, blank=True)
    retry_times = models.IntegerField(default=0)
    is_waiting_balance = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'lender_reversal_transaction'


class LenderReversalTransactionHistory(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_reversal_transaction_history_id', primary_key=True)
    lender_reversal_transaction = models.ForeignKey(
        'LenderReversalTransaction',
        models.DO_NOTHING,)

    method = models.CharField(max_length=50)
    order_id = models.CharField(max_length=100, null=True, blank=True)
    idempotency_id = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(null=True, blank=True, max_length=50)
    reason = models.CharField(max_length=500, null=True, blank=True)
    reference_id = models.CharField(max_length=100, null=True, blank=True)
    step = models.IntegerField(null=True, blank=True)
    amount = models.IntegerField()

    class Meta(object):
        db_table = 'lender_reversal_transaction_history'


class LenderManualRepaymentTracking(FollowTheMoneyModel):
    id = models.AutoField(db_column='lender_manual_repayment_tracking_id', primary_key=True)
    lender_transaction_mapping = models.ForeignKey(
        'LenderTransactionMapping', models.DO_NOTHING, db_column='lender_transaction_mapping_id',
        blank=True, null=True, default=None)
    principal = models.BigIntegerField(default=0)
    interest = models.BigIntegerField(default=0)
    late_fee = models.BigIntegerField(default=0)
    amount = models.BigIntegerField(default=0)
    transaction_type = models.TextField(null=True, blank=True)
    lender = models.ForeignKey(
        'LenderCurrent', models.DO_NOTHING, db_column='lender_id',
        blank=True, null=True, default=None)

    class Meta(object):
        db_table = 'lender_manual_repayment_tracking'


class LoanLenderHistory(FollowTheMoneyModel):
    id = models.AutoField(db_column='loan_lender_history_id', primary_key=True)
    lender = models.ForeignKey('LenderCurrent',
                                models.DO_NOTHING,
                                db_column='lender_id',
                                blank=True,
                                null=True)
    loan = BigForeignKey('julo.Loan',
                         models.DO_NOTHING,
                         db_column='loan_id')

    class Meta(object):
        db_table = 'loan_lender_history'


class SbDailyOspProductLender(models.Model):
    id = BigAutoField(db_column='daily_osp_product_lender_id', primary_key=True)
    day = models.TextField(db_index=True)
    product = models.TextField()
    lender = models.TextField(db_index=True)
    current = models.FloatField()
    dpd1 = models.FloatField()
    dpd30 = models.FloatField()
    dpd60 = models.FloatField()
    dpd90 = models.FloatField()
    dpd120 = models.FloatField()
    dpd150 = models.FloatField()
    dpd180 = models.FloatField()
    npl90 = models.FloatField()

    class Meta(object):
        db_table = '"ana"."daily_osp_product_lender"'
        managed = False


class LenderRepaymentDetailManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderRepaymentDetail(TimeStampedModel):

    id = models.AutoField(db_column='lender_repayment_detail_id', primary_key=True)
    upload_date = models.DateTimeField()
    payment_receipt_id = models.TextField()
    payment_date = models.DateTimeField()
    account_transaction_id = models.BigIntegerField(
        db_column='account_transaction_id', null=True, blank=True
    )

    objects = LenderRepaymentDetailManager()

    class Meta(object):
        db_table = 'lender_repayment_detail'


class LenderRepaymentDetailProcessLog(TimeStampedModel):

    id = models.AutoField(db_column='lender_repayment_detail_process_log_id', primary_key=True)
    file_date = models.DateField()
    status = models.TextField()
    error_detail = models.TextField(null=True, blank=True)

    objects = LenderRepaymentDetailManager()

    class Meta(object):
        db_table = 'lender_repayment_detail_process_log'
