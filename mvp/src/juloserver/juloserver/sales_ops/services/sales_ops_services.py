import csv
import logging
import math
import os

from dataclasses import dataclass
from datetime import (
    datetime,
)

from bulk_update.helper import bulk_update

from core.templatetags.unit import convert_date_to_string
from rest_framework.exceptions import ValidationError

from juloserver.julo.models import FeatureSetting
from juloserver.promo.constants import PromoCodeCriteriaConst
from juloserver.promo.models import PromoCodeCriteria, PromoCodeAgentMapping
from juloserver.sales_ops.constants import (
    ScoreCriteria, AutodialerConst, QUERY_LIMIT, PROMOTION_AGENT_OFFER_AVAILABLE_AT_LEAST_DAYS,
    BucketCode,
)
from juloserver.sales_ops.exceptions import (
    MissingAccountSegmentHistory,
)
from juloserver.sales_ops.models import (
    SalesOpsAccountSegmentHistory,
    SalesOpsMScore,
    SalesOpsRScore,
    SalesOpsRMScoring,
    SalesOpsAgentAssignment,
    SalesOpsLineupCallbackHistory,
    SalesOpsDailySummary,
    SalesOpsLineupHistory,
    SalesOpsBucket,
    SalesOpsLineup,
    SalesOpsGraduation,
)
from juloserver.sales_ops.serializers import AgentAssingmentCsvImporterSerializer
from juloserver.sales_ops.utils import get_list_int_by_str, chunker
from juloserver.sales_ops.services.autodialer_services import AutodialerDelaySetting

from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Sum

from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import Application
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.sales_ops import tasks
from juloserver.sales_ops.constants import SalesOpsSettingConst, SalesOpsVendorName
from juloserver.sales_ops.services import julo_services
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic


logger = logging.getLogger(__name__)


@dataclass
class RMScoreInfo:
    r_score: int  # flake8: noqa 701 remove the comment after flake8 is upgrade to 3.7
    m_score: int  # flake8: noqa 701 - idem
    account_rm_segment: SalesOpsAccountSegmentHistory = None  # flake8: noqa 701 - idem
    r_score_model: SalesOpsRMScoring = None  # flake8: noqa 701 - idem
    m_score_model: SalesOpsRMScoring = None  # flake8: noqa 701 - idem


class SalesOpsSetting:
    @staticmethod
    def get_available_limit():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT,
            SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_LIMIT
        )

        try:
            setting_value = int(setting_value)
        except (ValueError, TypeError):
            logger.warning('Invalid integer type: {}'.format(setting_value))
            setting_value = SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_LIMIT

        return setting_value

    @staticmethod
    def get_delay_paid_collection_call_day():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_DELAY_PAID_COLLECTION_CALL_DAY,
            SalesOpsSettingConst.DEFAULT_LINEUP_DELAY_PAID_COLLECTION_CALL_DAY
        )

        return timedelta(days=int(setting_value))

    @staticmethod
    def get_loan_restriction_call_day():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_LOAN_RESTRICTION_CALL_DAY,
            SalesOpsSettingConst.DEFAULT_LINEUP_LOAN_RESTRICTION_CALL_DAY,
        )
        return int(setting_value)

    @staticmethod
    def get_loan_disbursement_date_call_day():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY,
            SalesOpsSettingConst.DEFAULT_LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY,
        )
        return int(setting_value)

    @staticmethod
    def get_sales_ops_rpc_delay_call_hour():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR,
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR,
        )
        return int(setting_value)

    @staticmethod
    def get_sales_ops_non_rpc_attempt_count():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT,
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT,
        )
        return int(setting_value)

    @staticmethod
    def get_sales_ops_non_rpc_delay_call_hour():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR,
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR,
        )
        return int(setting_value)

    @staticmethod
    def get_sales_ops_non_rpc_final_delay_call_hour():
        setting_value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR,
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR,
        )
        return int(setting_value)

    @staticmethod
    def get_r_percentages():
        return get_list_int_by_str(julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.RECENCY_PERCENTAGES,
            SalesOpsSettingConst.DEFAULT_RECENCY_PERCENTAGES
        ))

    @staticmethod
    def get_m_percentages():
        return get_list_int_by_str(julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.MONETARY_PERCENTAGES,
            SalesOpsSettingConst.DEFAULT_MONETARY_PERCENTAGES,
        ))

    @staticmethod
    def get_autodialer_delay_setting():
        setting_value = julo_services.get_sales_ops_setting()
        if setting_value is None:
            return AutodialerDelaySetting()

        delay_setting = AutodialerDelaySetting(
            rpc_delay_hour=setting_value.get(
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR,
                SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR
            ),
            rpc_assignment_delay_hour=setting_value.get(
                SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR,
                SalesOpsSettingConst.DEFAULT_AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR
            ),
            non_rpc_delay_hour=setting_value.get(
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR,
                SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR
            ),
            non_rpc_final_delay_hour=setting_value.get(
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR,
                SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR
            ),
            non_rpc_final_attempt_count=setting_value.get(
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT,
                SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT
            ),
        )

        return delay_setting


