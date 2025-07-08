from __future__ import unicode_literals
from builtins import object
import logging

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.validators import MaxValueValidator
from datetime import datetime, date, timedelta
from django.conf import settings

from .constants import PaylaterConst
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.postgres.fields import JSONField
from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes)
from cuser.fields import CurrentUserField
from juloserver.julo.models import (Skiptrace, SkiptraceResultChoice, StatusLookup)
from juloserver.julocore.data.models import (
    JuloModelManager, GetInstanceMixin, TimeStampedModel, CustomQuerySet
)

logger = logging.getLogger(__name__)

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class LineModelManager(GetInstanceMixin, JuloModelManager):
    pass


class LineModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = LineModelManager()


class StatementQuerySet(CustomQuerySet):
    def not_paid_active(self):
        return self.exclude(
                statement_status_id__in=PaymentStatusCodes.paylater_paid_status_codes()
               ).exclude(customer_credit_limit__customer_credit_status_id=(LoanStatusCodes.INACTIVE,
                                                                 LoanStatusCodes.DRAFT,
                                                                 LoanStatusCodes.PAID_OFF,
                                                                 LoanStatusCodes.RENEGOTIATED))\
                .exclude(is_collection_called=True)


class StatementManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return StatementQuerySet(self.model)

    def list_bucket_group_plus_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now()).date()
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)

        return self.get_queryset().not_paid_active().filter(
            statement_due_date__range=(range2_ago, range1_ago))

    def bucket_list_t0(self):
        today = timezone.localtime(timezone.now())

        return self.get_queryset().not_paid_active().filter(statement_due_date=today)

    def bucket_list_t1_to_t5(self):
        return self.list_bucket_group_plus_with_range(1, 5)

    def bucket_list_t6_to_t14(self):
        return self.list_bucket_group_plus_with_range(6, 14)

    def bucket_list_t15_to_t29(self):
        return self.list_bucket_group_plus_with_range(15, 29)

    def bucket_list_t30_to_t44(self):
        return self.list_bucket_group_plus_with_range(30, 44)

    def bucket_list_t45_to_t59(self):
        return self.list_bucket_group_plus_with_range(45, 59)

    def bucket_list_t60_to_t89(self):
        return self.list_bucket_group_plus_with_range(60, 89)

    def bucket_list_t90plus(self):
        today = timezone.localtime(timezone.now())
        dpd_90_days_ago = today - timedelta(days=90)

        return self.get_queryset().not_paid_active().filter(statement_due_date__lte=dpd_90_days_ago)


class CustomerCreditLimit(LineModel):
    id = models.AutoField(db_column='customer_credit_limit_id', primary_key=True)
    customer = models.OneToOneField('julo.Customer',
                                    on_delete=models.CASCADE,
                                    db_column='customer_id')
    customer_credit_limit = models.BigIntegerField(default=0)
    customer_credit_status = models.ForeignKey('julo.StatusLookup',
                                                    models.DO_NOTHING,
                                                    db_column='status_code')
    customer_credit_active_date = models.DateTimeField(null=True, blank=True)
    credit_score = models.OneToOneField('julo.CreditScore',
                                        models.DO_NOTHING,
                                        db_column='credit_score_id', null=True)

    class Meta(object):
        db_table = 'customer_credit_limit'


class StatementLock(LineModel):
    id = models.AutoField(primary_key=True)
    statement = models.OneToOneField('Statement',
                                    on_delete=models.CASCADE,
                                    db_column='statement_id',
                                    null=True, blank=True)
    agent = models.ForeignKey(User, models.DO_NOTHING, db_column='agent_id')
    is_locked = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'statement_lock'


class StatementLockHistory(LineModel):
    id = models.AutoField(primary_key=True)
    statement = models.ForeignKey('Statement', models.DO_NOTHING,
                                    db_column='statement_id',
                                    null=True, blank=True)
    agent = models.ForeignKey(User, models.DO_NOTHING,
                                db_column='agent_id')
    is_locked = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'statement_lock_history'


