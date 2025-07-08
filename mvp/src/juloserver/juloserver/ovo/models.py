from django.db import models

from juloserver.account_payment.models import AccountPayment
from juloserver.julocore.data.models import GetInstanceMixin, TimeStampedModel, JuloModelManager
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.pii_vault.models import (
    PIIVaultModel,
    PIIVaultModelManager,
)


class PIIType:
    KV = 'kv'
    CUSTOMER = 'cust'


class OvoModelManager(GetInstanceMixin, JuloModelManager):
    pass


class OvoModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = OvoModelManager()


class OvoRepaymentTransaction(OvoModel):
    """Ovo Push to Pay"""
    id = models.AutoField(db_column='ovo_repayment_transaction_id', primary_key=True)
    transaction_id = models.BigIntegerField(blank=True, null=True)
    account_payment_xid = models.ForeignKey(
        AccountPayment, models.DO_NOTHING, to_field='account_payment_xid',
        db_column='account_payment_xid', null=True, blank=True, db_index=True)
    status = models.TextField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    amount = models.BigIntegerField(default=0)
    status_description = models.TextField(null=True, blank=True)
    is_checkout_experience = models.NullBooleanField()

    class Meta(object):
        db_table = 'ovo_repayment_transaction'


class OvoRepaymentTransactionHistory(OvoModel):
    """Ovo Push to Pay"""
    id = models.AutoField(db_column='ovo_repayment_transaction_history_id', primary_key=True)
    ovo_repayment_transaction = models.ForeignKey(
        'OvoRepaymentTransaction', models.DO_NOTHING, db_column='ovo_repayment_transaction_id',
        blank=True, null=True
    )
    field_name = models.TextField()
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()

    class Meta(object):
        db_table = 'ovo_repayment_transaction_history'


class OvoWalletModelManager(GetInstanceMixin, PIIVaultModelManager):
    pass


class OvoWalletAccount(PIIVaultModel):
    """Ovo Tokenization"""

    PII_FIELDS = ['phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'repayment_pii_vault'

    id = BigAutoField(db_column='ovo_wallet_account_id', primary_key=True)
    account_id = models.BigIntegerField(db_column='account_id', null=True, blank=True)
    status = models.CharField(max_length=30)
    access_token = models.TextField(null=True, blank=True)
    access_token_expiry_time = models.DateTimeField(null=True, blank=True)
    refresh_token = models.TextField(null=True, blank=True)
    refresh_token_expiry_time = models.DateTimeField(null=True, blank=True)
    balance = models.BigIntegerField(null=True, blank=True)
    auth_code = models.TextField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)
    phone_number_tokenized = models.TextField(null=True, blank=True)
    max_limit_payment = models.BigIntegerField(null=True, blank=True)
    objects = OvoWalletModelManager()

    class Meta(object):
        db_table = 'ovo_wallet_account'
        managed = False

    def __str__(self):
        return 'id={} account_id={} status={}'.format(self.id, self.account_id, self.status)


class OvoWalletBalanceHistory(OvoModel):
    """Ovo Tokenization"""

    id = BigAutoField(db_column='ovo_wallet_balance_history_id', primary_key=True)
    ovo_wallet_account = models.ForeignKey(
        OvoWalletAccount, models.DO_NOTHING, db_column='ovo_wallet_account_id'
    )
    balance = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'ovo_wallet_balance_history'
        managed = False

    def __str__(self):
        return 'id={} ovo_wallet_account_id={} balance={}'.format(
            self.id, self.ovo_wallet_account_id, self.balance
        )


class OvoWalletTransaction(OvoModel):
    """Ovo Tokenization"""

    id = BigAutoField(db_column='ovo_wallet_transaction_id', primary_key=True)
    ovo_wallet_account = models.ForeignKey(
        OvoWalletAccount, models.DO_NOTHING, db_column='ovo_wallet_account_id'
    )
    account_payment_id = models.BigIntegerField(null=True, blank=True)
    partner_reference_no = models.TextField(unique=True, db_index=True)
    reference_no = models.TextField(null=True, blank=True)
    amount = models.BigIntegerField()
    status = models.CharField(max_length=30)
    status_code = models.CharField(max_length=10)
    status_description = models.TextField(null=True, blank=True)
    vendor = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'ovo_wallet_transaction'
        managed = False

    def __str__(self):
        return 'id={} ovo_wallet_account_id={} partner_reference_no={}'.format(
            self.id, self.ovo_wallet_account_id, self.partner_reference_no
        )
