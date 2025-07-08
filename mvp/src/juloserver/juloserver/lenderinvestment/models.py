from __future__ import unicode_literals

from builtins import object
from django.db import models
from juloserver.julocore.data.models import TimeStampedModel, GetInstanceMixin, JuloModelManager
from django.contrib.postgres.fields import JSONField


# Create your models here.
class LenderInvestmentModelManager(GetInstanceMixin, JuloModelManager):
    pass


class LenderInvestmentModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = LenderInvestmentModelManager()


class SbLenderAccount(models.Model):
    id = models.AutoField(db_column='lender_account_id', primary_key=True)
    lender_account_name = models.CharField(null=True, blank=True, max_length=50)
    lender_account_partner = models.CharField(null=True, blank=True, max_length=50)
    lender_account_note = models.TextField(null=True, blank=True)
    cdate = models.DateTimeField(auto_now_add=True)


    class Meta(object):
        db_table = '"sb"."lender_account"'
        managed = False

    def __str__(self):
        return "%s (%s)" % (self.lender_account_partner, self.lender_account_name)


class SbLenderWithdrawBatch(LenderInvestmentModel):
    id = models.AutoField(db_column='lender_withdraw_batch_id', primary_key=True)
    lender_account = models.ForeignKey('SbLenderAccount',
                                        models.DO_NOTHING,
                                        db_column='lender_account_id')
    balance = models.BigIntegerField(default=0)


    class Meta(object):
        db_table = '"sb"."lender_withdraw_batch"'
        managed = False

    def __str__(self):
        return "%s - %s" % (self.lender_account, self.balance)


class SbLenderTransaction(models.Model):
    id = models.AutoField(db_column='lender_transaction_id', primary_key=True)
    lender_withdraw_batch = models.ForeignKey('SbLenderWithdrawBatch',
                                                models.DO_NOTHING,
                                                db_column='lender_withdraw_batch_id')
    amount = models.BigIntegerField(default=0)
    tagged_amount = models.BigIntegerField(default=0)
    transaction_type = models.CharField(null=True, blank=True, max_length=20)
    cdate = models.DateTimeField(auto_now_add=True)


    class Meta(object):
        db_table = '"sb"."lender_transaction"'
        managed = False

    def __str__(self):
        return "%s %s - %s" % (self.lender_withdraw_batch.lender_account,
                                self.transaction_type, self.amount)


class SbLenderLoanLedger(LenderInvestmentModel):
    id = models.AutoField(db_column='lender_loan_ledger_id', primary_key=True)
    lender_withdraw_batch = models.ForeignKey('SbLenderWithdrawBatch',
                                                models.DO_NOTHING,
                                                db_column='lender_withdraw_batch_id')
    loan = models.ForeignKey('julo.Loan',
                            models.DO_NOTHING,
                            db_column='loan_id')
    loan_date = models.DateField()
    loan_status = models.CharField(null=True, blank=True, max_length=50)
    application_xid = models.BigIntegerField(null=True, blank=True)
    osp = models.BigIntegerField(default=0)
    tag_type = models.CharField(null=True, blank=True, max_length=50)

    class Meta(object):
        db_table = '"sb"."lender_loan_ledger"'
        managed = False

    def __str__(self):
        return "%s %s %s - %s" % (self.lender_withdraw_batch.lender_account,
                                self.application_xid, self.tag_type, self.osp)


class SbMintosPaymentList(models.Model):
    id = models.AutoField(db_column='mintos_payment_schedule_id', primary_key=True)
    lender_transaction = models.ForeignKey('SbLenderTransaction',
                                            models.DO_NOTHING,
                                            db_column='lender_transaction_id')
    loan_id = models.BigIntegerField(null=True, blank=True)
    payment_schedule_number = models.IntegerField(null=True, blank=True)
    due_date = models.DateField()
    principal_amount = models.BigIntegerField(null=True, blank=True)
    interest_amount = models.BigIntegerField(null=True, blank=True)
    total_amount = models.BigIntegerField(null=True, blank=True)
    remaining_principal = models.BigIntegerField(null=True, blank=True)
    cdate = models.DateTimeField(auto_now_add=True)

    class Meta(object):
        db_table = '"sb"."mintos_payment_schedule"'
        managed = False

    def __str__(self):
        return "%s %s" % (self.lender_transaction, self.loan_id)