class AccountCreditLimit(LineModel):
    id = models.AutoField(db_column='account_credit_limit_id', primary_key=True)
    customer_credit_limit = models.ForeignKey('CustomerCreditLimit',
                                              on_delete=models.CASCADE,
                                              db_column='customer_credit_limit_id')
    account_credit_limit = models.BigIntegerField(default=0)
    available_credit_limit = models.BigIntegerField(default=0)
    account_credit_status = models.ForeignKey('julo.StatusLookup',
                                                   models.DO_NOTHING,
                                                   db_column='status_code')
    account_credit_active_date = models.DateTimeField(null=True, blank=True)
    callback_url = models.CharField(max_length=500, null=True, blank=True)
    agreement_accepted_ts = models.DateTimeField(null=True, blank=True)
    callback_response = JSONField(null=True, blank=True)
    scrap_data_uploaded = models.BooleanField(default=False)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING,
                                db_column='partner_id',
                                blank=True,
                                null=True)

    class Meta(object):
        db_table = 'account_credit_limit'

    @property
    def used_credit_limit(self, statement=None):
        if not statement:
            last_statement = self.statement_set.exclude(
                statement_status_id__gte=PaymentStatusCodes.PAID_ON_TIME).order_by('id').last()
        else:
            last_statement = statement

        if last_statement:
            used_limit = last_statement.statement_total_due_amount - last_statement.statement_interest_amount - last_statement.statement_late_fee_amount

            return used_limit

        return 0

    @property
    def unused_credit_limit(self, statement=None):
        used_credit_limit = self.used_credit_limit(statement)

        return int(self.account_credit_limit) - int(used_credit_limit)

    def update_available_credit_limit(self, transaction):
        if transaction.transaction_type == 'credit':
            # don't update limit when refund after paid off
            if transaction.transaction_description == 'payment':
                statement = transaction.statement
                add_amount = transaction.transaction_amount - statement.statement_interest_amount - statement.statement_late_fee_amount
                self.available_credit_limit += add_amount
            elif transaction.transaction_description == 'refund':
                self.available_credit_limit += transaction.transaction_amount
        elif transaction.transaction_type == 'debit':
            self.available_credit_limit -= transaction.transaction_amount


class TransactionOne(LineModel):
    TRANSACTION_TYPE_CHOICES = (('Debit', 'debit'),
                                ('Credit', 'credit'))
    id = models.AutoField(db_column='transaction_one_id', primary_key=True)

    # i think relation to customer_credit_limit better than relation to customer
    # because they are one on one
    customer_credit_limit = models.ForeignKey('CustomerCreditLimit',
                                              on_delete=models.CASCADE,
                                              db_column='customer_credit_limit_id')
    account_credit_limit = models.ForeignKey('AccountCreditLimit',
                                             models.DO_NOTHING,
                                             db_column='account_credit_limit_id')
    invoice = models.ForeignKey('Invoice',
                                models.DO_NOTHING,
                                db_column='invoice_id', null=True, blank=True)
    invoice_detail = models.ForeignKey('InvoiceDetail',
                                        models.DO_NOTHING,
                                        db_column='invoice_detail_id',
                                        null=True,
                                        blank=True)
    statement = models.ForeignKey('Statement',
                                  models.DO_NOTHING,
                                  db_column='statement_id')
    transaction_type = models.CharField(max_length=100, choices=TRANSACTION_TYPE_CHOICES,)
    transaction_date = models.DateTimeField(default=timezone.now)
    transaction_amount = models.FloatField()
    transaction_status = models.CharField(max_length=100)
    transaction_description = models.TextField(null=True, blank=True)
    disbursement_amount = models.BigIntegerField(default=0)
    disbursement = models.ForeignKey('disbursement.Disbursement',
                                     models.DO_NOTHING,
                                     db_column='disbursement_id',
                                     null=True,
                                     blank=True)

    class Meta(object):
        db_table = 'transaction_one'


