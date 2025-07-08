from builtins import range
from builtins import object
from datetime import timedelta
from django.db.models import F
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from django.db import models
from juloserver.julocore.data.models import TimeStampedModel

from juloserver.julo.models import Partner

from .constants import CriteriaChoices, DpdConditionChoices, CootekProductLineCodeName


class CootekRobot(TimeStampedModel):
    id = models.AutoField(db_column='cootek_robot_id', primary_key=True)
    robot_identifier = models.CharField(max_length=200, null=True, default=None)
    robot_name = models.CharField(max_length=200, null=True, default=None)
    is_group_method = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'cootek_robot'

    def __str__(self):
        return self.robot_name


class CootekControlGroup(TimeStampedModel):
    id = models.AutoField(db_column='cootek_control_group_id', primary_key=True)
    account_tail_ids = ArrayField(models.CharField(
        max_length=100), null=True, default=None, blank=True)
    percentage = models.CharField(max_length=200, null=True, default=None)

    class Meta(object):
        db_table = 'cootek_control_group'

    def __str__(self):
        return self.percentage


class CootekConfiguration(TimeStampedModel):
    NUMBER_OF_ATTEMPT_CHOICES = (
        ('0', '0'),
        ('1', '1'),
        ('2', '2'),
        ('3', '3')
    )

    id = models.AutoField(db_column='cootek_configuration_id', primary_key=True)
    strategy_name = models.CharField(max_length=200, default=None)
    partner = models.ForeignKey(Partner, models.DO_NOTHING,
                                db_column='partner_id', blank=True, null=True)
    task_type = models.CharField(max_length=200, null=True, default=None)
    criteria = models.CharField(choices=CriteriaChoices.ALL,
                                max_length=200, blank=True, null=True)
    dpd_condition = models.CharField(choices=DpdConditionChoices.ALL, blank=True, null=True,
                                     max_length=200, default='Exactly', verbose_name='called_at')
    called_at = models.IntegerField(verbose_name='From', blank=True, null=True)
    called_to = models.IntegerField(blank=True, null=True, verbose_name='To')
    time_to_start = models.TimeField()
    time_to_prepare = models.TimeField(blank=True, null=True)
    time_to_query_result = models.TimeField(blank=True, null=True)
    number_of_attempts = models.CharField(choices=NUMBER_OF_ATTEMPT_CHOICES, max_length=200)
    tag_status = ArrayField(models.CharField(max_length=200), null=True, default=None)
    from_previous_cootek_result = models.BooleanField(default=True)
    cootek_robot = models.ForeignKey(CootekRobot, models.DO_NOTHING,
                                     db_column='cootek_robot_id', blank=True, null=True)
    product = models.CharField(max_length=10, null=True, default=None)
    exclude_risky_customer = models.BooleanField(
        default=False, verbose_name='Exclude isrisky dpd- ?')
    exclude_autodebet = models.BooleanField(default=False)
    loan_ids = ArrayField(models.CharField(max_length=100), null=True, default=None, blank=True)
    is_active = models.BooleanField(default=True)
    is_exclude_b3_vendor = models.BooleanField(
        default=False, verbose_name='Exclude 50% sent to B3 vendor')
    cootek_control_group = models.ForeignKey(
        CootekControlGroup, models.DO_NOTHING,
        db_column='cootek_control_group_id', blank=True, null=True)
    time_to_end = models.TimeField(blank=True, null=True)
    julo_gold = models.CharField(max_length=100, blank=True, null=True)

    class Meta(object):
        db_table = 'cootek_configuration'
        unique_together = ('task_type', 'time_to_start', )

    def is_bl_paylater(self):
        return True if self.partner and self.partner.name == 'bukalapak_paylater' else False

    def get_payment_filter(self, dpd_limit_list, is_object_skiptrace=False):
        is_bl_paylater = self.is_bl_paylater()
        today = timezone.localtime(timezone.now()).date()

        def get_dpd_date(dpd):
            return today - timedelta(dpd)

        if self.dpd_condition == DpdConditionChoices.EXACTLY:
            key = 'due_date'
            if is_object_skiptrace:
                key = 'account_payment__due_date'
            values = get_dpd_date(self.called_at)
            if is_bl_paylater:
                key = 'statement_due_date'
        elif self.dpd_condition == DpdConditionChoices.RANGE:
            key = 'due_date__in'
            if is_object_skiptrace:
                key = 'account_payment__due_date__in'
            require_list = list(range(self.called_at, self.called_to + 1))
            # get common ele in 2 lists
            if not dpd_limit_list:
                values = require_list
            else:
                values = list(set(require_list) & set(dpd_limit_list))

            values = [get_dpd_date(x) for x in values]
            if is_bl_paylater:
                key = 'statement_due_date__in'
        elif self.dpd_condition == DpdConditionChoices.LESS:
            key = 'due_date__in'
            if is_bl_paylater:
                key = 'statement_due_date__in'
            if is_object_skiptrace:
                key = 'account_payment__due_date__gt'
            if not dpd_limit_list:
                values = get_dpd_date(self.called_at)
                key = key.replace('__in', '__gt')
            else:
                values = [get_dpd_date(x) for x in dpd_limit_list if x < self.called_at]
        else:
            return {}

        return {key: values}

    def get_loan_id_filter(self):
        """generate filter for last digit of loan id"""
        loan_filter = {}
        query_filter = {'annotate': {}, 'filter': {}}
        filter_format = '{digit}_last_digit'
        if not self.loan_ids:
            return None

        for loan_id_str in self.loan_ids:
            loan_id_list = loan_id_str.split('-')
            last_digit = len(loan_id_list[0])
            loan_filter_format = filter_format.format(digit=last_digit)

            if len(loan_id_list) == 1:
                loan_id = int(loan_id_list[0])
                if loan_filter_format not in loan_filter:
                    loan_filter[loan_filter_format] = []
                loan_filter[loan_filter_format].append(loan_id)
            else:
                loan_id_min = int(loan_id_list[0])
                loan_id_max = int(loan_id_list[1])
                loan_filter[loan_filter_format] = (loan_id_min, loan_id_max)

        for filter_key, filter_data in list(loan_filter.items()):
            last_digit = int(filter_key[0])
            query_filter['annotate'].update({filter_key: F('loan_id') % 10**last_digit})
            if isinstance(filter_data, list):
                query_filter['filter'].update({filter_key + '__in': filter_data})
            else:
                query_filter['filter'].update({filter_key + '__range': filter_data})

        return query_filter

    @property
    def is_julo_one_product(self):
        return True if self.product == CootekProductLineCodeName.J1 else False
    
    @property
    def is_julo_turbo_product(self):
        return True if self.product == CootekProductLineCodeName.JTURBO else False

    @property
    def is_experiment_late_dpd(self):
        return self.criteria == CriteriaChoices.LATE_DPD_EXPERIMENT

    @property
    def is_unconnected_late_dpd(self):
        return self.criteria == CriteriaChoices.UNCONNECTED_LATE_DPD

    @property
    def unconnected_late_dpd_time(self):
        if not self.is_unconnected_late_dpd:
            return ''

        return self.strategy_name.split('_')[-1]

    @property
    def is_bucket_3_unconnected_late_dpd(self):
        return self.is_unconnected_late_dpd and self.called_at == 41 and self.called_to == 70

    @property
    def is_allowed_product(self):
        return self.product in {
            CootekProductLineCodeName.J1, CootekProductLineCodeName.DANA, CootekProductLineCodeName.JTURBO}

    def is_bucket_0(self):
        return self.called_at <= 0
