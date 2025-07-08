from __future__ import unicode_literals

import logging
from builtins import object

from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.models import Application, Bank, Loan
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import (
    CustomQuerySet,
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager

from .constants import DisbursementStatus, DisbursementVendors, NameBankValidationStatus


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


logger = logging.getLogger(__name__)


class NameBankValidationQuerySet(CustomQuerySet):
    def by_method(self, method, date):
        return self.filter(method=method, cdate__date=date)


class NameBankValidationManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return NameBankValidationQuerySet(self.model)

    def get_count_today_by_method(self, method):
        now = timezone.now()
        return self.get_queryset().by_method(method, now.date()).count()


class NameBankValidation(PIIVaultModel):
    PII_FIELDS = ['validated_name', 'mobile_phone', 'name_in_bank']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = models.AutoField(db_column='name_bank_validation_id', primary_key=True)
    bank_code = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    name_in_bank = models.CharField(max_length=100)
    method = models.CharField(max_length=50)
    validation_id = models.CharField(max_length=100, null=True, blank=True)
    validation_status = models.CharField(max_length=20, default=NameBankValidationStatus.INITIATED)
    validated_name = models.CharField(max_length=100, null=True, blank=True)
    mobile_phone = models.CharField(max_length=20)
    reason = models.CharField(max_length=100, null=True, blank=True)
    attempt = models.IntegerField(default=0)
    objects = NameBankValidationManager()
    error_message = models.TextField(blank=True, null=True)
    name_in_bank_tokenized = models.CharField(max_length=225, null=True, blank=True)
    validated_name_tokenized = models.CharField(max_length=225, null=True, blank=True)
    mobile_phone_tokenized = models.CharField(max_length=225, null=True, blank=True)
    bank = models.ForeignKey('julo.Bank', models.DO_NOTHING, db_column='bank_id', null=True)

    class Meta(object):
        db_table = 'name_bank_validation'
        index_together = [('account_number',)]

    def create_history(self, event_type, update_fields):
        not_allowed_fields = ['cdate', 'udate']
        update_fields = [field for field in update_fields if field not in not_allowed_fields]
        data_dict = iter(list(self.__dict__.items()))
        field_changes = dict((key, val) for key, val in data_dict if key in update_fields)
        NameBankValidationHistory.objects.create(name_bank_validation=self,
                                                 event=event_type,
                                                 field_changes=field_changes)

    @property
    def is_success(self):
        return self.validation_status == NameBankValidationStatus.SUCCESS

    @property
    def bank_name(self):
        field_name = '{}_bank_code'.format(self.method.lower())
        filters = {field_name: self.bank_code}
        bank = Bank.objects.filter(**filters).first()
        return bank.bank_name if bank else ''


class DisbursementQuerySet(CustomQuerySet):
    def by_method(self, method, date):
        return self.filter(method=method, cdate__date=date)


class DisbursementManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return DisbursementQuerySet(self.model)

    def get_count_today_by_method(self, method):
        now = timezone.now()
        return self.get_queryset().by_method(method, now).count()

    def checking_statuses_bca_disbursement(self):
        return self.get_queryset().filter(
            disburse_status__in=DisbursementStatus.CHECKING_STATUSES,
            method=DisbursementVendors.BCA,
        )


class Disbursement(TimeStampedModel):
    id = models.AutoField(db_column='disbursement_id', primary_key=True)
    name_bank_validation = models.ForeignKey('NameBankValidation',
                                             on_delete=models.CASCADE,
                                             db_column='name_bank_validation_id',
                                             blank=True,
                                             null=True)
    disbursement_type = models.CharField(default='loan', max_length=10)
    external_id = models.CharField(max_length=50)
    amount = models.BigIntegerField()
    method = models.CharField(max_length=50)
    disburse_id = models.CharField(max_length=100, null=True, blank=True)
    disburse_status = models.CharField(default=DisbursementStatus.INITIATED, max_length=50)
    retry_times = models.IntegerField(default=0)
    reason = models.CharField(max_length=500, null=True, blank=True)
    reference_id = models.CharField(max_length=100, null=True, blank=True)

    # to determine transfer step of xfers flow (1, 2)
    step = models.IntegerField(null=True, blank=True)

    # transfer this amount to JTF from JTP
    original_amount = models.BigIntegerField(null=True)

    objects = DisbursementManager()
    _lender_id = None

    class Meta(object):
        db_table = 'disbursement2'

    def create_history(self, event_type, update_fields):
        not_allowed_fields = ['cdate', 'udate']
        update_fields = [field for field in update_fields if field not in not_allowed_fields]
        data_dict = iter(list(self.__dict__.items()))
        field_changes = dict((key, val) for key, val in data_dict if key in update_fields)
        DisbursementHistory.objects.create(disbursement=self,
                                           event=event_type,
                                           field_changes=field_changes)

    @property
    def lender_id(self):
        if not self._lender_id:
            lender = LenderCurrent.objects.filter(lender_name='jtp').last()
            if lender:
                self._lender_id = lender.id
            loan = Loan.objects.get_or_none(disbursement_id=self.id)
            if loan:
                self._lender_id = loan.lender_id
        return self._lender_id


class NameBankValidationHistoryManager(PIIVaultModelManager):
    pass


class NameBankValidationHistory(PIIVaultModel):
    id = models.AutoField(db_column='name_bank_validation_history_id', primary_key=True)
    name_bank_validation = models.ForeignKey(NameBankValidation,
                                             models.DO_NOTHING,
                                             db_column='name_bank_validation_id')
    event = models.CharField(max_length=50)
    field_changes = JSONField()

    # PII attributes
    field_changes_tokenized = models.TextField(blank=True, null=True)
    PII_FIELDS = ['field_changes']
    PII_TYPE = 'kv'

    objects = NameBankValidationHistoryManager()

    class Meta(object):
        db_table = 'name_bank_validation_history'


class DisbursementHistory(TimeStampedModel):
    id = models.AutoField(db_column='disbursement_history_id', primary_key=True)
    disbursement = models.ForeignKey(Disbursement,
                                     models.DO_NOTHING,
                                     db_column='disbursement_id')
    event = models.CharField(max_length=50)
    field_changes = JSONField()

    class Meta(object):
        db_table = 'disbursement_history'


class BcaTransactionRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class BcaTransactionRecord(TimeStampedModel):
    id = models.AutoField(db_column='bca_transaction_id', primary_key=True)
    transaction_date = models.DateField()
    reference_id = models.CharField(max_length=100)
    currency_code = models.CharField(max_length=10)
    amount = models.IntegerField()
    beneficiary_account_number = models.CharField(max_length=100)
    remark1 = models.CharField(max_length=100)
    status = models.CharField(max_length=100, null=True, blank=True)
    error_code = models.CharField(max_length=50, null=True, blank=True)

    objects = BcaTransactionRecordManager()

    class Meta(object):
        db_table = 'bca_transaction_record2'


class BankNameValidationLogManager(PIIVaultModelManager, GetInstanceMixin, JuloModelManager):
    pass


class BankNameValidationLog(PIIVaultModel):
    PII_FIELDS = ['validated_name', 'validated_name_old']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'loan_pii_vault'
    id = models.AutoField(db_column='bank_validation_log_id', primary_key=True)
    validation_id = models.CharField(max_length=100, null=True, blank=True)
    validation_status = models.CharField(max_length=20, default=NameBankValidationStatus.INITIATED)
    validated_name = models.CharField(max_length=100, null=True, blank=True)
    account_number = models.CharField(max_length=100)
    reason = models.CharField(max_length=100, null=True, blank=True)
    method = models.CharField(max_length=50)
    validation_status_old = models.CharField(max_length=20,
                                             default=NameBankValidationStatus.INITIATED)
    validated_name_old = models.CharField(max_length=100, null=True, blank=True)
    account_number_old = models.CharField(max_length=100, null=True, blank=True)
    reason_old = models.CharField(max_length=100, null=True, blank=True)
    method_old = models.CharField(max_length=50, null=True, blank=True)
    application = models.ForeignKey(Application, models.DO_NOTHING,
                                    db_column='application_id',
                                    blank=True, null=True)
    validated_name_tokenized = models.CharField(max_length=225, null=True, blank=True)
    validated_name_old_tokenized = models.CharField(max_length=225, null=True, blank=True)

    objects = BankNameValidationLogManager()

    class Meta(object):
        db_table = 'bank_name_validation_log'


class Disbursement2HistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class Disbursement2History(TimeStampedModel):
    id = models.AutoField(db_column='disbursement2_history_id', primary_key=True)
    disbursement = models.ForeignKey(Disbursement,
                                     on_delete=models.CASCADE,
                                     db_column='disbursement_id')
    amount = models.BigIntegerField()
    method = models.CharField(max_length=50)
    order_id = models.CharField(max_length=100, null=True, blank=True)
    idempotency_id = models.CharField(max_length=100, null=True, blank=True)
    disburse_status = models.CharField(null=True, blank=True, max_length=50)
    reason = models.CharField(max_length=500, null=True, blank=True)
    reference_id = models.CharField(max_length=100, null=True, blank=True)
    attempt = models.IntegerField(null=True, blank=True)
    step = models.IntegerField(null=True, blank=True)
    transaction_request_ts = models.DateTimeField(null=True, blank=True)
    transaction_response_ts = models.DateTimeField(null=True, blank=True)

    objects = Disbursement2HistoryManager()

    class Meta(object):
        db_table = 'disbursement2_history'


class DailyDisbursementLimitManager(GetInstanceMixin, JuloModelManager):
    pass


class DailyDisbursementLimit(TimeStampedModel):
    id = models.AutoField(db_column='daily_disbursement_limit_id', primary_key=True)
    total_amount = models.BigIntegerField(default=0)
    limit_date = models.DateField(unique=True)

    objects = DailyDisbursementLimitManager()

    class Meta(object):
        db_table = 'daily_disbursement_limit'


class PaymentGatewayCustomerDataLoan(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='payment_gateway_customer_data_loan_id')
    beneficiary_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    disbursement = models.ForeignKey(Disbursement, models.DO_NOTHING, db_column='disbursement_id')
    processed = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'payment_gateway_customer_data_loan'


class DailyDisbursementScoreLimit(TimeStampedModel):
    id = models.AutoField(db_column='daily_disbursement_score_limit_id', primary_key=True)
    total_amount = models.BigIntegerField(default=0)
    limit_date = models.DateField()
    score_type = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    objects = DailyDisbursementLimitManager()

    class Meta(object):
        db_table = 'daily_disbursement_score_limit'
        unique_together = ('limit_date', 'score_type')


class DailyDisbursementLimitWhitelist(TimeStampedModel):
    id = models.AutoField(db_column='daily_disbursement_limit_whitelist_id', primary_key=True)
    customer_id = models.BigIntegerField()
    source = models.TextField(blank=True, null=True)
    user_id = models.BigIntegerField()

    class Meta(object):
        db_table = "daily_disbursement_limit_whitelist"


class DailyDisbursementLimitWhitelistHistory(TimeStampedModel):
    id = models.AutoField(db_column='daily_disbursement_limit_whitelist_id', primary_key=True)
    customer_id = models.BigIntegerField()
    source = models.TextField(blank=True, null=True)
    user_id = models.BigIntegerField()
    start_date = models.DateField()

    class Meta(object):
        db_table = "daily_disbursement_limit_whitelist_history"