class InitSalesOpsLineup:
    def __init__(self, query_limit=QUERY_LIMIT):
        setting_value = julo_services.get_sales_ops_setting()
        self.lineup_min_available_days = setting_value.get(
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_DAYS,
            SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_DAYS
        )
        self.lineup_max_used_limit_percentage = setting_value.get(
            SalesOpsSettingConst.LINEUP_MAX_USED_LIMIT_PERCENTAGE,
            SalesOpsSettingConst.DEFAULT_LINEUP_MAX_USED_LIMIT_PERCENTAGE
        )
        self.setting_delay_paid_collection_day = \
            SalesOpsSetting.get_delay_paid_collection_call_day()
        self.setting_available_limit = SalesOpsSetting.get_available_limit()
        self.lineup_loan_restriction_call_day = setting_value.get(
            SalesOpsSettingConst.LINEUP_LOAN_RESTRICTION_CALL_DAY,
            SalesOpsSettingConst.DEFAULT_LINEUP_LOAN_RESTRICTION_CALL_DAY,
        )
        self.lineup_disbursement_restriction_call_day = setting_value.get(
            SalesOpsSettingConst.LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY,
            SalesOpsSettingConst.DEFAULT_LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY,
        )
        self.lineup_rpc_delay_call_hour = \
            SalesOpsSetting.get_sales_ops_rpc_delay_call_hour()
        self.lineup_non_rpc_attempt = \
            SalesOpsSetting.get_sales_ops_non_rpc_attempt_count()
        self.lineup_non_rpc_delay_call_hour = \
            SalesOpsSetting.get_sales_ops_non_rpc_delay_call_hour()
        self.lineup_non_rpc_final_delay_call_hour = \
            SalesOpsSetting.get_sales_ops_non_rpc_final_delay_call_hour()
        self.query_limit = query_limit

    def generate_query(self):
        query = Application.objects.get_queryset().only('account_id').exclude(
            is_deleted=True
        ).distinct()
        query = self._is_active_j1_account_query(query)
        query = self._has_sufficient_available_limit(query)
        return query

    def _is_active_j1_account_query(self, application_query):
        return application_query.filter(
            Q(account__account_lookup__name='JULO1', account__status_id=AccountConstant.STATUS_CODE.active),
            Q(product_line_id=ProductLineCodes().J1, workflow__name=WorkflowConst.JULO_ONE,
              partner__isnull=True, application_status_id=ApplicationStatusCodes.LOC_APPROVED),
        )

    def _has_sufficient_available_limit(self, application_query):
        return application_query.filter(
            Q(account__accountlimit__available_limit__gt=self.setting_available_limit)
        )

    def _filter_invalid_account_ids_pass_affordability(self, account_ids):
        """
        Get account ids that are not passed affordability check.
        Need application level because django 1.9 does not support subquery
        """
        query = AccountPayment.objects.not_paid_active().filter(
            Q(account_id__in=account_ids),
        ).distinct('account_id').order_by('account_id', 'due_date')
        affordability_field_name = \
            'account__accountlimit__latest_affordability_history__affordability_value'
        account_affordability_list = query.values(
            'account_id', 'principal_amount', 'interest_amount',
            affordability_field_name,
        )
        return [
            item['account_id'] for item in account_affordability_list
            if item['principal_amount'] + item['interest_amount'] >= item[affordability_field_name]
        ]

    def _filter_application_restriction(self, account_ids):
        return julo_services.filter_invalid_account_ids_application_restriction(
            account_ids, self.lineup_min_available_days
        )

    def _filter_account_limit_restriction(self, account_ids):
        return julo_services.filter_invalid_account_limit_restriction(
            account_ids, self.lineup_max_used_limit_percentage
        )

    def _filter_blocked_sales_ops_users(self, account_ids):
        now = timezone.localtime(timezone.now())
        return SalesOpsLineup.objects.\
            filter(
                account_id__in=account_ids,
                inactive_until__gt=now,
            ).\
            values_list('account_id', flat=True)

    def _filter_invalid_account_ids_has_rpc(self, account_ids):
        """
        Get account ids that are invalid with latest success RPC call <= 30 days
        """
        rpc_delay_threshold = timezone.localtime(timezone.now()) - timedelta(
            hours=self.lineup_rpc_delay_call_hour
        )

        sales_ops_lineup_ids = list(
            SalesOpsLineup.objects.filter(
                account_id__in=account_ids
            ).values_list('id', flat=True)
        )

        latest_rpc_agent_assignment_ids = list(
            SalesOpsAgentAssignment.objects.filter(
                lineup_id__in=sales_ops_lineup_ids,
                completed_date__gt=rpc_delay_threshold,
            ).values_list('id', flat=True)
        )

        return SalesOpsLineup.objects.filter(
            latest_rpc_agent_assignment_id__in=latest_rpc_agent_assignment_ids
        ).values_list('account_id', flat=True)

    def _filter_invalid_account_ids_has_non_rpc(self, account_ids):
        """
        Get account ids that are invalid with latest non RPC call
            + Non RPC attempt < 2, latest non RPC call <= 15 hours
            + Non RPC attempt >= 2, latest_non RPC call <= 7 days
        """
        now = timezone.localtime(timezone.now())
        non_rpc_delay_threshold = now - timedelta(hours=self.lineup_non_rpc_delay_call_hour)
        non_rpc_final_delay_threshold = now - timedelta(
            hours=self.lineup_non_rpc_final_delay_call_hour
        )

        sales_ops_lineup_ids = list(
            SalesOpsLineup.objects.filter(
                account_id__in=account_ids
            ).values_list('id', flat=True)
        )

        latest_agent_assignment_ids = list(
            SalesOpsAgentAssignment.objects.filter(
                Q(lineup_id__in=sales_ops_lineup_ids),
                Q(
                    Q(
                        non_rpc_attempt__lt=self.lineup_non_rpc_attempt,
                        completed_date__gt=non_rpc_delay_threshold,
                    )
                    | Q(
                        non_rpc_attempt__gte=self.lineup_non_rpc_attempt,
                        completed_date__gt=non_rpc_final_delay_threshold,
                    )
                ),
            ).values_list('id', flat=True)
        )

        return SalesOpsLineup.objects.filter(
            latest_agent_assignment_id__in=latest_agent_assignment_ids
        ).values_list('account_id', flat=True)

    def _filter_invalid_account_ids_has_collection_calls(self, account_ids):
        """
        Get account ids that are DPD <= 5 the next account payment
        """
        dpd_time_delta = timedelta(days=5)
        return julo_services.filter_invalid_account_ids_collection_restriction(
            account_ids, dpd_time_delta
        )

    def _filter_invalid_account_ids_has_paid_prev_collection_calls(self, account_ids):
        """
        Get account ids that are has paid previous collection calls from the paid account_payment
        """
        return julo_services.filter_invalid_account_ids_paid_collection_restriction(
            account_ids, self.setting_delay_paid_collection_day)

    def _filter_invalid_account_ids_max_paid_date_restriction(self, account_ids):
        """
        Get account ids that have invalid max paid date
        """
        return julo_services.filter_invalid_account_ids_loan_restriction(
            account_ids, self.lineup_loan_restriction_call_day)

    def _filter_invalid_account_ids_disbursement_restriction(self, account_ids):
        """
        Get account ids that have invalid with disbursement date < 14 days
        """
        return julo_services.filter_invalid_account_ids_disbursement_date_restriction(
            account_ids, self.lineup_disbursement_restriction_call_day)

    def _filter_suspended_users(self, account_ids):
        return julo_services.filter_suspended_users(account_ids)

    def create_sales_ops_daily_summary(self, total_count):
        return SalesOpsDailySummary.objects.create(
            total=total_count,
            progress=0,
            number_of_task=math.ceil(total_count / self.query_limit),
            new_sales_ops=0,
            update_sales_ops=0,
        )

    def update_sales_ops_daily_summary(self, daily_summary_id, count_new_accounts,
                                       count_update_accounts):
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            daily_summary = SalesOpsDailySummary.objects.select_for_update().get(
                pk=daily_summary_id
            )
            daily_summary.update_safely(
                progress=daily_summary.progress + 1,
                new_sales_ops=daily_summary.new_sales_ops + count_new_accounts,
                update_sales_ops=daily_summary.update_sales_ops + count_update_accounts
            )
        if daily_summary.progress == daily_summary.number_of_task:
            self.update_inactive_lineup(daily_summary.cdate)
            tasks.sync_sales_ops_lineup.delay()

    def prepare_data(self):
        query = self.generate_query().order_by('account_id')

        # Force to evaluate queryset
        account_ids = list(query.values_list('account_id', flat=True))
        total_count = len(account_ids)
        daily_summary = self.create_sales_ops_daily_summary(total_count)
        for sub_account_ids in chunker(account_ids, self.query_limit):
            tasks.process_sales_ops_lineup_account_ids.delay(sub_account_ids, daily_summary.id)

    def handle(self, account_ids, daily_summary_id):
        invalid_checks = [
            self._filter_suspended_users,
            self._filter_invalid_account_ids_pass_affordability,
            self._filter_application_restriction,
            self._filter_account_limit_restriction,
            self._filter_blocked_sales_ops_users,
            self._filter_invalid_account_ids_has_rpc,
            self._filter_invalid_account_ids_has_non_rpc,
            self._filter_invalid_account_ids_has_collection_calls,
            self._filter_invalid_account_ids_has_paid_prev_collection_calls,
            self._filter_invalid_account_ids_max_paid_date_restriction,
            self._filter_invalid_account_ids_disbursement_restriction,
        ]
        for invalid_check in invalid_checks:
            invalid_account_ids = invalid_check(account_ids)
            account_ids = [
                account_id
                for account_id in account_ids
                if account_id not in invalid_account_ids
            ]

        # latest lineup info
        latest_application_id_dict = julo_services.get_bulk_latest_application_id_dict(account_ids)
        latest_disbursed_loan_id_dict = julo_services.get_bulk_latest_disbursed_loan_id_dict(account_ids)
        latest_account_limit_id_dict = julo_services.get_bulk_latest_account_limit_id_dict(account_ids)
        latest_account_property_id_dict = julo_services.get_bulk_latest_account_property_id_dict(account_ids)

        lineups = SalesOpsLineup.objects.filter(account_id__in=account_ids).all()
        update_account_ids = [lineup.account_id for lineup in lineups]
        new_account_ids = [account_id for account_id in account_ids if account_id not in update_account_ids]

        # Create the new lineups data
        for account_id in new_account_ids:
            SalesOpsLineup.objects.create(
                account_id=account_id,
                latest_application_id=latest_application_id_dict.get(account_id),
                latest_disbursed_loan_id=latest_disbursed_loan_id_dict.get(account_id),
                latest_account_limit_id=latest_account_limit_id_dict.get(account_id),
                latest_account_property_id=latest_account_property_id_dict.get(account_id),
                is_active=True
            )

        # update the current lineup data
        # No need to update the latest information. Will be updated on other process
        update_account_ids = []
        for lineup in lineups:
            account_id = lineup.account_id
            lineup.latest_application_id = latest_application_id_dict.get(account_id)
            lineup.latest_disbursed_loan_id = latest_disbursed_loan_id_dict.get(account_id)
            lineup.latest_account_limit_id = latest_account_limit_id_dict.get(account_id)
            lineup.latest_account_property_id = latest_account_property_id_dict.get(account_id)
            lineup.is_active = True
            if len(lineup.tracker.changed()) > 0:
                lineup.save()
            else:
                update_account_ids.append(account_id)
        if update_account_ids:
            SalesOpsLineup.objects.filter(account_id__in=update_account_ids).update(
                udate=timezone.localtime(timezone.now()),
            )
        self.update_sales_ops_daily_summary(
            daily_summary_id, len(new_account_ids), len(update_account_ids)
        )

    def update_inactive_lineup(self, start_time):
        qs = SalesOpsLineup.objects.filter(is_active=True, udate__lt=start_time)
        sales_ops_lineup_ids = qs.values_list('id', flat=True)
        for sub_sales_ops_lineup_ids in chunker(sales_ops_lineup_ids.iterator(), self.query_limit):
            self.update_inactive_lineup_by_batch(sub_sales_ops_lineup_ids)

    @staticmethod
    def update_inactive_lineup_by_batch(lineup_ids):
        SalesOpsLineup.objects.filter(id__in=lineup_ids).update(is_active=False)
        # Deactivate old agent assignment session
        SalesOpsAgentAssignment.objects.filter(
            lineup_id__in=lineup_ids,
            is_active=True,
        ).update(is_active=False)
        sales_ops_lineup_histories = []
        for lineup_id in lineup_ids:
            sales_ops_lineup_histories.append(SalesOpsLineupHistory(
                lineup_id=lineup_id,
                old_values={"is_active": True},
                new_values={"is_active": False},
            ))
        SalesOpsLineupHistory.objects.bulk_create(sales_ops_lineup_histories)


