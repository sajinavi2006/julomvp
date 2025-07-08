from __future__ import unicode_literals

from django.db import models
from juloserver.cashback.constants import OverpaidConsts
from juloserver.julo.models import Agent, Application, Customer, CustomerWalletHistory, Image
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import (
    CustomQuerySet,
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class CashbackEarned(TimeStampedModel):
    id = models.AutoField(db_column='cashback_earned_id', primary_key=True)
    current_balance = models.BigIntegerField()
    expired_on_date = models.DateField()
    verified = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'cashback_earned'

    def __str__(self):
        """Visual identification"""
        return "%s. %s" % (self.id, self.expired_on_date)


class CashbackOverpaidVerificationQuerySet(CustomQuerySet):
    def ineligible_cases(self):
        return self.filter(
            status__in=OverpaidConsts.Statuses.INELIGIBLE,
            overpaid_amount__gt=0
        )


class CashbackOverpaidVerificationManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CashbackOverpaidVerificationQuerySet(self.model)

    def get_ineligible_cases(self):
        return self.get_queryset().ineligible_cases()


class CashbackOverpaidVerification(TimeStampedModel):
    id = models.AutoField(db_column='overpaid_case_id', primary_key=True)
    overpaid_amount = models.IntegerField()

    # see OverpaidConsts.Statuses
    status = models.CharField(max_length=100)

    customer = BigForeignKey(
        Customer,
        on_delete=models.DO_NOTHING,
        db_column='customer_id',
    )
    application = BigForeignKey(
        Application,
        on_delete=models.DO_NOTHING,
        db_column='application_id',
    )
    image = BigForeignKey(
        Image,
        on_delete=models.DO_NOTHING,
        db_column='image_id',
        null=True,
        blank=True,
    )
    wallet_history = models.OneToOneField(
        CustomerWalletHistory,
        related_name='overpaid_verification',
        on_delete=models.DO_NOTHING,
        db_column='wallet_history_id',
    )

    objects = CashbackOverpaidVerificationManager()

    class Meta(object):
        db_table = 'cashback_overpaid_verification'


class OverpaidVerifyingHistory(TimeStampedModel):
    id = models.AutoField(db_column='history_id', primary_key=True)
    overpaid_verification = models.ForeignKey(
        CashbackOverpaidVerification,
        related_name='overpaid_history',
        on_delete=models.DO_NOTHING,
        db_column='overpaid_verification_id',
    )
    agent_note = models.CharField(max_length=1000, null=True, blank=True)
    agent = models.ForeignKey(
        Agent,
        db_column='agent_id',
        on_delete=models.DO_NOTHING,
    )
    processed_status = models.CharField(max_length=100)
    error_message = models.CharField(max_length=1000, null=True, blank=True)
    decision = models.CharField(max_length=100, null=True, blank=True)

    class Meta(object):
        db_table = 'overpaid_verifying_history'
