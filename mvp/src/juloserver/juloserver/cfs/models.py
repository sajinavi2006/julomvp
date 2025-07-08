from django.db import models
from django.contrib.postgres.fields import JSONField

from juloserver.julo.models import (
    TimeStampedModel, ascii_validator, GetInstanceMixin, Customer, CustomerWalletHistory,
    Agent, Loan, Payment
)
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import JuloModelManager, CustomQuerySet


class CfsAction(TimeStampedModel):
    id = models.BigIntegerField(db_column='cfs_action_id', primary_key=True)
    action_code = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    default_expiry = models.BigIntegerField(blank=True, null=True)
    display_order = models.BigIntegerField(default=0)
    icon = models.CharField(max_length=1000)
    app_link = models.CharField(max_length=255)
    first_occurrence_cashback_amount = models.BigIntegerField(blank=True, null=True)
    repeat_occurrence_cashback_amount = models.BigIntegerField(blank=True, null=True)
    is_need_agent_verify = models.BooleanField(default=False)
    app_version = models.CharField(
        max_length=10, blank=True, null=True, validators=[ascii_validator]
    )
    action_type = models.CharField(max_length=255)
    tag_info = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'cfs_action'


class CfsActionAssignmentManager(GetInstanceMixin, JuloModelManager):
    def latest_assignment_by_customer(self, customer_id, action_id):
        return self.get_queryset().filter(customer_id=customer_id, action_id=action_id).last()


class CfsActionAssignment(TimeStampedModel):
    id = models.AutoField(db_column='cfs_action_assignment_id', primary_key=True)
    repeat_action_no = models.BigIntegerField(blank=False, null=False)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id')
    progress_status = models.BigIntegerField(blank=True, null=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    action = models.ForeignKey(
        CfsAction, models.DO_NOTHING, db_column='cfs_action_id')
    cashback_amount = models.BigIntegerField(blank=True, null=True)
    customer_wallet_history = models.ForeignKey(
        CustomerWalletHistory, models.DO_NOTHING, db_column='customer_wallet_history_id',
        blank=True, null=True)
    extra_data = JSONField(blank=True, null=True)

    objects = CfsActionAssignmentManager()

    class Meta(object):
        db_table = 'cfs_action_assignment'

    @property
    def multiplier(self):
        if (self.extra_data is not None and 'multiplier' in self.extra_data):
            return self.extra_data['multiplier']
        return None


class CfsAssignmentVerificationQuerySet(CustomQuerySet):
    def non_verify(self):
        return self.filter(verify_status__isnull=True)

    def crm(self):
        return self.non_verify()

    def action(self, action_id):
        return self.filter(cfs_action_assignment__action_id=action_id)


class CfsAssignmentVerificationManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CfsAssignmentVerificationQuerySet(model=self.model)

    def crm_queryset(self):
        select_related = [
            'cfs_action_assignment__action',
            'cfs_action_assignment__customer',
            'account',
            'locked_by',
        ]
        return self.get_queryset().crm().select_related(*select_related)


class CfsAssignmentVerification(TimeStampedModel):
    id = models.AutoField(db_column='verification_id', primary_key=True)
    cfs_action_assignment = models.ForeignKey(
        CfsActionAssignment, models.DO_NOTHING, db_column='cfs_action_assignment_id')
    account = models.ForeignKey('account.Account', models.DO_NOTHING, db_column='account_id',
                                blank=True, null=True)
    agent = models.ForeignKey(Agent, models.DO_NOTHING, db_column='agent_id', blank=True, null=True)
    verify_status = models.IntegerField(null=True, blank=True)
    message = models.TextField(null=True, max_length=1000)
    locked_by = models.ForeignKey(Agent, models.DO_NOTHING,
                                  db_column='locked_by_id', blank=True,
                                  null=True, related_name='cfs_assignment_verification_locked')
    extra_data = JSONField(blank=True, null=True)
    monthly_income = models.BigIntegerField(null=True, blank=True)

    objects = CfsAssignmentVerificationManager()

    class Meta(object):
        db_table = 'cfs_assignment_verification'

    @property
    def is_locked(self):
        return self.locked_by_id is not None

    @property
    def locked_by_info(self):
        if self.is_locked:
            return str(self.locked_by)
        return None

    @property
    def is_pending(self):
        return self.verify_status is None


class CfsAddressVerification(TimeStampedModel):
    id = models.AutoField(db_column='verification_id', primary_key=True)
    cfs_action_assignment = models.ForeignKey(
        CfsActionAssignment, models.DO_NOTHING, db_column='cfs_action_assignment_id')
    device_lat = models.FloatField()
    device_long = models.FloatField()
    application_address_lat = models.FloatField()
    application_address_long = models.FloatField()
    distance_in_km = models.FloatField()
    decision = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'cfs_address_verification'


class CfsTier(TimeStampedModel):
    id = models.BigIntegerField(db_column='tier_id', primary_key=True)
    name = models.TextField(null=True, max_length=255)
    point = models.BigIntegerField(blank=True, null=True)
    message = models.TextField(null=True, blank=True)
    icon = models.CharField(null=True, blank=True, max_length=1000)
    description = models.TextField(null=True, max_length=1000)
    cashback_multiplier = models.FloatField(blank=True, null=True)
    referral_bonus = models.BigIntegerField(blank=True, null=True)
    qris = models.BooleanField(default=False)
    ppob = models.BooleanField(default=False)
    ecommerce = models.BooleanField(default=False)
    tarik_dana = models.BooleanField(default=False)
    dompet_digital = models.BooleanField(default=False)
    transfer_dana = models.BooleanField(default=False)
    pencairan_cashback = models.BooleanField(default=False)
    pasca_bayar = models.BooleanField(default=False)
    listrik_pln = models.BooleanField(default=False)
    bpjs_kesehatan = models.BooleanField(default=False)
    tiket_kereta = models.BooleanField(default=False)
    pdam = models.BooleanField(default=False)
    education = models.BooleanField(default=False)
    julo_card = models.BooleanField(default=False)
    balance_consolidation = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'cfs_tier'


class CfsActionPoints(TimeStampedModel):
    id = models.IntegerField(db_column='cfs_action_points_id', primary_key=True)
    description = models.TextField(null=True, blank=True)
    multiplier = models.FloatField(blank=True, null=True)
    floor = models.IntegerField(blank=True, null=True)
    ceiling = models.IntegerField(blank=True, null=True)
    default_expiry = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'cfs_action_points'


class CfsActionPointsAssignment(TimeStampedModel):
    id = models.AutoField(db_column='cfs_action_points_assignment_id', primary_key=True)
    customer_id = models.BigIntegerField(db_column='customer_id')
    loan_id = models.BigIntegerField(db_column='loan_id', null=True, blank=True)
    payment_id = models.BigIntegerField(
        db_column='payment_id', blank=True, null=True
    )
    cfs_action_points_id = models.IntegerField(
        db_column='cfs_action_points_id'
    )
    extra_data = JSONField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    is_processed = models.BooleanField(default=False)
    points_changed = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'cfs_action_points_assignment'
        managed = False


class TotalActionPoints(TimeStampedModel):
    id = models.AutoField(db_column='total_action_points_id', primary_key=True)
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column='customer_id', unique=True)
    point = models.IntegerField(default=0, blank=True, null=True)

    class Meta(object):
        db_table = 'total_action_points'


class TotalActionPointsHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class TotalActionPointsHistory(TimeStampedModel):
    id = models.AutoField(db_column='total_action_points_history_id', primary_key=True)
    customer_id = models.BigIntegerField(db_column='customer_id')
    cfs_action_point_assignment_id = models.IntegerField(
        db_column='cfs_action_points_assignment_id'
    )
    partition_date = models.DateField()
    old_point = models.IntegerField(blank=True, null=True)
    new_point = models.IntegerField(blank=True, null=True)
    change_reason = models.CharField(null=True, blank=True, max_length=255)

    objects = TotalActionPointsHistoryManager()

    class Meta(object):
        db_table = 'total_action_points_history'
        managed = False


class EntryGraduationList(models.Model):
    # this model is only used for retroloading entry level status
    cdate = models.DateTimeField(auto_now_add=True)
    account_id = models.BigIntegerField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    current_set_limit = models.BigIntegerField(null=True, blank=True)
    new_set_limit = models.BigIntegerField(null=True, blank=True)
    new_max_limit = models.BigIntegerField(null=True, blank=True)
    graduation_date = models.DateField(auto_now_add=True)
    graduation_channel = models.CharField(max_length=1000, null=True, blank=True)
    notes = models.CharField(max_length=1000, null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."manual_graduation_history"'
        managed = False


class EasyIncomeEligible(models.Model):
    id = models.AutoField(db_column='easy_income_eligible_id', primary_key=True)
    cdate = models.DateTimeField()
    udate = models.DateTimeField()
    data_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    customer_id = models.IntegerField()
    account_id = models.IntegerField()
    ta_version = models.CharField(max_length=255, null=True, blank=True)
    comms_group = models.CharField(max_length=255, null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."easy_income_eligible"'
        managed = False