def count_sales_ops_bucket_on_dashboard():
    sales_ops_feature = FeatureSetting.objects.get_or_none(
        feature_name="sales_ops", is_active=True
    )
    using_bucket_logic = using_sales_ops_bucket_logic()
    vendor_name = SalesOpsVendorName.IN_HOUSE if using_bucket_logic else None
    count_active_lineup = SalesOpsLineup.objects.count_active_lineup(
        vendor_name, exclude_buckets=[BucketCode.GRADUATION]
    )
    result = [(None, 'SALES OPS', count_active_lineup)]

    if sales_ops_feature:
        if using_bucket_logic:
            buckets = SalesOpsBucket.objects.filter(
                is_active=True).values('code', 'is_active').order_by('code')
        else:
            parameters = sales_ops_feature.parameters
            buckets = parameters.get("buckets", [])

        for bucket in buckets:
            if not bucket["is_active"]:
                continue
            count_bucket = SalesOpsLineup.objects.count_bucket(bucket["code"], vendor_name)
            if count_bucket:
                result.append((bucket["code"], bucket["code"], count_bucket))

    return tuple(result)


def get_bucket_code_map_with_bucket_name(exclude_buckets=None):
    sales_ops_feature = FeatureSetting.objects.get_or_none(
        feature_name="sales_ops", is_active=True
    )
    using_bucket_logic = using_sales_ops_bucket_logic()

    result = [(None, 'SALES OPS')]
    if sales_ops_feature:
        if using_bucket_logic:
            buckets = SalesOpsBucket.objects.filter(
                is_active=True).values('code', 'name', 'is_active').order_by('code')
        else:
            parameters = sales_ops_feature.parameters
            buckets = parameters.get("buckets", [])

        for bucket in buckets:
            if not bucket['is_active']:
                continue
            if exclude_buckets and bucket['code'] in exclude_buckets:
                continue
            result.append((bucket['code'], bucket['name']))

    return result