class Statement(TimeStampedModel):
    id = models.AutoField(db_column='statement_id', primary_key=True)
    customer_credit_limit = models.ForeignKey('CustomerCreditLimit',
                                              on_delete=models.CASCADE,
                                              db_column='customer_credit_limit_id')
    account_credit_limit = models.ForeignKey('AccountCreditLimit',
                                             models.DO_NOTHING,
                                             db_column='account_credit_limit_id')
    statement_due_date = models.DateField(null=True, blank=True)
    statement_due_amount = models.BigIntegerField()
    statement_interest_amount = models.BigIntegerField()
    statement_principal_amount = models.BigIntegerField()
    statement_transaction_fee_amount = models.BigIntegerField()
    statement_late_fee_amount = models.BigIntegerField(default=0)
    statement_late_fee_applied = models.IntegerField(default=0)
    statement_paid_date = models.DateField(null=True, blank=True)
    statement_paid_interest = models.BigIntegerField(default=0)
    statement_paid_principal = models.BigIntegerField(default=0)
    statement_paid_late_fee = models.BigIntegerField(default=0)
    statement_paid_transaction_fee = models.BigIntegerField(default=0)
    statement_paid_amount = models.BigIntegerField(default=0)
    statement_status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='statement_status_code')
    is_collection_called = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'statement'

    DUE_SOON_DAYS = 3

    objects = StatementManager()

    @property
    def paid_late_days(self):
        if self.statement_due_date is None or self.statement_paid_date is None:
            days = 0
        else:
            time_delta = self.statement_paid_date - self.statement_due_date
            days = time_delta.days
        logger.debug({'paid_late_days': days})
        return days

    @property
    def total_debt(self):
        debt = self.transactionone_set.filter(transaction_type='debit').exclude(
            transaction_description__in=['late_fee', 'waive_late_fee_void']).aggregate(models.Sum('transaction_amount'))

        if not debt['transaction_amount__sum']:
            debt['transaction_amount__sum'] = 0
        return debt['transaction_amount__sum']

    @property
    def total_credit(self):
        credit = self.transactionone_set.filter(transaction_type='credit').exclude(
            transaction_description__in=['payment', 'refund_paid', 'late_fee_void', 'waive_late_fee']).aggregate(
            models.Sum('transaction_amount'))

        if not credit['transaction_amount__sum']:
            credit['transaction_amount__sum'] = 0
        return credit['transaction_amount__sum']

    @property
    def total_payments(self):
        payment = self.transactionone_set.filter(transaction_type='credit',
                                                 transaction_description='payment').aggregate(
            models.Sum('transaction_amount'))

        if not payment['transaction_amount__sum']:
            payment['transaction_amount__sum'] = 0
        return payment['transaction_amount__sum']

    @property
    def total_refund(self):
        refund = self.transactionone_set.filter(transaction_type='credit',
                                                transaction_description='refund').aggregate(
            models.Sum('transaction_amount'))

        if not refund['transaction_amount__sum']:
            refund['transaction_amount__sum'] = 0
        return refund['transaction_amount__sum']

    @property
    def statement_total_due_amount(self):
        total = self.total_debt - self.total_credit + self.statement_interest_amount + self.statement_late_fee_amount

        return total

    @property
    def due_late_days(self):
        """
        Negative value means it's not due yet. 0 means due today. Positive
        value means due is late.
        """
        if self.statement_due_date is None:
            days = 0
        else:
            time_delta = date.today() - self.statement_due_date
            days = time_delta.days

        return days

    def change_status(self, status_code):
        previous_status = self.statement_status
        new_status = StatusLookup.objects.get(status_code=status_code)
        self.statement_status = new_status
        logger.info({
            'previous_status': previous_status,
            'new_status': new_status,
            'action': 'changing_status'
        })

    def update_statement_amount(self, transaction):
        if transaction.transaction_type == 'credit':
            if transaction.transaction_description == 'refund':
                self.statement_due_amount -= transaction.transaction_amount
                self.statement_principal_amount -= transaction.transaction_amount
            elif transaction.transaction_description == 'refund_paid':
                # do nothing to statement when refund after paid off
                pass
            elif transaction.transaction_description == 'payment':
                self.statement_paid_amount += transaction.transaction_amount
                self.statement_paid_date = transaction.transaction_date

                if self.statement_due_amount == self.statement_paid_amount:
                    self.statement_paid_late_fee = self.statement_late_fee_amount
                    self.statement_paid_interest = self.statement_interest_amount
                    self.statement_paid_principal = self.statement_principal_amount
                    self.statement_paid_transaction_fee = self.statement_transaction_fee_amount

        elif transaction.transaction_type == 'debit':
            if transaction.transaction_description == 'invoice':
                self.statement_due_amount += transaction.transaction_amount
                self.statement_principal_amount += transaction.disbursement_amount
                self.statement_transaction_fee_amount += transaction.invoice.transaction_fee_amount

    def update_status_based_on_due_date(self):
        updated = False
        due_late_days = self.due_late_days

        if due_late_days is None:
            return updated

        if due_late_days < -self.DUE_SOON_DAYS:
            if self.statement_status != StatusLookup.PAYMENT_NOT_DUE_CODE:
                self.change_status(StatusLookup.PAYMENT_NOT_DUE_CODE)
                updated = True
        elif due_late_days < 0:
            if self.statement_status != StatusLookup.PAYMENT_DUE_IN_3_DAYS_CODE:
                self.change_status(StatusLookup.PAYMENT_DUE_IN_3_DAYS_CODE)
                updated = True
        elif due_late_days == 0:
            if self.statement_status != StatusLookup.PAYMENT_DUE_TODAY_CODE:
                self.change_status(StatusLookup.PAYMENT_DUE_TODAY_CODE)
                updated = True
        elif due_late_days < 5:
            if self.statement_status != StatusLookup.PAYMENT_1DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_1DPD_CODE)
                updated = True
        elif due_late_days < 30:
            if self.statement_status != StatusLookup.PAYMENT_5DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_5DPD_CODE)
                updated = True
        elif due_late_days < 60:
            if self.statement_status != StatusLookup.PAYMENT_30DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_30DPD_CODE)
                updated = True
        elif due_late_days < 90:
            if self.statement_status != StatusLookup.PAYMENT_60DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_60DPD_CODE)
                updated = True
        elif due_late_days < 120:
            if self.statement_status != StatusLookup.PAYMENT_90DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_90DPD_CODE)
                updated = True
        elif due_late_days < 150:
            if self.statement_status != StatusLookup.PAYMENT_120DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_120DPD_CODE)
                updated = True
        elif due_late_days < 180:
            if self.statement_status != StatusLookup.PAYMENT_150DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_150DPD_CODE)
                updated = True
        else:
            if self.statement_status != StatusLookup.PAYMENT_180DPD_CODE:
                self.change_status(StatusLookup.PAYMENT_180DPD_CODE)
                updated = True

        return updated

    def total_refund_by_invoces(self, invoice=None):
        filter_refund = dict(
            transaction_type='credit',
            transaction_description='refund'
        )

        filter_refund_paid = dict(
            transaction_type='credit',
            transaction_description='refund_paid'
        )

        if invoice:
            filter_refund.update(invoice=invoice)
            filter_refund_paid.update(invoice=invoice)

        refund = self.transactionone_set.filter(**filter_refund).aggregate(
            models.Sum('transaction_amount'))

        refund_paid = self.transactionone_set.filter(**filter_refund_paid).aggregate(
            models.Sum('transaction_amount'))

        if not refund['transaction_amount__sum']:
            refund['transaction_amount__sum'] = 0
        if not refund_paid['transaction_amount__sum']:
            refund_paid['transaction_amount__sum'] = 0

        return refund['transaction_amount__sum'] + refund_paid['transaction_amount__sum']


