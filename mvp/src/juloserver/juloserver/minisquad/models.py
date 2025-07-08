from __future__ import unicode_literals

from builtins import object
from datetime import date
from datetime import datetime
import collections

from cuser.fields import CurrentUserField
from django.contrib.postgres.fields import JSONField, ArrayField
from django.db import models
from django.db.models import F, Q
from django.conf import settings
from django.contrib.auth.models import Group

from juloserver.julocore.data.models import (
    GetInstanceMixin, JuloModelManager, TimeStampedModel, CustomQuerySet
)
from juloserver.julo.constants import AgentAssignmentTypeConst

from juloserver.julo.models import (
                                    Loan,
                                    Payment,
                                    Customer,
                                    SkiptraceResultChoice,
                                    Application,
                                    ExperimentSetting,
                                    Skiptrace,
                                    )
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.constants import BucketConst
from itertools import chain
from django.utils import timezone
from datetime import timedelta
from .constants import DialerVendor, DialerTaskStatus
from ..julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigAutoField,
    BigOneToOneField,
)
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager
from juloserver.julo.models import PIIType
from juloserver.minisquad.constants import CollectionQueue


class CollectionSquadManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionSquad(TimeStampedModel):
    id = models.AutoField(db_column='collection_squad_id', primary_key=True)
    squad_name = models.CharField(max_length=50, blank=True, null=True)
    group = models.ForeignKey(Group,
                              models.DO_NOTHING,
                              db_column='group_id',
                              blank=True,
                              null=True)

    objects = CollectionSquadManager()

    class Meta(object):
        db_table = 'collection_squad'


