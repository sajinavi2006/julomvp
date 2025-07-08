from builtins import object
from django.db import models

from juloserver.julo.models import GetInstanceMixin, TimeStampedModel, JuloModelManager


class DanaWalletModelManager(GetInstanceMixin, JuloModelManager):
    pass


class DanaWalletModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = DanaWalletModelManager()


class DanaWalletAccount(DanaWalletModel):
    id = models.AutoField(db_column='dana_wallet_account_id', primary_key=True)
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id')
    status = models.CharField(max_length=30)
    access_token = models.TextField(null=True, blank=True)
    access_token_expiry_time = models.DateTimeField(null=True, blank=True)
    refresh_token = models.TextField(null=True, blank=True)
    refresh_token_expiry_time = models.DateTimeField(null=True, blank=True)
    balance = models.BigIntegerField(null=True, blank=True)
    public_user_id = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'dana_wallet_account'

    def __str__(self):
        return 'id={} account_id={} status={}'.format(self.id, self.account_id, self.status)


class DanaWalletTransaction(DanaWalletModel):
    id = models.AutoField(db_column='dana_wallet_transaction_id', primary_key=True)
    dana_wallet_account = models.ForeignKey(
        DanaWalletAccount, models.DO_NOTHING, db_column='dana_wallet_account_id'
    )
    partner_reference_no = models.TextField(unique=True, db_index=True)
    reference_no = models.TextField(null=True, blank=True)
    amount = models.BigIntegerField()
    transaction_status_code = models.CharField(max_length=10, null=True, blank=True)
    transaction_status_description = models.TextField(null=True, blank=True)
    transaction_type = models.TextField()
    payback_transaction = models.ForeignKey(
        'julo.PaybackTransaction', models.DO_NOTHING, db_column='payback_transaction_id'
    )
    redirect_url = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'dana_wallet_transaction'

    def __str__(self):
        return 'id={} dana_wallet_account_id={} partner_reference_no={}'.format(
            self.id, self.dana_wallet_account_id, self.partner_reference_no
        )


class DanaWalletBalanceHistory(DanaWalletModel):
    id = models.AutoField(db_column='dana_wallet_balance_history_id', primary_key=True)
    dana_wallet_account = models.ForeignKey(
        DanaWalletAccount, models.DO_NOTHING, db_column='dana_wallet_account_id'
    )
    balance = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'dana_wallet_balance_history'

    def __str__(self):
        return 'id={} dana_wallet_account_id={} balance={}'.format(
            self.id, self.dana_wallet_account_id, self.balance
        )