def get_bucket_name(current_bucket_code, bucket_code_map=None):
    if not bucket_code_map:
        bucket_code_map = get_bucket_code_map_with_bucket_name()
    for bucket_code, bucket_name in bucket_code_map:
        if current_bucket_code == bucket_code:
            return bucket_name
    return AutodialerConst.SUBJECT


def get_bucket_title(current_bucket_code, buckets_count):
    return get_bucket_name(current_bucket_code, buckets_count) + " - ALL ACCOUNTS"


def get_account_latest_info_dict(account_id):
    latest_account_limit = julo_services.get_latest_account_limit(account_id)
    latest_account_property = julo_services.get_latest_account_property(account_id)
    latest_disbursed_loan = julo_services.get_latest_disbursed_loan(account_id)
    latest_application = julo_services.get_latest_application(account_id)

    return {
        'latest_account_limit_id': getattr(latest_account_limit, 'id', None),
        'latest_account_property_id': getattr(latest_account_property, 'id', None),
        'latest_disbursed_loan_id': getattr(latest_disbursed_loan, 'id', None),
        'latest_application_id': getattr(latest_application, 'id', None),
    }


def update_latest_lineup_info(lineup_id):
    lineup = SalesOpsLineup.objects.get_or_none(id=lineup_id)
    if lineup is None:
        return

    update_data = get_account_latest_info_dict(lineup.account_id)
    lineup.update_safely(**update_data)
    return lineup