class Invoice(LineModel):
    id = models.AutoField(db_column='invoice_id', primary_key=True)
    customer_credit_limit = models.ForeignKey('CustomerCreditLimit',
                                              on_delete=models.CASCADE,
                                              db_column='customer_credit_limit_id')
    account_credit_limit = models.ForeignKey('AccountCreditLimit',
                                             models.DO_NOTHING,
                                             db_column='account_credit_limit_id')
    customer_xid = models.BigIntegerField()
    invoice_number = models.CharField(max_length=100, db_index=True)
    invoice_date = models.DateTimeField(null=True, blank=True)
    invoice_amount = models.BigIntegerField()
    invoice_due_date = models.DateField(null=True, blank=True)
    transaction_fee_amount = models.BigIntegerField()
    invoice_status = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'invoice'


class InvoiceDetail(LineModel):
    id = models.AutoField(db_column='invoice_detail_id', primary_key=True)
    invoice = models.ForeignKey('Invoice',
                                models.DO_NOTHING,
                                related_name='transactions',
                                db_column='invoice_id')
    partner_transaction_id = models.CharField(max_length=100, db_index=True)
    shipping_address = models.TextField()
    details = JSONField(default=list, blank=True, null=True)
    partner_transaction_status = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'invoice_detail'


class TransactionPaymentDetail(LineModel):
    id = models.AutoField(db_column='transaction_payment_id', primary_key=True)
    transaction = models.OneToOneField('TransactionOne',
                                       models.DO_NOTHING,
                                       db_column='transaction_one_id')
    payment_method_type = models.CharField(max_length=100)
    payment_method_name = models.CharField(max_length=100)
    payment_account_number = models.CharField(max_length=50)
    payment_amount = models.BigIntegerField()
    payment_date = models.DateField()
    payment_ref = models.CharField(max_length=100)

    class Meta(object):
        db_table = 'transaction_payment_detail'


