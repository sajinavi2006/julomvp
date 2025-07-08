import logging
from dateutil.relativedelta import relativedelta
import datetime
from django.utils import timezone
from typing import Tuple
from collections import defaultdict
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting

from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.sales_ops.constants import (
    ScoreCriteria,
    SalesOpsSettingConst,
)
from juloserver.sales_ops.models import (
    SalesOpsBucket,
    SalesOpsLineup,
    SalesOpsRMScoringConfig,
    SalesOpsPrepareData,
)


logger = logging.getLogger(__name__)


def classify_rm_scoring(account_ids):
    sales_ops_prepare_data_queryset = SalesOpsPrepareData.objects.filter(
        account_id__in=account_ids
    )
    rm_score_mappings = get_rm_scoring_config_mappings()

    result_list = []
    unscored_account_ids = []

    for sales_ops_prepare_data in sales_ops_prepare_data_queryset:
        account_m_score = classify_m_score(sales_ops_prepare_data, rm_score_mappings)
        account_r_score = classify_r_score(
            sales_ops_prepare_data,
            rm_score_mappings,
            sales_ops_prepare_data.customer_type
        )

        if not (account_m_score and account_r_score):
            unscored_account_ids.append(sales_ops_prepare_data.account_id)
            continue

        m_score_id, m_score = account_m_score
        r_score_id, r_score = account_r_score
        result_list.append({
            'account_id': sales_ops_prepare_data.account_id,
            'customer_type': sales_ops_prepare_data.customer_type,
            'm_score': m_score,
            'm_score_id': m_score_id,
            'r_score': r_score,
            'r_score_id': r_score_id,
            'available_limit': sales_ops_prepare_data.available_limit,
        })

    if len(unscored_account_ids):
        logger.info(
            {
                'action': 'classify_rm_scoring',
                'message': 'Account does not have m_score or r_score',
                'unscored_account_ids': unscored_account_ids,
            }
        )

    return result_list


def get_rm_scoring_config_mappings():
    """
    Returns: A dictionary with 4 keys ['monetary', 'recency_ftc', 'recency_repeat_os', 'recency_repeat_no_os']
    The resulting dictionary structure as follows:
        {
            <key>: {
                'field_name': <field_name_value>,
                'data': {
                    <score_obj_id>: {
                        'min_value': <min_value>,
                        'max_value': <max_value>,
                        'score': <score_value>
                    }
                }
            }
        }
    """
    sales_ops_rm_score = SalesOpsRMScoringConfig.objects.filter(is_active=True)
    result = defaultdict(lambda: {'field_name': '', 'data': {}})

    for score_obj in sales_ops_rm_score:
        key = (
            score_obj.criteria
            if score_obj.criteria == ScoreCriteria.MONETARY
            else "{}_{}".format(score_obj.criteria, score_obj.customer_type)
        )

        result[key]['field_name'] = score_obj.field_name
        result[key]['data'][score_obj.id] = {
            'min_value': score_obj.min_value or float('-inf'),
            'max_value': score_obj.max_value or float('inf'),
            'score': score_obj.score,
        }

    return dict(result)


def classify_m_score(prepare_data_record, rm_scoring_config_mappings):
    monetary_score_mappings = rm_scoring_config_mappings.get(ScoreCriteria.MONETARY, {})

    return determine_score_based_on_criteria(
        prepare_data_record=prepare_data_record,
        criteria_mappings=monetary_score_mappings
    )


def classify_r_score(prepare_data_record, rm_scoring_config_mappings, customer_type):
    key = "{}_{}".format(ScoreCriteria.RECENCY, customer_type)
    recency_score_mappings = rm_scoring_config_mappings.get(key, {})

    return determine_score_based_on_criteria(
        prepare_data_record=prepare_data_record,
        criteria_mappings=recency_score_mappings
    )


def determine_score_based_on_criteria(prepare_data_record, criteria_mappings):
    """
    For example: criteria_mappings = {
                        'field_name': 'last_loan_fund_transfer_ts',
                        'data': {
                                8: {'min_value': 14, 'max_value': 30, 'r_score': 4},
                                9: {'min_value': 30, 'max_value': 60, 'r_score': 3},
                                10: {'min_value': 60, 'max_value': 90, 'r_score': 2},
                                11: {'min_value': 90, 'max_value': inf, 'r_score': 1}
                            }
                        }
    Returns: a tuple of (score_id, score), or None if no score matches.
    """
    # Get data dynamically based on the field name
    field_name = criteria_mappings.get('field_name')
    field_value = getattr(prepare_data_record, field_name)

    for score_id, limits in criteria_mappings['data'].items():
        if limits['min_value'] < field_value <= limits['max_value']:
            return score_id, limits['score']
    return None