class SbLenderLoanLedgerBackup(LenderInvestmentModel):
    backup_ts = models.DateTimeField(auto_now_add=True)
    lender_withdraw_batch_id = models.IntegerField(null=True, blank=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    loan_date = models.DateField()
    loan_status = models.CharField(null=True, blank=True, max_length=50)
    application_xid = models.BigIntegerField(null=True, blank=True)
    osp = models.BigIntegerField(default=0)
    tag_type = models.CharField(null=True, blank=True, max_length=50)

    class Meta(object):
        db_table = '"sb"."lender_loan_ledger_backup"'
        managed = False

    def __str__(self):
        """Visual identification"""
        return "{}".format(self.lender_withdraw_batch_id)


class ExchangeRate(LenderInvestmentModel):
    id = models.AutoField(db_column='exchange_rate_id', primary_key=True)
    currency = models.CharField(null=True, blank=True, max_length=10)
    sell = models.FloatField(null=True, blank=True)
    buy = models.FloatField(null=True, blank=True)
    rate = models.FloatField(null=True, blank=True)
    source = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'exchange_rates'


class MintosResponseLog(LenderInvestmentModel):
    STATUS_CHOICES = (
        ('failed', 'Failed'),
        ('success', 'Success'))

    id = models.AutoField(db_column='mintos_response_log_id', primary_key=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    api_type = models.CharField(null=True, blank=True, max_length=100)
    http_status_code = models.CharField(null=True, blank=True, max_length=5)
    response = JSONField(null=True, blank=True)
    request = JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    status = models.CharField(null=True, blank=True, max_length=10, choices=STATUS_CHOICES)

    class Meta(object):
        db_table = 'mintos_response_log'


class MintosLoanListStatus(LenderInvestmentModel):
    STATUS_CHOICES = (
        ('Decision', 'Decision'),
        ('Active', 'Active'),
        ('Payout', 'Payout'),
        ('Finished', 'Finished'),
        ('Declined', 'Declined'),
        ('Buyback Manual', 'Buyback Manual'),
    )

    id = models.AutoField(db_column='mintos_loan_list_status_id', primary_key=True)
    mintos_loan_id = models.BigIntegerField(null=True, blank=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    mintos_send_in_ts = models.DateTimeField()
    status = models.CharField(null=True, blank=True, max_length=50, choices=STATUS_CHOICES)
    exchange_rate = models.ForeignKey('ExchangeRate',
                                        models.DO_NOTHING,
                                        db_column='exchange_rate_id',
                                        null=True, blank=True)
    interest_rate_percent = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = 'mintos_loan_list_status'


class MintosQueueStatus(LenderInvestmentModel):
    STATUS_CHOICES = (
        ('loan_sendin', 'loan_sendin'),
        ('payment_sendin', 'payment_sendin'),
        ('rebuy_loan', 'rebuy_loan'))

    id = models.AutoField(db_column='mintos_queue_status_id', primary_key=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    payment_number = models.BigIntegerField(null=True, blank=True)
    queue_type = models.CharField(max_length=50, choices=STATUS_CHOICES, null=True, blank=True)
    queue_status = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'mintos_queue_status'


class SbMintosPaymentSendin(models.Model):
    id = models.AutoField(db_column='mintos_payment_send_in_id', primary_key=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    payment_id = models.BigIntegerField(null=True, blank=True)
    payment_date = models.DateField()
    payment_schedule_number = models.IntegerField(null=True, blank=True)
    principal_amount = models.BigIntegerField(null=True, blank=True)
    interest_amount = models.BigIntegerField(null=True, blank=True)
    remaining_principal = models.BigIntegerField(null=True, blank=True)
    cdate = models.DateTimeField(auto_now_add=True)


    class Meta(object):
        db_table = '"sb"."mintos_payment_send_in"'
        managed = False


class SbMintosBuybackSendin(models.Model):
    id = models.AutoField(db_column='mintos_buyback_send_in_id', primary_key=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    buyback_date = models.DateField()
    purpose = models.CharField(max_length=100, null=True, blank=True)
    buyback_amount = models.BigIntegerField(null=True, blank=True)
    cdate = models.DateTimeField(auto_now_add=True)

    class Meta(object):
        db_table = '"sb"."mintos_buyback_send_in"'
        managed = False


class MintosPaymentSendin(LenderInvestmentModel):
    id = models.AutoField(db_column='mintos_payment_send_in_id', primary_key=True)
    application_xid = models.BigIntegerField(null=True, blank=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    payment_id = models.BigIntegerField(null=True, blank=True)
    payment_date = models.DateField()
    payment_schedule_number = models.IntegerField(null=True, blank=True)
    principal_amount = models.CharField(max_length=50, null=True, blank=True)
    interest_amount = models.CharField(max_length=50, null=True, blank=True)
    total_amount = models.CharField(max_length=50, null=True, blank=True)
    remaining_principal = models.CharField(max_length=50, null=True, blank=True)
    penalty_amount = models.CharField(max_length=50, null=True, blank=True)

    class Meta(object):
        db_table = 'mintos_payment_send_in'


class MintosReport(LenderInvestmentModel):
    id = models.AutoField(db_column='mintos_report_id', primary_key=True)
    filename = models.TextField(unique=True)
    email_date = models.DateField()

    class Meta(object):
        db_table = 'mintos_report'


class MintosReportDetail(LenderInvestmentModel):
    id = models.AutoField(db_column='mintos_report_detail_id', primary_key=True)
    mintos_report = models.ForeignKey('MintosReport',
                                    models.DO_NOTHING,
                                    db_column='mintos_report_id',
                                    null=True, blank=True)
    mintos_id = models.IntegerField(null=True, blank=True, default=None, db_index=True)
    mintos_loan_id = models.CharField(null=True, blank=True, default=None, max_length=255)
    loan_status = models.CharField(null=True, blank=True, default=None, max_length=255, db_index=True)
    loan_originator_id = models.CharField(null=True, blank=True, default=None, max_length=255, db_index=True)
    loan_originator = models.CharField(null=True, blank=True, default=None, max_length=255)
    country = models.CharField(null=True, blank=True, default=None, max_length=255)
    interest_rate = models.FloatField(null=True, blank=True, default=None)
    schedule_entries = models.IntegerField(null=True, blank=True, default=None)
    initial_term = models.IntegerField(null=True, blank=True, default=None)
    remaining_term = models.IntegerField(null=True, blank=True, default=None)
    listed_on = models.DateTimeField(null=True, blank=True, default=None)
    original_principal = models.FloatField(null=True, blank=True, default=None)
    outstanding_principal = models.FloatField(null=True, blank=True, default=None)
    invested = models.FloatField(null=True, blank=True, default=None)
    invested_in_percent = models.FloatField(null=True, blank=True, default=None)
    repaid_principal_to_investors = models.FloatField(null=True, blank=True, default=None)
    acc_interest_investors = models.FloatField(null=True, blank=True, default=None)
    repaid_interest_to_investors = models.FloatField(null=True, blank=True, default=None)
    acc_interest_lenders = models.FloatField(null=True, blank=True, default=None)
    acc_interest_mintos = models.FloatField(null=True, blank=True, default=None)
    payment_status = models.CharField(null=True, blank=True, default=None, max_length=255)
    collateral_value = models.CharField(null=True, blank=True, default=None, max_length=255)
    ltv = models.CharField(null=True, blank=True, default=None, max_length=255)
    collateral_type = models.CharField(null=True, blank=True, default=None, max_length=255)
    listing_status = models.CharField(null=True, blank=True, default=None, max_length=255, db_index=True)
    acc_late_payment_fee_investors = models.FloatField(null=True, blank=True, default=None)
    acc_late_payment_fee_lenders = models.FloatField(null=True, blank=True, default=None)
    currency = models.CharField(null=True, blank=True, default=None, max_length=255)
    loan_type = models.CharField(null=True, blank=True, default=None, max_length=255)
    buyback = models.CharField(null=True, blank=True, default=None, max_length=255)
    loan_originator_account_id = models.CharField(null=True, blank=True, default=None, max_length=255)
    total_invested = models.CharField(null=True, blank=True, default=None, max_length=255)
    finished_at = models.DateTimeField(null=True, blank=True, default=None)
    repurchased_principal_from_investors = models.FloatField(null=True, blank=True, default=None)
    repurchased_interest_from_investors = models.FloatField(null=True, blank=True, default=None)
    bad_debt = models.CharField(null=True, blank=True, default=None, max_length=255)
    buyback_reason = models.CharField(null=True, blank=True, default=None, max_length=255)

    class Meta(object):
        db_table = 'mintos_report_detail'