class CollectionHistoryQuerySet(CustomQuerySet):
    def get_bucket_1_excluding_ptp(self):
        return self.filter(squad__isnull=True,
                           agent__isnull=True,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_1_ptp_data(self, agent_id):
        return self.filter(squad__isnull=True,
                           last_current_status=True,
                           agent_id=agent_id,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_data_excluding_ptp(self, squad_id):
        return self.filter(squad_id=squad_id,
                           agent__isnull=True,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket4_data_excluding_ptp(self, squad_id):
        return self.filter(squad_id=squad_id,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)\
                   .exclude(is_ptp=True)

    def get_bucket4_data_excluding_ptp_for_agent(self, squad_id, agent_id):
        return self.filter(squad_id=squad_id,
                           agent_id=agent_id,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)\
                   .exclude(is_ptp=True)

    def get_bucket_ptp_data(self, squad_id, agent_id):
        return self.filter(squad_id=squad_id,
                           agent_id=agent_id,
                           is_ptp=True,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_data_excluding_ptp_squads(self, squad_ids):
        return self.filter(squad_id__in=squad_ids,
                           agent__isnull=True,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket4_data_excluding_ptp_squads(self, squad_ids):
        return self.filter(squad_id__in=squad_ids,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)\
                   .exclude(is_ptp=True)

    def get_bucket_non_contact(self, squad_id):
        return self.filter(squad_id=squad_id,
                           last_current_status=True,
                           excluded_from_bucket=True,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_non_contact_squads(self, squad_ids, is_julo_one=False):
        if not is_julo_one:
            return self.filter(squad_id__in=squad_ids,
                               last_current_status=True,
                               excluded_from_bucket=True,
                               payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)
        else:
            return self.filter(squad_id__in=squad_ids,
                               last_current_status=True,
                               excluded_from_bucket=True,
                               account_payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

    def list_bucket_group_with_range(self, range1, range2):
        today = timezone.localtime(timezone.now())

        if today.hour > PaymentStatusCodes.UNCALLED_PAYMENT_HOUR_SHIFT:
            return self.filter(payment__cdate=None)
        else:
            return self.determine_bucket_by_range([range1, range2])

    def get_bucket_1(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_1_DPD['to'])

        return self.filter(payment__due_date__range=[range2_ago, range1_ago])

    def get_bucket_2(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_2_DPD['to'])

        return self.filter(payment__due_date__range=[range2_ago, range1_ago])

    def get_bucket_3(self):
        today = timezone.localtime(timezone.now())
        range1_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_3_DPD['to'])

        return self.filter(payment__due_date__range=[range2_ago, range1_ago])

    def get_bucket_4(self):
        today = timezone.localtime(timezone.now()).date()
        range1_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['from'])
        range2_ago = today - timedelta(days=BucketConst.BUCKET_4_DPD['to'])
        release_date = datetime.strptime(BucketConst.EXCLUDE_RELEASE_DATE, '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(Q(payment__due_date__range=[range2_ago, range1_ago]) |
                           Q(payment__due_date__range=[
                               range2_ago_release_date, range1_ago_release_date
                           ]) &
                           Q(payment__ptp_date__isnull=False) &
                           Q(payment__ptp_date__gte=today))

    def get_bucket_5(self):
        today = timezone.localtime(timezone.now()).date()
        due_date = today - timedelta(days=BucketConst.BUCKET_5_DPD)
        release_date = datetime.strptime(BucketConst.EXCLUDE_RELEASE_DATE, '%Y-%m-%d')
        range1_ago_release_date = release_date - timedelta(days=91)
        range2_ago_release_date = release_date - timedelta(days=100)

        return self.filter(payment__due_date__lte=due_date).exclude(
            Q(payment__due_date__range=[range2_ago_release_date, range1_ago_release_date]) &
            Q(payment__ptp_date__isnull=False) &
            Q(payment__ptp_date__gte=today)
        )

    def determine_bucket_by_range(self, ranges):
        if collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']]):
            return self.get_bucket_1()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']]):
            return self.get_bucket_2()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']]):
            return self.get_bucket_3()
        elif collections.Counter(ranges) == collections.Counter(
                [BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']]):
            return self.get_bucket_4()
        else:
            today = timezone.localtime(timezone.now())
            range1_ago = today - timedelta(days=ranges[0])
            range2_ago = today - timedelta(days=ranges[1])
            return self.filter(payment__due_date__range=[range2_ago, range1_ago])

    def exclude_non_contact_data_in_squad(self, squad_id):
        non_contacted_data_ids = self.get_bucket_non_contact(squad_id)\
            .values_list('id', flat=True)

        return self.exclude(pk__in=(non_contacted_data_ids))

    def exclude_non_contact_data_in_squads(self, squad_ids):
        non_contacted_data_ids = self.get_bucket_non_contact_squads(squad_ids)\
            .values_list('id', flat=True)

        return self.exclude(pk__in=(non_contacted_data_ids))

    def get_bucket_ptp_data_all_agent(self):
        return self.filter(agent__isnull=False,
                           last_current_status=True,
                           excluded_from_bucket=False,
                           payment__payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                           is_ptp=True,
                           cdate__date__gte=date(2020, 5, 27))

    def get_bucket_t1_to_t4(self):
        return self.list_bucket_group_with_range(1, 4)

    def get_bucket_t5_to_t10(self):
        return self.list_bucket_group_with_range(5, 10)

    def get_bucket_t11_to_t25(self):
        return self.list_bucket_group_with_range(11, 25)

    def get_bucket_t26_to_t40(self):
        return self.list_bucket_group_with_range(26, 40)

    def get_bucket_t11_to_t40(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
        )

    def get_bucket_t41_to_t55(self):
        return self.list_bucket_group_with_range(41, 55)

    def get_bucket_t56_to_t70(self):
        return self.list_bucket_group_with_range(56, 70)

    def get_bucket_t41_to_t70(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        )

    def get_bucket_t71_to_t85(self):
        return self.list_bucket_group_with_range(71, 85)

    def get_bucket_t86_to_t100(self):
        return self.list_bucket_group_with_range(86, 100)

    def get_bucket_t71_to_t90(self):
        return self.list_bucket_group_with_range(
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
        )


class CollectionHistoryManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CollectionHistoryQuerySet(self.model)

    def not_paid_active(self):
        """ To Exclude is_restructured True, since query for implement status code
        lt 330 already done with other queryset get_bucket* """
        return self.get_queryset().exclude(payment__is_restructured=True)

    # NOTE: reserve for future use incase bucket 1 become minisquad also
    # def get_bucket_t1_to_t4(self):
    #     return self.get_queryset()\
    #                .get_bucket_1_excluding_ptp()\
    #                .get_bucket_t1_to_t4()

    # def get_bucket_t5_to_t10(self):
    #     return self.get_queryset()\
    #                .get_bucket_1_excluding_ptp()\
    #                .get_bucket_t5_to_t10()

    # def get_bucket_1_ptp(self, agent_id):
    #     return self.get_queryset()\
    #                .get_bucket_1_ptp_data(agent_id)

    # def get_bucket_1_wa(self, agent_id):
    #     return self.get_queryset()\
    #                .get_bucket_1_excluding_ptp()\
    #                .filter(payment__is_whatsapp=True)

    # def get_bucket_t0(self):
    #     today = timezone.localtime(timezone.now()).date()

    #     return self.get_queryset()\
    #                .get_bucket_1_excluding_ptp()\
    #                .filter(payment__due_date=today)

    # def get_bucket_tminus1(self):
    #     tminus1 = timezone.localtime(timezone.now()).date() + timedelta(days=1)

    #     return self.get_queryset()\
    #                .get_bucket_1_excluding_ptp()\
    #                .filter(payment__due_date=tminus1)

    def get_bucket_ptp(self, squad_id, agent_id):
        return self.not_paid_active()\
                   .get_bucket_ptp_data(squad_id, agent_id)

    def get_bucket_wa(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .filter(payment__is_whatsapp=True)

    def get_bucket_ignore_called(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .filter(loan__is_ignore_calls=True)

    def get_bucket_t11_to_t25(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t11_to_t25()

    def get_bucket_t26_to_t40(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t26_to_t40()

    def get_bucket_t11_to_t40(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t11_to_t40().exclude(loan__ever_entered_B5=True)

    def get_bucket_t11_to_t40_all_squad(self, squad_ids, experiment_setting):
        if experiment_setting:
            centerix_experiment_criteria = experiment_setting.criteria[DialerVendor.CENTERIX]

            return self.get_queryset()\
                       .get_bucket_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t11_to_t40()\
                       .annotate(last_two_digit_loan_id=F('loan_id') % 100)\
                       .filter(last_two_digit_loan_id__range=centerix_experiment_criteria)
        else:
            return self.get_queryset()\
                       .get_bucket_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t11_to_t40()

    def get_bucket_t41_to_t55(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t41_to_t55()

    def get_bucket_t56_to_t70(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t56_to_t70()

    def get_bucket_t41_to_t70(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t41_to_t70().exclude(loan__ever_entered_B5=True)

    def get_bucket_t41_to_t70_all_squad(self, squad_ids, experiment_setting):
        if experiment_setting:
            centerix_experiment_criteria = experiment_setting.criteria[DialerVendor.CENTERIX]

            return self.get_queryset()\
                       .get_bucket_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t41_to_t70()\
                       .annotate(last_two_digit_loan_id=F('loan_id') % 100)\
                       .filter(last_two_digit_loan_id__range=centerix_experiment_criteria)
        else:
            return self.get_queryset()\
                       .get_bucket_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t41_to_t70()

    def get_bucket_t71_to_t85(self, squad_id, agent_id):
        return self.not_paid_active()\
                   .get_bucket4_data_excluding_ptp_for_agent(squad_id, agent_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t71_to_t85()

    def get_bucket_t86_to_t100(self, squad_id, agent_id):
        return self.not_paid_active()\
                   .get_bucket4_data_excluding_ptp_for_agent(squad_id, agent_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t86_to_t100()

    def get_bucket_t71_to_t90(self, squad_id):
        return self.not_paid_active()\
                   .get_bucket4_data_excluding_ptp(squad_id)\
                   .exclude_non_contact_data_in_squad(squad_id)\
                   .get_bucket_t71_to_t90().exclude(loan__ever_entered_B5=True)

    def get_bucket_t71_to_t100_all_squad(self, squad_ids, experiment_setting):
        if experiment_setting:
            centerix_experiment_criteria = experiment_setting.criteria[DialerVendor.CENTERIX]

            return self.get_queryset()\
                       .get_bucket_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t41_to_t70()\
                       .annotate(last_two_digit_loan_id=F('loan_id') % 100)\
                       .filter(last_two_digit_loan_id__range=centerix_experiment_criteria)
        else:
            return self.get_queryset()\
                       .get_bucket4_data_excluding_ptp_squads(squad_ids)\
                       .exclude_non_contact_data_in_squads(squad_ids)\
                       .get_bucket_t71_to_t90()

    def get_bucket_t101plus(self, squad_id):
        t101plus = timezone.localtime(timezone.now()) - timedelta(days=100)

        return self.not_paid_active()\
                   .get_bucket_data_excluding_ptp(squad_id)\
                   .filter(payment__due_date__lt=t101plus)

    def get_bucket_non_contact(self, squad_id):
        return self.not_paid_active().get_bucket_non_contact(squad_id)

    def get_bucket_non_contact_squads(self, squad_ids, is_julo_one=False):
        return self.not_paid_active().get_bucket_non_contact_squads(
            squad_ids,
            is_julo_one)

    def get_bucket_ptp_data_all_agent(self):
        return self.not_paid_active().get_bucket_ptp_data_all_agent()


class CollectionHistory(TimeStampedModel):
    """
        Table that store informations of payments on squad level
    """
    id = models.AutoField(db_column='collection_history_id', primary_key=True)
    customer = models.ForeignKey(Customer,
                                 models.DO_NOTHING,
                                 db_column='customer_id',
                                 blank=True,
                                 null=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    payment = models.ForeignKey(Payment,
                                models.DO_NOTHING,
                                db_column='payment_id',
                                blank=True,
                                null=True)
    squad = models.ForeignKey(CollectionSquad,
                              models.DO_NOTHING,
                              db_column='squad_id',
                              blank=True,
                              null=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              models.DO_NOTHING,
                              db_column='agent_id',
                              blank=True,
                              null=True)
    call_result = models.ForeignKey(SkiptraceResultChoice,
                                    models.DO_NOTHING,
                                    db_column='call_result_id',
                                    blank=True,
                                    null=True)
    last_current_status = models.BooleanField(default=True)
    excluded_from_bucket = models.BooleanField(default=False)
    is_ptp = models.BooleanField(default=False)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    objects = CollectionHistoryManager()

    class Meta(object):
        db_table = 'collection_history'


class CollectionSquadAssignment(TimeStampedModel):
    squad = models.ForeignKey(CollectionSquad,
                              models.DO_NOTHING,
                              db_column='squad_id',
                              blank=True,
                              null=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              models.DO_NOTHING,
                              db_column='agent_id',
                              blank=True,
                              null=True)
    username = models.CharField(max_length=100, blank=True, null=True)
    bucket_name = models.CharField(max_length=100, blank=True, null=True)

    class Meta(object):
        db_table = 'collection_squad_assignment'


class CommissionLookup(TimeStampedModel):
    id = models.AutoField(db_column='commission_lookup_id', primary_key=True)
    payment = models.ForeignKey(Payment,
                                models.DO_NOTHING,
                                db_column='payment_id',
                                blank=True,
                                null=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    payment_amount = models.BigIntegerField(default=0)
    credited_amount = models.BigIntegerField(default=0)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              models.DO_NOTHING,
                              db_column='agent_id',
                              blank=True,
                              null=True)
    squad = models.ForeignKey(CollectionSquad,
                              models.DO_NOTHING,
                              db_column='squad_id',
                              blank=True,
                              null=True)
    collected_by = models.TextField()
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'commission_lookup'


class SentToCenterixLog(TimeStampedModel):
    id = models.AutoField(db_column='sent_to_centerix_log_id', primary_key=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id')
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    bucket = models.TextField()
    sorted_by_collection_model = models.NullBooleanField()

    class Meta(object):
        db_table = 'sent_to_centerix_log'


class VendorQualityExperiment(TimeStampedModel):
    id = models.AutoField(db_column='vendor_quality_experiment_id', primary_key=True)
    loan = models.ForeignKey(
        Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    bucket = models.TextField()
    experiment_group = models.TextField()
    experiment_setting = models.ForeignKey(
        ExperimentSetting, models.DO_NOTHING, db_column='experiment_setting_id')
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING, db_column='account_payment_id',
        blank=True, null=True
    )

    class Meta(object):
        db_table = 'vendor_quality_experiment'


class DialerTask(TimeStampedModel):
    id = models.AutoField(db_column='dialer_task_id', primary_key=True)
    vendor = models.CharField(max_length=100, default='Intelix')
    type = models.CharField(max_length=100)
    status = models.CharField(max_length=100, default=DialerTaskStatus.INITIATED)
    retry_count = models.IntegerField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    processed_by = models.TextField(
        blank=True, null=True, default=DialerTaskStatus.DIALER_TASK_INTERNAL_SOURCE)

    class Meta(object):
        db_table = 'dialer_task'


class DialerTaskEvent(TimeStampedModel):
    id = models.AutoField(db_column='dialer_task_event_id', primary_key=True)
    dialer_task = models.ForeignKey(DialerTask, models.DO_NOTHING, db_column='dialer_task_id')
    data_count = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=100, default=DialerTaskStatus.INITIATED)
    error = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'dialer_task_event'


class FailedCallResult(TimeStampedModel):
    id = models.AutoField(db_column='failed_call_result_id', primary_key=True)
    call_result = JSONField(blank=True, null=True)
    error = models.TextField()
    dialer_task = models.ForeignKey(
        DialerTask, models.DO_NOTHING,
        db_column='dialer_task_id'
    )

    class Meta(object):
        db_table = 'failed_call_result'


class SentToDialer(TimeStampedModel):
    id = models.AutoField(db_column='sent_to_dialer_id', primary_key=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = models.ForeignKey(
        Payment, models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True)
    bucket = models.TextField()
    sorted_by_collection_model = models.NullBooleanField()
    dialer_task = models.ForeignKey(DialerTask, models.DO_NOTHING, db_column='dialer_task_id')
    # for tracing uid that already deleted from queue
    is_deleted = models.BooleanField(default=False)
    last_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.DO_NOTHING,
        db_column='last_agent_id',
        blank=True,
        null=True)
    last_call_status = models.TextField(blank=True, null=True)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    sort_rank = models.BigIntegerField(blank=True, null=True)
    bttc_class_range = models.TextField(blank=True, null=True)
    task_id = models.TextField(blank=True, null=True, db_index=True)
    phone_number = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'sent_to_dialer'


class NotSentToDialer(TimeStampedModel):
    id = models.AutoField(db_column='not_sent_to_dialer_id', primary_key=True)
    loan = BigForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    payment = BigForeignKey(
        Payment, models.DO_NOTHING,
        db_column='payment_id',
        blank=True,
        null=True)
    bucket = models.TextField()
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    dpd = models.IntegerField(blank=True, null=True)
    is_j1 = models.BooleanField(default=False)
    is_excluded_from_bucket = models.BooleanField(default=False)
    is_paid_off = models.BooleanField(default=False)
    paid_off_timestamp = models.DateTimeField(blank=True, null=True)
    unsent_reason = models.TextField()
    dialer_task = models.ForeignKey(DialerTask, models.DO_NOTHING, db_column='dialer_task_id')

    class Meta(object):
        db_table = 'not_sent_to_dialer'


class VendorRecordingDetailManager(PIIVaultModelManager):
    pass


class VendorRecordingDetail(PIIVaultModel):
    PII_FIELDS = ['call_to']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = CollectionQueue.TOKENIZED_QUEUE

    id = models.AutoField(db_column='vendor_recording_detail_id', primary_key=True)
    payment = BigForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='agent_id')
    bucket = models.TextField()
    call_status = models.ForeignKey(
        SkiptraceResultChoice, db_column='skiptrace_result_choice_id')
    call_to = models.TextField(blank=True, null=True)
    call_start = models.DateTimeField()
    call_end = models.DateTimeField()
    # second
    duration = models.IntegerField()
    source = models.TextField(default="Intelix")
    voice_path = models.TextField()
    recording_url = models.TextField(blank=True, null=True)
    unique_call_id = models.TextField(unique=True)
    skiptrace = models.ForeignKey(
        Skiptrace, models.DO_NOTHING, db_column='skiptrace_id', blank=True, null=True)
    call_to_tokenized = models.TextField(blank=True, null=True)
    objects = VendorRecordingDetailManager()

    class Meta(object):
        db_table = 'vendor_recording_detail'

    @property
    def oss_recording_path(self):
        return self.recording_url.replace(
            '{}/'.format(settings.OSS_JULO_COLLECTION_BUCKET), ''
        )

    @property
    def oss_recording_file_name(self):
        return self.oss_recording_path.split('/')[1]

    @property
    def downloaded_file_name(self):
        file_name = "%s_{}_{}.wav" % timezone.localtime(
            self.call_start).strftime("%Y%m%d%H%M%S")
        if self.payment:
            return file_name.format("pmtid", self.payment.id)
        if self.call_to:
            return file_name.format("phone", self.call_to)

        return file_name.format("accpmtid", self.account_payment.id)

    @property
    def negative_score(self):
        airudder_upload = self.airudderrecordingupload_set.last()
        if not airudder_upload:
            return '-'
        upload_report = airudder_upload.recordingreport_set.last()
        if not upload_report:
            return '-'
        return upload_report.r_channel_negative_score_amount

    @property
    def sop_score(self):
        airudder_upload = self.airudderrecordingupload_set.last()
        if not airudder_upload:
            return '-'
        upload_report = airudder_upload.recordingreport_set.last()
        if not upload_report:
            return '-'
        return upload_report.r_channel_sop_score_amount


class intelixBlacklist(TimeStampedModel):
    id = models.AutoField(db_column='intelix_blacklist_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id'
    )
    skiptrace = models.ForeignKey('julo.Skiptrace', models.DO_NOTHING,
                                  db_column='skiptrace_id', blank=True,
                                  null=True)
    expire_date = models.DateField(blank=True, null=True)
    reason_for_removal = models.TextField(
        blank=True, null=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        db_column='auth_user_id', blank=True, null=True)

    class Meta(object):
        db_table = 'intelix_blacklist'


class BulkVendorRecordingFileCache(TimeStampedModel):
    id = models.AutoField(db_column='vendor_recording_detail_id', primary_key=True)
    cache_vendor_recording_detail_ids = models.TextField(blank=True, null=True)
    zip_recording_file_url = models.TextField(blank=True, null=True)
    expire_date = models.DateTimeField()
    total_data = models.IntegerField()
    task_id = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'bulk_vendor_recording_file_cache'

    @property
    def oss_zip_file_path(self):
        return self.zip_recording_file_url.replace(
            '{}/'.format(settings.OSS_JULO_COLLECTION_BUCKET), ''
        )


class CallbackPromiseApp(TimeStampedModel):
    id = models.AutoField(db_column='callback_promise_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    bucket = models.TextField(blank=True, null=True)
    selected_time_slot_start = models.TextField(blank=True, null=True)
    selected_time_slot_end = models.TextField(blank=True, null=True)
    skiptrace_history = models.ForeignKey(
        'julo.SkiptraceHistory',
        models.DO_NOTHING,
        db_column='skiptrace_history_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'callback_promise_app'


class CollectionCalendarsDistributionSender(TimeStampedModel):
    id = models.AutoField(db_column='collection_calendars_distribution_sender_id', primary_key=True)
    email = models.CharField(max_length=100)
    status = models.CharField(max_length=100, null=True, blank=True)
    token = JSONField(null=True, blank=True)
    daily_limit = models.IntegerField(default=100)
    current_usage = models.IntegerField(default=0)

    class Meta(object):
        db_table = 'collection_calendars_distribution_sender'


class CollectionCalendarsEvent(TimeStampedModel):
    id = models.AutoField(db_column='collection_calendars_event_id', primary_key=True)
    google_calendar_event_id = models.CharField(max_length=255, unique=True)
    event_date = models.DateField(blank=True, null=True)
    total_participants = models.IntegerField(blank=True, null=True)
    is_ptp = models.BooleanField(blank=True, default=False)
    collection_calendars_distribution_sender = models.ForeignKey(
        CollectionCalendarsDistributionSender,
        models.DO_NOTHING,
        db_column='collection_calendars_distribution_sender_id',
        blank=True,
        null=True,
    )

    class Meta(object):
        db_table = 'collection_calendars_event'


class CollectionCalendarsReminder(TimeStampedModel):
    id = models.AutoField(db_column='collection_calendars_reminder_id', primary_key=True)
    color_id = models.IntegerField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    google_calendar_event_id = models.CharField(max_length=255, blank=True, null=True)
    is_paid = models.BooleanField(blank=True, default=False)
    is_ptp = models.BooleanField(blank=True, default=False)
    status_code = models.CharField(max_length=5, blank=True, null=True)
    status_code_description = models.CharField(max_length=255, blank=True, null=True)
    method = models.CharField(max_length=15, blank=True, null=True)
    is_single_event = models.BooleanField(blank=True, default=False)
    collection_calendars_event = models.ForeignKey(
        CollectionCalendarsEvent,
        models.DO_NOTHING,
        db_column='collection_calendars_event_id',
        blank=True,
        null=True
    )

    class Meta(object):
        db_table = 'collection_calendars_reminder'


class CollectionCalendarsParameter(TimeStampedModel):
    id = models.AutoField(db_column='collection_calendar_parameter_id', primary_key=True)
    summary = models.TextField(blank=True, null=True)
    description = models.TextField(
        blank=True,
        null=True,
        help_text='please refer to this spreadsheet for the parameter details '
        'https://docs.google.com/spreadsheets/d/1D4aIESQG9UuPNDimERQaQJ_LBSh8a2GRO64xmMef4XM/edit#gid=0'
        )
    is_active = models.BooleanField(blank=True,default=False)
    is_single_parameter = models.BooleanField(blank=True, default=False)
    is_ptp_parameter = models.BooleanField(blank=True, default=False)

    class Meta(object):
        db_table = 'collection_calendars_parameter'


class CollectionDialerTemporaryData(TimeStampedModel):
    # this model will always flush every day at 8PM and generate it every day at 1AM
    id = models.AutoField(
        db_column='collection_dialer_temporary_id', primary_key=True)
    customer = BigForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True)
    application_id = models.BigIntegerField(blank=True, null=True)
    nama_customer = models.TextField(blank=True, null=True)
    nama_perusahaan = models.TextField(blank=True, null=True)
    posisi_karyawan = models.TextField(blank=True, null=True)
    nama_pasangan = models.TextField(blank=True, null=True)
    nama_kerabat = models.TextField(blank=True, null=True)
    hubungan_kerabat = models.TextField(blank=True, null=True)
    jenis_kelamin = models.TextField(blank=True, null=True)
    tgl_lahir = models.TextField(blank=True, null=True)
    tgl_gajian = models.TextField(blank=True, null=True)
    tujuan_pinjaman = models.TextField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True)
    alamat = models.TextField(blank=True, null=True)
    kota = models.TextField(blank=True, null=True)
    tipe_produk = models.TextField(blank=True, null=True)
    partner_name = models.TextField(blank=True, null=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment', models.DO_NOTHING, db_column='account_payment_id',
        blank=True, null=True)
    sort_order = models.IntegerField(blank=True, null=True)
    dpd = models.IntegerField(blank=True, null=True)
    team = models.TextField(blank=True, null=True)
    mobile_phone_1 = models.TextField(blank=True, null=True)
    va_bca = models.TextField(blank=True, null=True, default='')
    va_permata = models.TextField(blank=True, null=True, default='')
    va_maybank = models.TextField(blank=True, null=True, default='')
    va_alfamart = models.TextField(blank=True, null=True, default='')
    va_indomaret = models.TextField(blank=True, null=True, default='')
    va_mandiri = models.TextField(blank=True, null=True, default='')

    class Meta(object):
        db_table = 'collection_dialer_temporary_data'


class TemporaryStorageDialer(TimeStampedModel):
    id = models.AutoField(
        db_column='temporary_storage_intelix_id', primary_key=True)
    key = models.TextField()
    temp_values = JSONField(null=True, blank=True)

    class Meta(object):
        db_table = 'temporary_storage_dialer'


class CollectionBucketInhouseVendorManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionBucketInhouseVendor(TimeStampedModel):
    id = models.AutoField(
        db_column='collection_bucket_inhouse_vendor_id',
        primary_key=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    bucket = models.TextField(blank=True, null=True)
    vendor = models.BooleanField(blank=True,default=False)

    objects = CollectionBucketInhouseVendorManager()

    class Meta(object):
        db_table = 'collection_bucket_inhouse_vendor'


class AIRudderPayloadTemp(TimeStampedModel):
    id = models.AutoField(db_column='ai_rudder_payload_temp_id', primary_key=True)
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', blank=True, null=True)
    phonenumber = models.TextField(db_index=True)
    nama_customer = models.TextField(blank=True, null=True, default='')
    nama_perusahaan = models.TextField(blank=True, null=True, default='')
    posisi_karyawan = models.TextField(blank=True, null=True, default='')
    dpd = models.IntegerField(blank=True, null=True)
    total_denda = models.BigIntegerField(blank=True, null=True)
    total_due_amount = models.BigIntegerField(blank=True, null=True)
    total_outstanding = models.BigIntegerField(blank=True, null=True)
    angsuran_ke = models.IntegerField(blank=True, null=True)
    tanggal_jatuh_tempo = models.TextField(blank=True, null=True, default='')
    nama_pasangan = models.TextField(blank=True, null=True, default='')
    nama_kerabat = models.TextField(blank=True, null=True, default='')
    hubungan_kerabat = models.TextField(blank=True, null=True, default='')
    alamat = models.TextField(blank=True, null=True, default='')
    kota = models.TextField(blank=True, null=True, default='')
    jenis_kelamin = models.TextField(blank=True, null=True, default='')
    tgl_lahir = models.TextField(blank=True, null=True, default='')
    tgl_gajian = models.TextField(blank=True, null=True, default='')
    tujuan_pinjaman = models.TextField(blank=True, null=True, default='')
    jumlah_pinjaman = models.BigIntegerField(blank=True, null=True)
    tgl_upload = models.TextField(blank=True, null=True, default='')
    va_bca = models.TextField(blank=True, null=True, default='')
    va_permata = models.TextField(blank=True, null=True, default='')
    va_maybank = models.TextField(blank=True, null=True, default='')
    va_alfamart = models.TextField(blank=True, null=True, default='')
    va_indomaret = models.TextField(blank=True, null=True, default='')
    va_mandiri = models.TextField(blank=True, null=True, default='')
    tipe_produk = models.TextField(blank=True, null=True, default='')
    last_pay_date = models.TextField(blank=True, null=True, default='')
    last_pay_amount = models.BigIntegerField(blank=True, null=True)
    partner_name = models.TextField(blank=True, null=True, default='')
    last_agent = models.TextField(blank=True, null=True, default='')
    last_call_status = models.TextField(blank=True, null=True, default='')
    refinancing_status = models.TextField(blank=True, null=True, default='')
    activation_amount = models.BigIntegerField(blank=True, null=True)
    program_expiry_date = models.TextField(blank=True, null=True, default='')
    customer_bucket_type = models.TextField(blank=True, null=True, default='')
    promo_untuk_customer = models.TextField(blank=True, null=True, default='')
    zip_code = models.TextField(blank=True, null=True, default='')
    mobile_phone_2 = models.TextField(blank=True, null=True, default='')
    telp_perusahaan = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_2 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_2 = models.TextField(blank=True, null=True, default='')
    no_telp_pasangan = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_3 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_3 = models.TextField(blank=True, null=True, default='')
    no_telp_kerabat = models.TextField(blank=True, null=True, default='')
    mobile_phone_1_4 = models.TextField(blank=True, null=True, default='')
    mobile_phone_2_4 = models.TextField(blank=True, null=True, default='')
    bucket_name = models.TextField(db_index=True, default='')
    sort_order = models.IntegerField(blank=True, null=True)
    angsuran_per_bulan = models.BigIntegerField(blank=True, null=True)
    uninstall_indicator = models.TextField(blank=True, null=True, default='')
    fdc_risky = models.TextField(blank=True, null=True, default='')
    risk_score = models.TextField(blank=True, null=True, default='')
    potensi_cashback = models.BigIntegerField(blank=True, null=True)
    total_seluruh_perolehan_cashback = models.BigIntegerField(blank=True, null=True)
    status_refinancing_lain = models.TextField(blank=True, null=True, default='')
    application_id = models.BigIntegerField(blank=True, null=True)
    other_numbers = ArrayField(models.TextField(), blank=True, null=True, default=None)
    unpaid_loan_account_details = models.TextField(blank=True, null=True, default='')
    fdc_details = models.TextField(blank=True, null=True, default='')

    class Meta(object):
        db_table = 'ai_rudder_payload_temp'


class HangupReasonPDS(TimeStampedModel):
    id = models.AutoField(
        db_column='hangup_reason_pds_id', primary_key=True)
    skiptrace_history = models.ForeignKey(
        'julo.SkiptraceHistory',
        models.DO_NOTHING,
        db_column='skiptrace_history_id',
        blank=True,
        null=True
    )
    hangup_reason = models.IntegerField(db_column='hangup_reason_id')
    reason = models.TextField()

    class Meta(object):
        db_table = 'hangup_reason_pds'

class AccountDueAmountAbove2Mio(TimeStampedModel):
    id = models.AutoField(db_column='account_due_amount_above_2mio_id', primary_key=True)
    account_id = models.IntegerField(blank=True, null=True)
    # exclude_date = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."account_due_amount_above_2mio"'
        managed = False


class CollectionRiskHistoryManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionRiskSkiptraceHistory(TimeStampedModel):
    id = models.AutoField(db_column='collection_risk_skiptrace_history_id', primary_key=True)
    skiptrace = models.ForeignKey('julo.Skiptrace', models.DO_NOTHING, db_column='skiptrace_id')
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField(blank=True, null=True)
    agent = CurrentUserField(related_name="collection_risk_skiptrace_call_history")
    agent_name = models.TextField(null=True, blank=True)
    spoke_with = models.TextField(null=True, blank=True)
    call_result = models.ForeignKey(
        'julo.SkiptraceResultChoice', db_column='skiptrace_result_choice_id'
    )
    application = BigForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', null=True, blank=True
    )
    payment_status = models.IntegerField(blank=True, null=True)
    notes = models.TextField(null=True, blank=True)
    callback_time = models.CharField(max_length=12, blank=True, null=True)
    excluded_from_bucket = models.NullBooleanField()
    non_payment_reason = models.TextField(null=True, blank=True)
    status_group = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    account_payment_status = models.ForeignKey(
        'julo.StatusLookup', models.DO_NOTHING, null=True, blank=True
    )
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )
    caller_id = models.TextField(null=True, blank=True)
    dialer_task = models.ForeignKey(
        'minisquad.DialerTask', models.DO_NOTHING, db_column='dialer_task_id', null=True, blank=True
    )
    source = models.TextField(null=True, blank=True)
    unique_call_id = models.TextField(null=True, blank=True)
    is_fraud_colls = models.BooleanField(default=False)
    external_unique_identifier = models.TextField(null=True, blank=True, unique=True, db_index=True)
    external_task_identifier = models.TextField(null=True, blank=True, db_index=True)
    objects = CollectionRiskHistoryManager()

    class Meta(object):
        db_table = 'collection_risk_skiptrace_history'

    def __init__(self, *args, **kwargs):
        from juloserver.pii_vault.collection.services import mask_phone_number_sync

        super(CollectionRiskSkiptraceHistory, self).__init__(*args, **kwargs)
        if self.notes:
            self.notes = mask_phone_number_sync(self.notes)


class RiskCallLogPocAiRudderPds(TimeStampedModel):
    id = models.AutoField(db_column='id', primary_key=True)

    skiptrace_history = models.ForeignKey(
        CollectionRiskSkiptraceHistory,
        models.DO_NOTHING,
        db_column='skiptrace_history_id',
    )

    call_log_type = models.TextField(blank=True, null=True)
    task_id = models.TextField(blank=True, null=True)
    task_name = models.TextField(blank=True, null=True)
    group_name = models.TextField(blank=True, null=True)
    state = models.TextField(blank=True, null=True)
    phone_number = models.TextField(blank=True, null=True)
    call_id = models.TextField(blank=True, null=True, db_index=True)
    contact_name = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    info_1 = models.TextField(blank=True, null=True)
    info_2 = models.TextField(blank=True, null=True)
    info_3 = models.TextField(blank=True, null=True)
    remark = models.TextField(blank=True, null=True)
    main_number = models.TextField(blank=True, null=True)
    phone_tag = models.TextField(blank=True, null=True)
    private_data = models.TextField(blank=True, null=True)
    hangup_reason = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(blank=True, null=True)
    recording_link = models.TextField(blank=True, null=True)
    nth_call = models.IntegerField(blank=True, null=True)
    talk_remarks = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'risk_call_log_poc_airudder_pds'


class RiskHangupReasonPDS(TimeStampedModel):
    id = models.AutoField(
        db_column='hangup_reason_pds_id', primary_key=True)
    skiptrace_history = models.ForeignKey(
        CollectionRiskSkiptraceHistory,
        models.DO_NOTHING,
        db_column='collection_risk_skiptrace_history_id',
        blank=True,
        null=True
    )
    hangup_reason = models.IntegerField(db_column='hangup_reason_id')
    reason = models.TextField()

    class Meta(object):
        db_table = 'risk_hangup_reason_pds'


class CollectionDialerTaskSummaryAPI(TimeStampedModel):
    id = models.AutoField(db_column='collection_dialer_task_summary_api_id', primary_key=True)
    date = models.DateField(blank=True, null=True)
    external_task_identifier = models.TextField(blank=True, null=True)
    external_task_name = models.TextField(blank=True, null=True)
    total_api = models.IntegerField(default=0)
    total_before_retro = models.IntegerField(default=0)
    total_after_retro = models.IntegerField(default=0)

    class Meta(object):
        db_table = 'collection_dialer_task_summary_api'


class AccountBucketHistory(TimeStampedModel):
    id = models.AutoField(db_column='account_bucket_history_id', primary_key=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    reached_at = models.DateTimeField(blank=True, null=True)
    bucket_name = models.TextField(blank=True, null=True, db_index=True)

    class Meta(object):
        db_table = 'account_bucket_history'


class BucketRecoveryDistribution(TimeStampedModel):
    id = models.AutoField(db_column='bucket_recovery_distribution_id', primary_key=True)
    assigned_to = models.TextField(blank=True, null=True, db_index=True)
    bucket_name = models.TextField(blank=True, null=True, db_index=True)
    assignment_datetime = models.DateTimeField(null=True, blank=True)
    assignment_generated_date = models.DateField(null=True, blank=True)
    account = models.ForeignKey(
        'account.Account', models.DO_NOTHING, db_column='account_id', blank=True, null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True,
    )

    class Meta(object):
        db_table = 'bucket_recovery_distribution'


class CollectionIneffectivePhoneNumber(TimeStampedModel):
    id = BigAutoField(db_column='collection_ineffective_phone_number_id', primary_key=True)
    last_unreachable_date = models.DateField(blank=True, null=True)
    skiptrace_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    ineffective_days = models.IntegerField(null=False, blank=False, default=0)
    flag_as_unreachable_date = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = 'collection_ineffective_phone_number'
        managed = False


class ManualDCAgentAssignment(TimeStampedModel):
    id = BigAutoField(db_column='manual_dc_agent_assignment_id', primary_key=True)
    account_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    agent_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    bucket_name = models.TextField(blank=True, null=True)
    is_eligible = models.NullBooleanField(db_index=True)
    assignment_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    sort_order = models.IntegerField(blank=True, null=True)
    account_payment_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    customer_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    assignment_notes = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'manual_dc_agent_assignment'
        managed = False


class CollectionSkiptraceEventHistory(TimeStampedModel):
    id = BigAutoField(db_column='collection_skiptrace_event_history_id', primary_key=True)
    event_date = models.DateField(blank=True, null=True)
    skiptrace_id = models.BigIntegerField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    unreachable_days = models.IntegerField(null=True, blank=True)
    event_name = models.TextField(blank=True, null=True)
    bucket_number = models.IntegerField(blank=True, null=True)
    consecutive_config_days = models.IntegerField(blank=True, null=True)
    refresh_config_days = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'collection_skiptrace_event_history'
        managed = False


class KangtauUploadedCustomerList(TimeStampedModel):
    id = BigAutoField(db_column='kangtau_customer_list_id', primary_key=True)
    loan_id = models.BigIntegerField()
    agent_unique_id = models.TextField(null=True, blank=True)
    name = models.TextField()
    phone_number = models.TextField()
    loan_amount = models.DecimalField(max_digits=15, decimal_places=2)
    outstanding_amount = models.DecimalField(max_digits=15, decimal_places=2)
    due_date = models.DateField()
    bucket = models.TextField(db_index=True)
    dpd = models.IntegerField(db_index=True)
    customer_form_id = models.TextField(db_index=True)
    customer_form_name = models.TextField(db_index=True)

    class Meta(object):
        db_table = 'kangtau_uploaded_customer_list'
        managed = False
        # Human-readable names
        verbose_name = 'Kangtau Uploaded Customer List'
        verbose_name_plural = 'Kangtau Uploaded Customer Lists'