def save_setting(parameters):
    monetary_percentages_str = parameters['monetary_percentages']
    recency_percentages_str = parameters['recency_percentages']
    monetary_percentages = get_list_int_by_str(monetary_percentages_str)
    recency_percentages = get_list_int_by_str(recency_percentages_str)
    db_r_percentages = SalesOpsSetting.get_r_percentages()
    db_m_percentages = SalesOpsSetting.get_m_percentages()
    is_changed_m_percentages = False
    is_changed_r_percentages = False
    if monetary_percentages != db_m_percentages:
        is_changed_m_percentages = True
    if recency_percentages != db_r_percentages:
        is_changed_r_percentages = True

    rm_scoring = SalesOpsRMScoring.objects.filter(is_active=True).all()
    m_scoring = rm_scoring.filter(criteria=ScoreCriteria.MONETARY)
    r_scoring = rm_scoring.filter(criteria=ScoreCriteria.RECENCY)
    if is_changed_m_percentages or not m_scoring:
        set_rm_scoring(monetary_percentages, ScoreCriteria.MONETARY)
    if is_changed_r_percentages or not r_scoring:
        set_rm_scoring(recency_percentages, ScoreCriteria.RECENCY)


def set_rm_scoring(percentages, criteria):
    now = timezone.localtime(timezone.now()).date()
    max_percentage = 100
    len_percentages = len(percentages)
    percentage_accumulate = 0
    new_scoring_dict = {}
    for index, value in enumerate(percentages):
        top_percentile = max_percentage - percentage_accumulate
        bottom_percentile = top_percentile - value
        new_scoring_dict[len_percentages - index] = (top_percentile, bottom_percentile)
        percentage_accumulate += value
    existed_scoring_dict = get_existed_rm_scoring_dict(criteria)
    inactive_scores = []
    bulk_create_new_score = []
    for score, percentage in new_scoring_dict.items():
        if not existed_scoring_dict:
            bulk_create_new_score.append(create_rm_scoring_model(
                criteria, new_scoring_dict[score][0], new_scoring_dict[score][1], score, now
            ))
        else:
            if new_scoring_dict[score] == existed_scoring_dict[score]:
                continue
            inactive_scores.append(score)
            bulk_create_new_score.append(create_rm_scoring_model(
                criteria, new_scoring_dict[score][0], new_scoring_dict[score][1], score, now
            ))
    if inactive_scores:
        SalesOpsRMScoring.objects.filter(
            score__in=inactive_scores, criteria=criteria
        ).update(is_active=False)
    if bulk_create_new_score:
        SalesOpsRMScoring.objects.bulk_create(bulk_create_new_score)


def get_existed_rm_scoring_dict(criteria):
    rm_scoring = SalesOpsRMScoring.objects.filter(
        criteria=criteria, is_active=True
    ).order_by('-score').all()
    return {item.score: (item.top_percentile, item.bottom_percentile) for item in rm_scoring}


def create_rm_scoring_model(criteria, top_percentile, bottom_percentile, score, cdate):
    return SalesOpsRMScoring(
        criteria=criteria,
        top_percentile=top_percentile,
        bottom_percentile=bottom_percentile,
        score=score,
        is_active=True,
        cdate=cdate,
    )


def is_account_valid(account):
    # Is not active
    if account.status_id != AccountConstant.STATUS_CODE.active:
        return False

    # Is not J1 Account
    is_julo1_account = julo_services.is_julo1_account(account)
    if not is_julo1_account:
        return False

    # Account is not always active (310)
    status_code_history = julo_services.get_account_status_code_history_list(account.id)
    is_always_active = status_code_history == [] or \
        max(status_code_history) == AccountConstant.STATUS_CODE.active
    if not is_always_active:
        return False

    # Account is suspended
    is_suspended_users = julo_services.filter_suspended_users(account)
    if not is_suspended_users:
        return False

    # Account limit is not above threshold
    account_limit = julo_services.get_latest_account_limit(account.id)
    available_limit_threshold = SalesOpsSetting.get_available_limit()
    if account_limit.available_limit <= available_limit_threshold:
        return False

    setting_value = julo_services.get_sales_ops_setting()
    lineup_min_available_days = setting_value.get(
        SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_DAYS,
        SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_DAYS
    )
    lineup_max_used_limit_percentage = setting_value.get(
        SalesOpsSettingConst.LINEUP_MAX_USED_LIMIT_PERCENTAGE,
        SalesOpsSettingConst.DEFAULT_LINEUP_MAX_USED_LIMIT_PERCENTAGE
    )
    invalid_account_ids = julo_services.filter_invalid_account_ids_application_restriction(
        [account.id], lineup_min_available_days
    )
    if invalid_account_ids:
        return False

    invalid_account_ids = julo_services.filter_invalid_account_limit_restriction(
        [account.id], lineup_max_used_limit_percentage
    )
    if invalid_account_ids:
        return False

    # Next Account payment DPD >=-5
    if julo_services.filter_invalid_account_ids_collection_restriction(
            [account.id], timedelta(days=5)):
        return False

    # Prev Account payment collection call has pass the date.
    expired_delta_time = SalesOpsSetting.get_delay_paid_collection_call_day()
    if julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [account.id], expired_delta_time):
        return False

    # valid if last payment paid date > 7 days
    loan_restriction_call_day = SalesOpsSetting.get_loan_restriction_call_day()
    invalid_account_ids = julo_services.filter_invalid_account_ids_loan_restriction(
        [account.id], loan_restriction_call_day
    )
    if invalid_account_ids:
        return False

    # valid if disbursement date > 14 days
    loan_disbursement_date_call_day = SalesOpsSetting.get_loan_disbursement_date_call_day()
    invalid_account_ids = julo_services.filter_invalid_account_ids_disbursement_date_restriction(
        [account.id], loan_disbursement_date_call_day
    )
    if invalid_account_ids:
        return False

    return True