class LoanOne(LineModel):
    id = models.AutoField(db_column='loan_one_id', primary_key=True)
    transaction = models.OneToOneField('TransactionOne',
                                       models.DO_NOTHING,
                                       db_column='transaction_one_id')
    loan_amount = models.BigIntegerField(default=0)
    loan_duration = models.IntegerField(default=1)
    installment_amount = models.BigIntegerField(default=0)
    customer = models.ForeignKey('julo.Customer',
                                 on_delete=models.CASCADE,
                                 db_column='customer_id')
    loan_one_status = models.ForeignKey('julo.StatusLookup',
                                             models.DO_NOTHING,
                                             db_column='status_code')
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING,
                                db_column='partner_id',
                                blank=True,
                                null=True)
    fund_transfer_ts = models.DateTimeField(null=True, blank=True)
    refund_amount = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = 'loan_one'

    def change_status(self, status_code):
        previous_status = self.loan_one_status
        new_status = StatusLookup.objects.get(status_code=status_code)
        self.loan_one_status = new_status
        logger.info({
            'previous_status': previous_status,
            'new_status': new_status,
            'action': 'changing_status'
        })


class PaymentSchedule(LineModel):
    id = models.AutoField(db_column='payment_schedule_id', primary_key=True)
    loan_one = models.ForeignKey('LoanOne',
                                 models.DO_NOTHING,
                                 db_column='loan_one_id')
    due_date = models.DateField(null=True, blank=True)
    due_amount = models.BigIntegerField()
    interest_amount = models.BigIntegerField()
    principal_amount = models.BigIntegerField()
    transaction_fee_amount = models.BigIntegerField()
    late_fee_amount = models.BigIntegerField(default=0)
    late_fee_applied = models.IntegerField(default=0)
    paid_date = models.DateField(null=True, blank=True)
    paid_interest = models.BigIntegerField(default=0)
    paid_principal = models.BigIntegerField(default=0)
    paid_late_fee = models.BigIntegerField(default=0)
    paid_transaction_fee = models.BigIntegerField(default=0)
    paid_amount = models.BigIntegerField(default=0)
    status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, db_column='status_code', null=True, blank=True)
    statement = models.ForeignKey('Statement',
                                  models.DO_NOTHING,
                                  db_column='statement_id')

    class Meta(object):
        db_table = 'payment_schedule'


class TransactionRefundDetail(LineModel):
    id = models.AutoField(db_column='transaction_refund_id', primary_key=True)
    invoice = models.ForeignKey('Invoice',
                                models.DO_NOTHING,
                                db_column='invoice_id')
    invoice_detail = models.ForeignKey('InvoiceDetail',
                                       models.DO_NOTHING,
                                       db_column='invoice_detail_id')
    loan_one = models.ForeignKey('LoanOne',
                                 models.DO_NOTHING,
                                 db_column='loan_one_id')
    transaction = models.OneToOneField('TransactionOne',
                                       models.DO_NOTHING,
                                       db_column='transaction_one_id')
    refund_amount = models.BigIntegerField(default=0)
    disbursement = models.ForeignKey('disbursement.Disbursement',
                                     models.DO_NOTHING,
                                     db_column='disbursement_id',
                                     null=True,
                                     blank=True)

    class Meta(object):
        db_table = 'transaction_refund_detail'