def generate_sales_ops_line_up(data: list) -> Tuple[int, int]:
    """
    Generate sales operations line up based on the given data and daily summary ID.

    This function groups the data by customer type, r_score and m_score,
        and then assigns a bucket code to each account ID.
    It updates the sales operations line up by creating new line ups,
        updating existing line ups, and updating the daily summary.

    Args:
        data (dict): From the classify_rm_scoring function.

    Returns:
        new_lineup_count (int): The number of new line ups created.
        num_updated (int): The number of line ups updated.
    """

    # group = {('customer_type', 'r_score', 'm_score'): [account_id, account_id, ...]}
    group = build_group_on_customer_type_rm_score(data)
    group_keys = list(group.keys())

    # assign bucket code to each account using round-robin
    bucket_assignments = assign_bucket_code_to_accounts(group, group_keys)
    new_lineup_objs, update_bucket_lineups = determine_new_update_lineups(bucket_assignments)
    num_updated = 0

    with db_transactions_atomic(DbConnectionAlias.transaction()):
        # create new lineups
        SalesOpsLineup.objects.bulk_create(new_lineup_objs)

        # update exists lineup with bucket_code and active status
        num_updated = update_sales_ops_lineup_with_active_status(update_bucket_lineups)

    # logging section
    log_bucket_assignments = {
        bucket_code: len(acc_ids) for bucket_code, acc_ids in bucket_assignments.items()
    }
    logger.info(
        {
            'action': 'generate_sales_ops_line_up',
            'list_account_ids': log_bucket_assignments,
        }
    )

    return len(new_lineup_objs), num_updated


def build_group_on_customer_type_rm_score(data_list: list) -> dict:
    """
    Grouping data based on customer type, r_score and m_score.
    Returns:
        group: {('customer_type', 'r_score', 'm_score'): [account_id, account_id, ...]}
    """
    group = defaultdict(list)
    for data in data_list:
        account_id = data['account_id']
        g_key = (data['customer_type'], data['r_score'], data['m_score'])

        group[g_key].append(account_id)

    return group


def update_sales_ops_lineup_with_active_status(bucket_lineups: dict) -> int:
    """
    Input:
        bucket_lineup: {bucket: [account_id, account_id, ...]}
    Returns:
        num_updated: int
    """
    next_reset_bucket_date = get_next_reset_bucket_date()
    num_updated = 0
    for bucket_code, account_ids in bucket_lineups.items():
        SalesOpsLineup.objects.filter(account_id__in=account_ids).update(
            is_active=True,
            bucket_code=bucket_code,
            next_reset_bucket_date=next_reset_bucket_date,
        )
        num_updated += len(account_ids)

    return num_updated


def assign_bucket_code_to_accounts(group: dict, group_keys: list) -> dict:
    """
    Assign bucket code to accounts
    Returns:
      - bucket_assignments: {bucket_code: [account_id, ...]}
    """
    bucket_codes = list(
        SalesOpsBucket.objects
        .filter(is_active=True)
        .values_list('code', flat=True)
        .order_by('id')
    )
    n_bucket = len(bucket_codes)
    remain_account_ids = []

    # assign bucket code to each account using round-robin
    bucket_assignments = defaultdict(list)
    for group_key in group_keys:
        account_ids = group[group_key]
        step = len(account_ids) // n_bucket
        i = 0
        for bucket_code in bucket_codes:
            bucket_assignments[bucket_code].extend(account_ids[i:i+step])
            i += step
        remain_account_ids.extend(account_ids[i:])

    # assign remaining account to bucket
    bucket_idx = 0
    for account_id in remain_account_ids:
        bucket_code = bucket_codes[bucket_idx]
        bucket_assignments[bucket_code].append(account_id)
        bucket_idx = (bucket_idx + 1) % n_bucket

    return bucket_assignments


def determine_new_update_lineups(bucket_assignments: dict) -> Tuple[list, dict]:
    """
    Input:
        bucket_assignments: {bucket_code: [account_id, ...]}
    Returns:
        new_lineup_objs: [new_lineup_obj, new_lineup_obj, ...]
        update_bucket_lineups: {bucket_code: [update_account_id, update_account_id, ...]}
    """
    next_reset_bucket_date = get_next_reset_bucket_date()
    new_lineup_objs = []
    update_bucket_lineups = {}  # {bucket_code: [update_account_id, update_account_id, ...]}
    for bucket_code, account_ids in bucket_assignments.items():
        exists_account_ids = (
            SalesOpsLineup.objects
            .filter(account_id__in=account_ids)
            .values_list('account_id', flat=True)
        )
        update_bucket_lineups[bucket_code] = list(exists_account_ids)
        new_account_set = set(account_ids) - set(exists_account_ids)
        for account_id in new_account_set:
            new_lineup_objs.append(
                SalesOpsLineup(
                    account_id=account_id,
                    is_active=True,
                    bucket_code=bucket_code,
                    next_reset_bucket_date=next_reset_bucket_date,
                )
            )

    return new_lineup_objs, update_bucket_lineups


def filter_out_user_assigned_in_bucket(account_ids):
    """
    Filter account IDs to get invalid ones based on the next reset bucket date.

    Invalid accounts are those where next_reset_bucket_date is not null and
    does not match the calculated next reset bucket date.

    Args:
    account_ids (list): List of account IDs to check.

    Returns:
    set: Set of invalid account IDs.
    """
    now = timezone.localtime(timezone.now())
    account_ids_set = set(account_ids)
    invalid_lineup_account_ids = set(
        SalesOpsLineup.objects.filter(
            account_id__in=account_ids_set,
            next_reset_bucket_date__gt=now
        ).values_list('account_id', flat=True)
    )

    return account_ids_set - invalid_lineup_account_ids


def get_next_reset_bucket_date():
    feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.SALES_OPS_REVAMP, is_active=True
    )
    parameters = feature_setting.parameters
    bucket_reset_day = parameters.get(
        'bucket_reset_day',
        SalesOpsSettingConst.DEFAULT_BUCKET_RESET_DAY
    )
    now = timezone.localtime(timezone.now())
    midnight_of_now = datetime.datetime.combine(now.date(), datetime.time.min)
    return (midnight_of_now + relativedelta(months=1)).replace(day=bucket_reset_day)