def get_valid_score_and_log(percentage_score_mappings, record, total_row, criteria):
    """
    this func support get score suitable and build log
    """
    division = total_row - 1 if total_row > 1 else 1
    percentage = math.floor(100 - ((record.ranking-1)/division * 100))
    score_obj = percentage_score_mappings.get(percentage)
    if score_obj is None:
        return None, None
    if criteria == ScoreCriteria.MONETARY:
        score_criteria = {
            'account_limit_id': record.latest_account_limit_id,
            'available_limit': record.available_limit,
            'account_id': record.account_id,
            'score': score_obj.score,
        }
        return score_obj, score_criteria
    elif criteria == ScoreCriteria.RECENCY:
        score_criteria = {
            'latest_active_dates': convert_date_to_string(
                record.latest_active_dates, format_date_type='YYYY-MM-d'
            ),
            'account_id': record.account_id,
            'score': score_obj.score,
        }
        return score_obj, score_criteria

    return None, None


def get_latest_score(account_id):
    """
    Get the latest score info information from `SalesOpsAccountRMSegmentHistory`
    """
    latest_account_segment_history = \
        SalesOpsAccountSegmentHistory.objects.filter(account_id=account_id).order_by('cdate').last()
    if latest_account_segment_history is None:
        raise MissingAccountSegmentHistory('No AccountSegmentHistory yet')

    r_score_model = SalesOpsRMScoring.objects.get(id=latest_account_segment_history.r_score_id)
    m_score_model = SalesOpsRMScoring.objects.get(id=latest_account_segment_history.m_score_id)
    r_score = r_score_model.score
    m_score = m_score_model.score

    return RMScoreInfo(r_score, m_score, latest_account_segment_history, r_score_model, m_score_model)


class AgentAssignmentCsvImporter:
    HEADER_ROW = [
        'account_id', 'agent_id', 'agent_name', 'completed_date'
    ]

    def __init__(self, csv_path):
        if not os.path.isfile(csv_path):
            raise ValueError(f'{csv_path} is not a file.')

        self.csv_path = csv_path

    def validate(self):
        with open(self.csv_path, 'r') as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames != self.HEADER_ROW:
                raise ValidationError(
                    f'Invalid header row: {reader.fieldnames}. Should be {self.HEADER_ROW}'
                )

        return True

    @transaction.atomic
    def save(self):
        with open(self.csv_path, 'r') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if not row['completed_date']:
                    continue

                serializer = AgentAssingmentCsvImporterSerializer(data=row)
                if not serializer.is_valid():
                    raise ValidationError(f'Row is invalid {serializer.errors}. Row: {row}')

                data = serializer.validated_data
                completed_date = timezone.localtime(
                    datetime.combine(data['completed_date'], datetime.min.time())
                )

                lineup = SalesOpsLineup.objects.get_or_none(account_id=data['account_id'])
                if not lineup:
                    lineup = SalesOpsLineup.objects.create(
                        account_id=data['account_id'], is_active=False
                    )

                agent_assignment, is_created = SalesOpsAgentAssignment.objects.get_or_create(
                    lineup_id=lineup.id,
                    agent_id=data['agent_id'],
                    agent_name=data['agent_name'],
                    assignment_date=completed_date,
                    completed_date=completed_date,
                    is_rpc=True,
                    is_active=False
                )

                if not is_created:
                    continue

                # Update the latest agent assignment for the queue
                latest_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
                    pk=lineup.latest_agent_assignment_id
                )
                if (
                    not latest_agent_assignment
                    or latest_agent_assignment.completed_date < agent_assignment.completed_date
                ):
                    lineup.latest_agent_assignment_id = agent_assignment.id
                    lineup.save(update_fields=['latest_agent_assignment_id'])


def get_last_sales_ops_calls(lineup):
    query = (
        SalesOpsAgentAssignment.objects.filter(
            Q(lineup_id=lineup.id),
            Q(is_active=True) | Q(is_active=False, completed_date__isnull=False),
        )
        .distinct('lineup_id', 'is_active')
        .order_by('lineup_id', 'is_active', '-udate')
    )
    return query.all()


def create_sales_ops_lineup_callback_history(callback_at, callback_note, lineup_id, user):
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        SalesOpsLineupCallbackHistory.objects.create(
            callback_at=callback_at,
            note=callback_note,
            lineup_id=lineup_id,
            changed_by=user.id
        )
        SalesOpsLineup.objects.filter(id=lineup_id).update(latest_callback_at=callback_at)