class StatementHistory(LineModel):
    id = models.AutoField(db_column='statement_history_id', primary_key=True)
    statement = models.ForeignKey(
        'Statement', models.DO_NOTHING, db_column='statement_id')

    status_old = models.IntegerField()
    status_new = models.IntegerField()
    # TODO: for some reason the api user is not being captured. Asking its
    # maintainer for help
    changed_by = CurrentUserField(
        related_name="statement_status_changes")

    change_reason = models.TextField(
        default="system_triggered")

    class Meta(object):
        db_table = 'statement_history'


class AccountCreditHistory(LineModel):
    id = models.AutoField(db_column='account_credit_history_id', primary_key=True)
    account_credit = models.ForeignKey(
        'AccountCreditLimit', models.DO_NOTHING, db_column='account_credit_limit_id')

    status_old = models.IntegerField()
    status_new = models.IntegerField()
    # TODO: for some reason the api user is not being captured. Asking its
    # maintainer for help
    changed_by = CurrentUserField(
        related_name="account_credit_status_changes")

    change_reason = models.TextField(
        default="system_triggered")

    class Meta(object):
        db_table = 'account_credit_history'


class DisbursementSummary(LineModel):
    id = models.AutoField(db_column='disbursement_summary_id', primary_key=True)
    transaction_date = models.DateField()
    transaction_count = models.IntegerField(default=0)
    transaction_ids = JSONField(default=list, blank=True, null=True)
    transaction_amount = models.BigIntegerField(default=0)
    product_line = models.ForeignKey('julo.ProductLine',
                                        models.DO_NOTHING,
                                        db_column='product_line_id',
                                        null=True,
                                        blank=True)
    disbursement = models.OneToOneField('disbursement.Disbursement',
                                        models.DO_NOTHING,
                                        db_column='disbursement_id',
                                        null=True,
                                        blank=True)
    partner = models.ForeignKey('julo.Partner',
                                models.DO_NOTHING,
                                db_column='partner_id',
                                blank=True,
                                null=True)

    disburse_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    models.DO_NOTHING,
                                    db_column='disburse_by',
                                    blank=True,
                                    null=True)

    disburse_xid = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'disbursement_summary'
        unique_together = ('transaction_date', 'partner', 'product_line',)


class BukalapakWhitelist(LineModel):
    id = models.AutoField(db_column='bukalapak_whitelist_id', primary_key=True)
    email = models.EmailField(unique=True)
    credit_limit = models.BigIntegerField(default=0)
    probability_fpd = models.FloatField()
    group = models.CharField(max_length=100, null=True, blank=True)
    version = models.CharField(max_length=50, null=True, blank=True)

    class Meta(object):
        db_table = 'bukalapak_whitelist'
        index_together = [('email',)]


