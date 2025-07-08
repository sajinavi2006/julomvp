from __future__ import unicode_literals

from django.db import models

from juloserver.julo.models import TimeStampedModel, Customer, RefereeMapping
from juloserver.julocore.customized_psycopg2.models import BigAutoField, BigForeignKey
from juloserver.referral.constants import ReferralBenefitConst, ReferralLevelConst, \
    ReferralPersonTypeConst


# Create your models here.


class ReferralBenefit(TimeStampedModel):
    id = BigAutoField(db_column='referral_benefit_id', primary_key=True)
    benefit_type = models.CharField(
        max_length=255,
        default=ReferralBenefitConst.CASHBACK,
        choices=ReferralBenefitConst.CHOICES
    )
    referrer_benefit = models.PositiveIntegerField(default=0)
    referee_benefit = models.PositiveIntegerField(default=0)
    min_disburse_amount = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'referral_benefit'


class ReferralLevel(TimeStampedModel):
    id = BigAutoField(db_column='referral_level_id', primary_key=True)
    benefit_type = models.CharField(
        max_length=255,
        default=ReferralLevelConst.CASHBACK,
        choices=ReferralLevelConst.CHOICES
    )
    referrer_level_benefit = models.PositiveIntegerField(default=0)
    min_referees = models.PositiveIntegerField(default=0)
    level = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'referral_level'


class ReferralBenefitHistory(TimeStampedModel):
    id = models.AutoField(db_column='history_id', primary_key=True)
    referee_mapping = BigForeignKey(
        RefereeMapping, models.DO_NOTHING, db_column='referee_mapping_id'
    )
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    referral_person_type = models.CharField(max_length=20, choices=ReferralPersonTypeConst.CHOICES)
    benefit_unit = models.CharField(max_length=20, choices=ReferralBenefitConst.CHOICES)
    amount = models.PositiveIntegerField(default=0)

    class Meta(object):
        db_table = 'referral_benefit_history'