def get_callback_histories(lineup_id):
    return SalesOpsLineupCallbackHistory.objects.filter(
        lineup_id=lineup_id
    ).order_by('-cdate')[:10]


def can_submit_lineup_skiptrace_history(lineup):
    latest_agent_assignment_id = lineup.latest_agent_assignment_id
    latest_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
        pk=latest_agent_assignment_id
    )
    if not latest_agent_assignment or (
        latest_agent_assignment.completed_date and not latest_agent_assignment.is_rpc
    ):
        return True

    if latest_agent_assignment.is_active:
        return False

    delay_setting = SalesOpsSetting.get_autodialer_delay_setting()
    rpc_delay_hour = delay_setting.rpc_delay_hour
    now = timezone.localtime(timezone.now())
    valid_rpc_call_datetime = now - timedelta(hours=rpc_delay_hour)

    completed_date = latest_agent_assignment.completed_date
    return completed_date and completed_date <= valid_rpc_call_datetime


def get_bucket_code(sales_ops_feature, r_score):
    if sales_ops_feature:
        parameters = sales_ops_feature.parameters
        buckets = parameters.get("buckets", [])
        for bucket in buckets:
            if bucket["criteria"] == ScoreCriteria.RECENCY and r_score in bucket["scores"]:
                return bucket["code"]
    return


# handle with bulk for sales ops prioritization
def bulk_create_account_segment_history(lineups):
    account_ids = {lineup.account_id for lineup in lineups}
    accounts_r_score_mappings = bulk_calculate_recency_score(account_ids)
    accounts_m_score_mappings = bulk_calculate_monetary_score(account_ids)
    create_list = []
    result = {}
    for account_id in account_ids:
        account_m_score = accounts_m_score_mappings.get(account_id)
        account_r_score = accounts_r_score_mappings.get(account_id)
        if not account_m_score or not account_r_score:
            continue

        m_score_obj, m_score_criteria = account_m_score
        r_score_obj, r_score_criteria = account_r_score
        create_list.append(SalesOpsAccountSegmentHistory(
            account_id=account_id,
            m_score_id=m_score_obj.id,
            r_score_id=r_score_obj.id,
            log={
                'r_score_criteria': r_score_criteria,
                'm_score_criteria': m_score_criteria,
            },
        ))
        result[account_id] = (m_score_obj.score, r_score_obj.score)
    SalesOpsAccountSegmentHistory.objects.bulk_create(create_list)
    return result


def get_percentage_score_mappings(criteria):
    rm_scores = list(SalesOpsRMScoring.objects.filter(
        criteria=criteria, is_active=True,
    ).order_by('-top_percentile').all())
    result = {}
    for rm_score in rm_scores:
        top_percentile = int(rm_score.top_percentile)
        if rm_score.top_percentile == 100:
            top_percentile += 1
        bottom_percentile = int(rm_score.bottom_percentile)
        for percentile in range(bottom_percentile, top_percentile):
            result[percentile] = rm_score
    return result


def bulk_calculate_monetary_score(account_ids):
    result = {}
    sales_ops_m_scores = SalesOpsMScore.objects.filter(account_id__in=account_ids)
    total_row = SalesOpsMScore.objects.count()
    percentage_score_mappings = get_percentage_score_mappings(ScoreCriteria.MONETARY)
    for sales_ops_m_score in sales_ops_m_scores:
        score_obj, m_score_criteria = get_valid_score_and_log(
            percentage_score_mappings, sales_ops_m_score, total_row, ScoreCriteria.MONETARY
        )
        result[sales_ops_m_score.account_id] = (score_obj, m_score_criteria)
    return result


def bulk_calculate_recency_score(account_ids):
    result = {}
    sales_ops_r_scores = SalesOpsRScore.objects.filter(account_id__in=account_ids)
    total_row = SalesOpsRScore.objects.count()
    percentage_score_mappings = get_percentage_score_mappings(ScoreCriteria.RECENCY)
    for sales_ops_r_score in sales_ops_r_scores:
        score_obj, r_score_criteria = get_valid_score_and_log(
            percentage_score_mappings, sales_ops_r_score, total_row, ScoreCriteria.RECENCY
        )
        result[sales_ops_r_score.account_id] = (score_obj, r_score_criteria)
    return result


def get_sales_ops_graduation_and_ranking(lineups):
    account_ids = {lineup.account_id for lineup in lineups}
    sales_ops_graduations = SalesOpsGraduation.objects.filter(account_id__in=account_ids)
    return {
        sales_ops_graduation.account_id: sales_ops_graduation.ranking
        for sales_ops_graduation in sales_ops_graduations
    }


def bulk_update_lineups(lineups, account_score_mappings):
    update_lineups = []
    sales_ops_feature = FeatureSetting.objects.get_or_none(feature_name='sales_ops', is_active=True)
    if not sales_ops_feature:
        return

    graduation_account_rank_mappings = get_sales_ops_graduation_and_ranking(lineups)
    parameters = sales_ops_feature.parameters
    monetary_percentages_str = parameters['monetary_percentages']
    monetary_percentages = get_list_int_by_str(monetary_percentages_str)
    for lineup in lineups:
        account_id = lineup.account_id
        if account_id in graduation_account_rank_mappings:
            lineup.bucket_code = BucketCode.GRADUATION
            lineup.prioritization = graduation_account_rank_mappings[account_id]
        elif account_id in account_score_mappings:
            m_score, r_score = account_score_mappings[account_id]
            lineup.bucket_code = get_bucket_code(sales_ops_feature, r_score)
            lineup.prioritization = len(monetary_percentages) - m_score + 1
        else:
            continue

        lineup.udate = timezone.localtime(timezone.now())
        update_lineups.append(lineup)
    bulk_update(update_lineups, update_fields=['bucket_code', 'prioritization', 'udate'])