class BukalapakCustomerData(LineModel):
    GENDER_CHOICES = (
        ('Pria', 'Pria'),
        ('Wanita', 'Wanita'))

    id = models.AutoField(db_column='bukalapak_customer_data_id', primary_key=True)
    application = models.OneToOneField(
        'julo.Application', models.DO_NOTHING, db_column='application_id',
        null=True, blank=True)

    customer = models.OneToOneField(
        'julo.Customer', models.DO_NOTHING, db_column='customer_id',
        null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    nik = models.CharField(
        max_length=16,
        validators=[
            ascii_validator,
            RegexValidator(
                regex='^[0-9]{16}$',
                message='KTP has to be 16 numeric digits')
        ], blank=True, null=True)
    confirmed_phone = models.CharField(max_length=50, blank=True, null=True)
    fullname = models.CharField(max_length=100, null=True, blank=True)
    birthday = models.DateField(blank=True, null=True)
    gender = models.CharField("Jenis kelamin",
                              choices=GENDER_CHOICES,
                              max_length=10,
                              validators=[ascii_validator],
                              blank=True, null=True)
    account_opening_date = models.DateField(null=True, blank=True)
    birthplace = models.CharField(max_length=100, null=True, blank=True)
    seller_flag = models.CharField(max_length=100, null=True, blank=True)
    identity_type = models.CharField(max_length=100, default="ktp")
    job = models.CharField(max_length=100, null=True, blank=True)
    marital_status = models.CharField(max_length=100, null=True, blank=True)
    reference_date = models.DateField(null=True, blank=True)

    class Meta(object):
        db_table = 'bukalapak_customer_data'


class StatementPtpManager(GetInstanceMixin, JuloModelManager):
    pass


class StatementPtp(TimeStampedModel):
    id = models.AutoField(db_column='statement_ptp_id', primary_key=True)
    statement = models.OneToOneField('Statement',
                                     models.DO_NOTHING,
                                     db_column='statement_id')
    ptp_date = models.DateField()
    ptp_amount = models.BigIntegerField()
    updated_by = CurrentUserField()

    class Meta(object):
        db_table = 'statement_ptp'

    objects = StatementPtpManager()


class StatementNoteManager(GetInstanceMixin, JuloModelManager):
    pass


class StatementNote(TimeStampedModel):
    id = models.AutoField(db_column='statement_note_id', primary_key=True)
    statement = models.ForeignKey('Statement',
                                  models.DO_NOTHING,
                                  db_column='statement_id')
    note_text = models.TextField()
    added_by = CurrentUserField()

    class Meta(object):
        db_table = 'statement_note'

    objects = StatementNoteManager()


class SkipTraceHistoryBl(LineModel):
    id = models.AutoField(db_column='skiptrace_history_bl_id', primary_key=True)
    skiptrace = models.ForeignKey(Skiptrace, models.DO_NOTHING,
                                        db_column='skiptrace_id')
    account_credit_limit = models.ForeignKey('AccountCreditLimit',
                                                models.DO_NOTHING,
                                                db_column='account_credit_limit_id')
    statement = models.ForeignKey('Statement',
                                    models.DO_NOTHING,
                                    db_column='statement_id',
                                    null=True,
                                    blank=True)
    agent = CurrentUserField()
    call_result = models.ForeignKey(SkiptraceResultChoice, models.DO_NOTHING,
                                        db_column='skiptrace_result_choice_id')

    class Meta(object):
        db_table = 'skiptrace_history_bl'


class StatementEvent(LineModel):
    id = models.AutoField(db_column='statement_event_id', primary_key=True)
    statement = models.ForeignKey(Statement, models.DO_NOTHING, db_column='statement_id')
    event_amount = models.BigIntegerField()
    event_due_amount = models.BigIntegerField()
    event_date = models.DateField()
    event_type = models.CharField(max_length=50)
    added_by = CurrentUserField(related_name="statement_event")
    can_reverse = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'statement_event'


class BukalapakInterest(LineModel):
    id = models.AutoField(db_column='bukalapak_interest_id', primary_key=True)
    last_digit_min = models.IntegerField(default=0)
    last_digit_max = models.IntegerField(default=0)
    interest_rate = models.FloatField()

    class Meta(object):
        db_table = 'bukalapak_interest'


class InitialCreditLimit(LineModel):
    CLUSTER_TYPE_CHOICES = (('Default', 'Default'),
                            ('MVP', 'MVP'),
                            ('Potential MVP', 'Potential MVP'),
                            ('Opportunistic', 'Opportunistic'),
                            ('Churned', 'Churned'))
    id = models.AutoField(db_column='initial_credit_limit_id', primary_key=True)
    cluster_type = models.CharField(choices=CLUSTER_TYPE_CHOICES,
                                    max_length=50,
                                    validators=[ascii_validator])
    score_first = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    score_last = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    initial_credit_limit = models.BigIntegerField(default=0, validators=[MinValueValidator(10000), MaxValueValidator(3000000)])

    class Meta(object):
        db_table = 'initial_credit_limit'
