from datetime import timedelta

from cuser.fields import CurrentUserField
from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from django.db.models import Q, F
from django.utils import timezone
from model_utils import FieldTracker

from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountProperty,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import (
    Agent,
    TimeStampedModel,
    GetInstanceMixin,
    Application,
    Loan,
    SkiptraceResultChoice,
)
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigAutoField,
)
from juloserver.julocore.data.models import JuloModelManager, CustomQuerySet
from juloserver.sales_ops.constants import (
    ScoreCriteria,
    AutodialerConst,
    SalesOpsRoles,
    SalesOpsVendorName,
    BucketCode,
    CustomerType,
)


class SalesOpsRMScoring(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_rm_scoring_id', primary_key=True)
    criteria = models.TextField(choices=ScoreCriteria.choices(), db_index=True)
    top_percentile = models.DecimalField(max_digits=15, decimal_places=4)
    bottom_percentile = models.DecimalField(max_digits=15, decimal_places=4, blank=True, null=True)
    score = models.SmallIntegerField()
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_ops_rm_scoring'
        managed = False

    def __str__(self):
        return '{} (criteria:{}) (score:{}) (top:{})'.format(
            self.id, self.criteria, self.score, self.top_percentile)


class SalesOpsAccountSegmentHistory(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_account_segment_history_id', primary_key=True)
    account_id = models.IntegerField(db_column='account_id')
    m_score_id = models.IntegerField(blank=True, null=True)
    r_score_id = models.IntegerField(blank=True, null=True)

    # for json state during rm score calculation, for debugging purpose.
    log = JSONField(default=dict, blank=True, null=True)

    class Meta:
        db_table = 'sales_ops_account_segment_history'
        managed = False

    def __str__(self):
        return '{} (account:{}) (r_score:{}) (m_score:{})'.format(
            self.id, self.account_id, self.r_score_id, self.m_score_id
        )


class SalesOpsLineupQuerySet(CustomQuerySet):
    def active(self):
        return self.filter(is_active=True)

    def crm(self, bucket_code=None, vendor_name=None, exclude_buckets=None):
        qs = self.active()
        if bucket_code:
            qs = qs.filter(bucket_code=bucket_code)
        elif exclude_buckets:
            qs = qs.exclude(bucket_code__in=exclude_buckets)
        if vendor_name:
            qs = qs.filter(vendor_name=vendor_name)

        return qs

    def agent(self, agent_id):
        sales_ops_agent_assignment_ids = list(
            SalesOpsAgentAssignment.objects.filter(
                agent_id=agent_id,
                completed_date__isnull=False,
            ).values_list('id', flat=True)
        )
        return self.filter(
            latest_agent_assignment_id__in=sales_ops_agent_assignment_ids
        ).distinct()

    def bucket(self, bucket_code):
        return self.filter(bucket_code=bucket_code)


class SalesOpsLineupManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return SalesOpsLineupQuerySet(model=self.model)

    def crm_queryset(self):
        select_related = [
            'latest_application',
            'latest_account_limit',
            'latest_account_property',
            'latest_disbursed_loan',
        ]
        return self.get_queryset().crm().select_related(*select_related)

    def crm_detail_queryset(self):
        select_related = [
            'latest_application',
            'latest_account_limit',
            'latest_account_property',
            'latest_disbursed_loan',
        ]
        return self.get_queryset().select_related(*select_related)

    def autodialer_default_queue_queryset(self, agent_id, bucket_code=None, *args, **kwargs):
        """
        Rules: (https://juloprojects.atlassian.net/wiki/spaces/PD/pages/2246475784)
            - To avoid customers being spammed by agents, so accounts that already assigned to
            agent_id will be excluded from autodialer.
            - Assignment will be done on call. So we exclude every customers that
            hasn’t got any agent_id yet. When they call customers and get RPC on autodialer,
            it will be assigned to that particular agent for 7 days.
            - After 7 days, the agent assignment will be voided and the customers will
            be assigned to other agents on call to whoever agents that get RPC.
            - Interval for next for non RPC (no answer, rejected, busy) = 4 hours,
            then it will get to queue again (configurable by django admin).
            If this happens 3x, then we will not call this applicant until the next 168 hours.
            - If the call time of recalled app and uncalled app are the same,
            then we will prioritize the uncalled app first.

            Patch:
            - Exclude if the linup has a valid `inactive_until` date
        """
        from juloserver.sales_ops.services.sales_ops_services import using_sales_ops_bucket_logic
        rpc_delay_hour = kwargs.get('rpc_delay_hour', 0)
        rpc_assignment_delay_hour = kwargs.get('rpc_assignment_delay_hour', 0)
        non_rpc_delay_hour = kwargs.get('non_rpc_delay_hour', 0)
        non_rpc_final_attempt_count = kwargs.get('non_rpc_final_attempt_count', 0)
        non_rpc_final_delay_hour = kwargs.get('non_rpc_final_delay_hour', 0)
        exclude_buckets = kwargs.get('exclude_buckets')

        qs = self.get_queryset()
        if using_sales_ops_bucket_logic():
            qs = qs.filter(vendor_name=SalesOpsVendorName.IN_HOUSE)

        if bucket_code:
            qs = qs.bucket(bucket_code)
        elif exclude_buckets:
            qs = qs.exclude(bucket_code__in=exclude_buckets)

        today = timezone.localtime(timezone.now())
        rpc_assignment_expire_date = today - timedelta(hours=rpc_assignment_delay_hour)
        rpc_success_expire_date = today - timedelta(hours=rpc_delay_hour)
        non_rpc_expire_date = today - timedelta(hours=non_rpc_delay_hour)
        non_rpc_final_expire_date = today - timedelta(hours=non_rpc_final_delay_hour)

        latest_agent_assignment_ids = list(
            SalesOpsAgentAssignment.objects.filter(
                Q(is_active=False),
                ~Q(
                    Q(is_rpc=True, completed_date__gt=rpc_success_expire_date)
                    | Q(
                        ~Q(agent_id=agent_id if agent_id else F('agent_id')),
                        is_rpc=True,
                        completed_date__gt=rpc_assignment_expire_date,
                    )
                    | Q(
                        is_rpc=False,
                        non_rpc_attempt__lt=non_rpc_final_attempt_count,
                        completed_date__gt=non_rpc_expire_date,
                    )
                    | Q(
                        is_rpc=False,
                        non_rpc_attempt__gte=non_rpc_final_attempt_count,
                        completed_date__gt=non_rpc_final_expire_date,
                    )
                ),
            ).values_list('id', flat=True)
        )

        extra_kwargs = {
            'select': {'has_assignment': 'latest_agent_assignment_id IS NOT NULL'}
        }
        order_args = [
            'prioritization',
            'has_assignment',
            'latest_agent_assignment_id',
            '-cdate',
        ]
        filter_arg = Q(
            Q(is_active=True),
            Q(inactive_until__lt=today) | Q(inactive_until__isnull=True),
            ~Q(prioritization=0),
            Q(
                Q(latest_agent_assignment_id__isnull=True)
                | Q(latest_agent_assignment_id__in=latest_agent_assignment_ids),
            ),
        )

        qs = qs.extra(**extra_kwargs).filter(filter_arg).order_by(*order_args)
        return qs

    def count_active_lineup(self, vendor_name=None, exclude_buckets=None):
        return self.get_queryset().crm(
            vendor_name=vendor_name, exclude_buckets=exclude_buckets
        ).count()

    def count_bucket(self, bucket_code, vendor_name):
        return self.get_queryset().crm(bucket_code=bucket_code, vendor_name=vendor_name).count()


class SalesOpsLineup(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_lineup_id', primary_key=True)
    account = models.OneToOneField(Account, db_column='account_id', on_delete=models.DO_NOTHING)
    prioritization = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    vendor_name = models.CharField(max_length=50, null=True, blank=True)
    rpc_count = models.IntegerField(default=0, null=True, blank=True)

    # for reason text for inactive_until changes.
    reason = models.TextField(null=True, blank=True)
    inactive_until = models.DateTimeField(null=True, blank=True)

    # These latest relations are used to ease the lookup in CRM
    latest_application = BigForeignKey(
        Application,
        db_column='latest_application_id',
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )
    latest_account_limit = models.OneToOneField(
        AccountLimit,
        db_column='latest_account_limit_id',
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )
    latest_account_property = models.OneToOneField(
        AccountProperty,
        db_column='latest_account_property_id',
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )
    latest_disbursed_loan = BigForeignKey(
        Loan,
        db_column='latest_disbursed_loan_id',
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )
    latest_account_payment = BigForeignKey(
        AccountPayment,
        db_column='latest_account_payment_id',
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )

    latest_agent_assignment_id = models.IntegerField(null=True, blank=True)
    latest_rpc_agent_assignment_id = models.IntegerField(null=True, blank=True)
    latest_callback_at = models.DateTimeField(blank=True, null=True)

    bucket_code = models.TextField(null=True, blank=True, db_index=True)
    next_reset_bucket_date = models.DateTimeField(null=True, blank=True)
    objects = SalesOpsLineupManager()
    tracker = FieldTracker()

    class Meta:
        db_table = 'sales_ops_lineup'

    def __str__(self):
        return '{} (account:{}) (priority:{})'.format(self.id, self.account_id, self.prioritization)

    def has_been_prioritized(self):
        return self.prioritization > 0


class SalesOpsAgentAssignmentManager(GetInstanceMixin, JuloModelManager):
    def agent_list_queryset(self):
        return Agent.objects.filter(
            user__groups__name=SalesOpsRoles.SALES_OPS,
            user__is_active=True
        )

    def get_previous_assignment(self, assignment):
        qs = self.get_queryset().filter(lineup_id=assignment.lineup_id,
                                        completed_date__isnull=False,
                                        completed_date__lte=assignment.assignment_date)\
                                .exclude(id=assignment.id)\
                                .order_by('completed_date')
        return qs.last()


class SalesOpsAgentAssignment(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_agent_assignment_id', primary_key=True)
    agent_id = models.IntegerField()
    lineup_id = models.BigIntegerField(db_column='sales_ops_lineup_id')
    agent_name = models.TextField(blank=True, null=True)
    assignment_date = models.DateTimeField(blank=True, null=True)
    completed_date = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(blank=True, default=True)
    is_rpc = models.NullBooleanField(blank=True)
    non_rpc_attempt = models.PositiveIntegerField(blank=True, default=0)

    objects = SalesOpsAgentAssignmentManager()

    class Meta:
        db_table = 'sales_ops_agent_assignment'
        managed = False

    def __str__(self):
        return '{} (lineup:{}) (agent:{})'.format(self.id, self.lineup_id, self.agent_id)

    def agent_promo_code_expiration_date(self):
        completed_date = self.completed_date
        return None if not completed_date else completed_date.date() + timedelta(days=6)


class SalesOpsPrioritizationConfiguration(TimeStampedModel):
    # will be deprecated after https://juloprojects.atlassian.net/browse/UTIL-453 release
    id = BigAutoField(db_column='sales_ops_prioritization_configuration_id', primary_key=True)
    segment_name = models.TextField(null=True, blank=True)
    prioritization = models.SmallIntegerField(default=0)
    r_score = models.SmallIntegerField(default=0)
    m_score = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_ops_prioritization_configuration'
        managed = False

    def __str__(self):
        return '{} (priority:{}) (r:{}) (m:{})'.format(
            self.id, self.prioritization, self.r_score, self.m_score)


class SalesOpsMScore(models.Model):
    account_id = models.BigIntegerField(primary_key=True)
    latest_account_limit_id = models.BigIntegerField(null=True, blank=True)
    available_limit = models.BigIntegerField(default=0)
    ranking = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = "sales_ops_m_score"
        managed = False


class SalesOpsRScore(models.Model):
    account_id = models.BigIntegerField(primary_key=True)
    latest_active_dates = models.DateField(blank=True, null=True)
    ranking = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = "sales_ops_r_score"
        managed = False


class SalesOpsGraduation(models.Model):
    account_id = models.BigIntegerField(primary_key=True)
    last_graduation_date = models.DateField(null=True, blank=True)
    limit_amount_increased = models.BigIntegerField(default=0)
    ranking = models.BigIntegerField(default=0)

    class Meta(object):
        db_table = "sales_ops_graduation"
        managed = False


class SalesOpsAutodialerSessionManager(GetInstanceMixin, JuloModelManager):
    pass


class SalesOpsAutodialerSession(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_autodialer_session_id', primary_key=True)
    lineup_id = models.BigIntegerField()
    failed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)
    next_session_ts = models.DateTimeField(blank=True, null=True)

    objects = SalesOpsAutodialerSessionManager()

    class Meta:
        db_table = 'sales_ops_autodialer_session'
        managed = False


class SalesOpsAutodialerActivityManager(GetInstanceMixin, JuloModelManager):
    def get_latest_activity(self, autodialer_session_id, agent_assignment_id):
        qs = self.get_queryset()
        valid_action = [
            AutodialerConst.SESSION_ACTION_SUCCESS,
            AutodialerConst.SESSION_ACTION_FAIL,
        ]
        filter_kwargs = {
            'autodialer_session_id': autodialer_session_id,
            'agent_assignment_id': agent_assignment_id,
            'action__in': valid_action
        }
        qs = qs.filter(**filter_kwargs).order_by('-cdate')
        return qs.first()


class SalesOpsAutodialerActivity(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_autodialer_activity_id', primary_key=True)
    agent_id = models.IntegerField()
    action = models.TextField()
    phone_number = models.TextField(blank=True, null=True)
    autodialer_session_id = models.IntegerField(db_column='sales_ops_autodialer_session_id',)
    agent_assignment_id = models.IntegerField(db_column='sales_ops_agent_assignment_id',
                                            blank=True, null=True)
    skiptrace_result_choice_id = models.IntegerField(db_column='skiptrace_result_choice_id',
                                                blank=True, null=True)

    objects = SalesOpsAutodialerActivityManager()

    class Meta:
        db_table = 'sales_ops_autodialer_activity'
        managed = False

    def is_success(self):
        return self.action == AutodialerConst.SESSION_ACTION_SUCCESS


class SalesOpsAutodialerQueueSnapshot(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_autodialer_queue_snapshot_id', primary_key=True)
    snapshot_at = models.DateTimeField(db_column='snapshot_at')
    account_id = models.BigIntegerField(null=True, blank=True)
    prioritization = models.IntegerField(null=True, blank=True)
    ordering = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'sales_ops_autodialer_queue_snapshot'
        managed = False


class SalesOpsLineupHistory(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_lineup_history_id', primary_key=True)
    lineup_id = models.IntegerField(db_column='sales_ops_lineup_id')
    old_values = JSONField(null=True, blank=True)
    new_values = JSONField(null=True, blank=True)
    changed_by_id = models.IntegerField(db_column='changed_by_id', null=True, blank=True)

    class Meta:
        db_table = 'sales_ops_lineup_history'
        managed = False


class SalesOpsLineupCallbackHistory(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_lineup_callback_history_id', primary_key=True)
    lineup_id = models.BigIntegerField(db_column='sales_ops_lineup_id')
    callback_at = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    changed_by = models.BigIntegerField()

    class Meta:
        db_table = 'sales_ops_lineup_callback_history'
        managed = False


class SalesOpsDailySummary(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_daily_summary_id', primary_key=True)
    total = models.IntegerField(null=True, blank=True)
    progress = models.IntegerField(null=True, blank=True)
    number_of_task = models.IntegerField(null=True, blank=True)
    new_sales_ops = models.IntegerField(null=True, blank=True)
    update_sales_ops = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'sales_ops_daily_summary'
        managed = False


class SalesOpsVendor(TimeStampedModel):
    id = models.AutoField(db_column='sales_ops_vendor_id', primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_ops_vendor'
        managed = False

    def __str__(self):
        return self.name


class SalesOpsBucket(TimeStampedModel):
    id = models.AutoField(db_column='sales_ops_bucket_id', primary_key=True)
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(null=True, blank=True)
    scores = JSONField(default=dict)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_ops_bucket'
        managed = False

    def __str__(self):
        return self.code


class SalesOpsVendorBucketMapping(TimeStampedModel):
    id = models.AutoField(db_column='sales_ops_vendor_bucket_mapping_id', primary_key=True)
    vendor = models.ForeignKey(
        SalesOpsVendor, db_column='sales_ops_vendor_id', on_delete=models.DO_NOTHING,
        related_name='bucket_mappings',
    )
    bucket = models.ForeignKey(
        SalesOpsBucket, db_column='sales_ops_bucket_id', on_delete=models.DO_NOTHING,
        related_name='vendor_mappings',
    )
    ratio = models.PositiveIntegerField()
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_ops_vendor_bucket_mapping'
        unique_together = (("vendor", "bucket"),)
        managed = False

    def __str__(self):
        return f'{self.vendor} - {self.bucket}'


class SalesOpsVendorAgentMappingManager(GetInstanceMixin, JuloModelManager):
    pass


class SalesOpsVendorAgentMapping(TimeStampedModel):
    id = models.AutoField(db_column='sales_ops_vendor_agent_mapping_id', primary_key=True)
    vendor = models.ForeignKey(
        SalesOpsVendor, db_column='sales_ops_vendor_id', on_delete=models.DO_NOTHING,
        related_name='agent_mappings',
    )
    agent_id = models.BigIntegerField()
    is_active = models.BooleanField(default=False)

    objects = SalesOpsVendorAgentMappingManager()

    class Meta:
        db_table = 'sales_ops_vendor_agent_mapping'
        unique_together = (("vendor", "agent_id"),)
        managed = False

    def __str__(self):
        return f'{self.vendor} - {self.agent_id}'
    

class SalesOpsPrepareData(TimeStampedModel):
    id = models.AutoField(db_column='sales_ops_prepare_data_id', primary_key=True)
    account_id = models.BigIntegerField()
    customer_id = models.BigIntegerField()
    customer_type = models.TextField(choices=CustomerType.choices(), null=True, blank=True)
    application_history_x190_cdate = models.DateTimeField()
    latest_loan_fund_transfer_ts = models.DateTimeField()
    available_limit = models.BigIntegerField(default=0)

    class Meta:
        db_table = '"ana"."sales_ops_prepare_data"'
        managed = False

    @property
    def days_after_application_history_x190_cdate(self) -> int:
        now = timezone.localtime(timezone.now())
        if self.application_history_x190_cdate:
            return (now - self.application_history_x190_cdate).days
        return 0
    
    @property
    def days_after_latest_loan_fund_transfer_ts(self) -> int:
        now = timezone.localtime(timezone.now())
        if self.latest_loan_fund_transfer_ts:
            return (now - self.latest_loan_fund_transfer_ts).days
        return 0


class SalesOpsRMScoringConfig(TimeStampedModel):
    id = BigAutoField(db_column='sales_ops_rm_scoring_id', primary_key=True)
    criteria = models.TextField(choices=ScoreCriteria.choices(), db_index=True)
    min_value = models.BigIntegerField(null=True, blank=True)
    max_value = models.BigIntegerField(null=True, blank=True)
    customer_type = models.TextField(choices=CustomerType.choices(), null=True, blank=True)
    field_name = models.TextField(null=True, blank=True)
    score = models.SmallIntegerField()
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_ops_rm_scoring_config'
        managed = False