def get_promotion_mapping_by_agent(agent_id):
    promotion_mapping = PromoCodeAgentMapping.objects.filter(
        agent_id=agent_id, promo_code__is_active=True
    ).last()
    return promotion_mapping.promo_code if promotion_mapping else None


def validate_promo_code_by_r_score(promo_code, r_score):
    criterias = promo_code.criteria or []
    promo_criterias = PromoCodeCriteria.objects.filter(
        id__in=criterias, type=PromoCodeCriteriaConst.R_SCORE
    )
    if not promo_criterias:
        # no criteria mean all
        return True

    for promo_criteria in promo_criterias:
        if r_score in promo_criteria.value['r_scores']:
            return True

    return False


def get_minimum_transaction_promo_code(promo_code):
    promo_code_criterias = promo_code.criteria
    min_tnx_amount_config = PromoCodeCriteria.objects.filter(
        id__in=promo_code_criterias, type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT
    ).last()
    min_transaction_amount = 0
    if min_tnx_amount_config:
        min_transaction_amount = min_tnx_amount_config.value['minimum_loan_amount']

    return min_transaction_amount


def using_sales_ops_bucket_logic():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_BUCKET_LOGIC,
        is_active=True
    ).exists()


def update_vendor_name_when_lineups_lt_vendors(total_lineups, lineup_ids, vendor_mappings):
    update_lineups = []
    udate = timezone.localtime(timezone.now())
    for i in range(0, total_lineups):
        update_lineups.append(
            SalesOpsLineup(
                pk=lineup_ids[i],
                vendor_name=vendor_mappings[i].vendor.name,
                udate=udate
            )
        )
    bulk_update(update_lineups, update_fields=['vendor_name', 'udate'])


def update_vendor_name_to_lineups(bucket, lineup_ids):
    vendor_mappings = bucket.vendor_mappings.filter(is_active=True)
    total_ratio = bucket.total_ratio
    total_vendors = len(vendor_mappings)
    total_lineups = len(lineup_ids)
    start = 0

    # if total_vendors = 0 => no vendor mapping found => update vendor_name to default value
    if total_vendors == 0:
        SalesOpsLineup.objects.filter(pk__in=lineup_ids).update(
            vendor_name=SalesOpsVendorName.IN_HOUSE
        )
        return

    # if total_vendors > total_lineups => pick one vendor for one lineup
    if total_vendors > total_lineups:
        update_vendor_name_when_lineups_lt_vendors(total_lineups, lineup_ids, vendor_mappings)
        return

    # update vendor_name for each buckets, skip last vendor
    # 1. vendor_ratio / total_ratio => percent_vendor
    # 2. percent_vendor * total lineups => total lineups per vendor
    if total_vendors > 1:
        for vendor_mapping in vendor_mappings[:total_vendors - 1]:
            percent_of_lineups = round((vendor_mapping.ratio / total_ratio), 2)
            total_vendor_lineups = round(percent_of_lineups * total_lineups)

            # split lineups by total_vendor_lineups and update vendor_name
            update_lineup_ids = lineup_ids[start: start + total_vendor_lineups]
            SalesOpsLineup.objects.filter(
                pk__in=update_lineup_ids
            ).update(vendor_name=vendor_mapping.vendor.name)

            start += total_vendor_lineups

    # get the rest of lineups for last vendor
    last_vendor = vendor_mappings[total_vendors-1]
    SalesOpsLineup.objects.filter(
        pk__in=lineup_ids[start:]).update(vendor_name=last_vendor.vendor.name)
    logger.info(
        {
            'action': 'update_vendor_name_to_lineups',
            'bucket': bucket.code,
            'lineup_ids': lineup_ids,
            'vendor_mappings': vendor_mappings,
            'new_vendor_name': last_vendor.vendor.name,
        }
    )


def bulk_update_bucket_lineups_logic(lineup_ids):
    lineups = SalesOpsLineup.objects.filter(pk__in=lineup_ids).values('pk', 'bucket_code')
    buckets = SalesOpsBucket.objects.prefetch_related(
        'vendor_mappings', 'vendor_mappings__vendor'
    ).filter(
        Q(is_active=True),
        Q(
            Q(vendor_mappings__isnull=True) | Q(vendor_mappings__is_active=True)
        )
    ).annotate(
        total_ratio=Sum('vendor_mappings__ratio')
    )

    bucket_code_lineups = {}
    for lineup in lineups:
        bucket_code_lineups.setdefault(lineup['bucket_code'], []).append(lineup['pk'])

    for bucket in buckets:
        lineup_ids = bucket_code_lineups.get(bucket.code)
        if lineup_ids:
            with db_transactions_atomic(DbConnectionAlias.utilization()):
                update_vendor_name_to_lineups(bucket, lineup_ids)
