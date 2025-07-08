import pytz
import logging
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
from functools import partial
from operator import attrgetter

from django.conf import settings
from bulk_update.helper import bulk_update
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from juloserver.julocore.constants import DbConnectionAlias
from juloserver.loyalty.constants import (
    BULK_SIZE_DEFAULT,
    MissionProgressStatusConst,
    MissionCategoryConst,
    MissionConfigTargetUserConst,
    MissionCriteriaValueConst,
    MissionRewardTypeConst,
    MissionCriteriaTypeConst,
    MissionCriteriaWhitelistStatusConst,
    TRANSACTION_METHOD_MAPPING_SEPULSA_PRODUCT_TYPE,
    MISSION_PROGRESS_TRACKING_FIELDS,
    MissionFilterCategoryConst,
    FeatureNameConst,
    MissionTargetTypeConst,
    MissionStatusMessageConst,
    APIVersionConst,
)
from juloserver.loyalty.models import (
    MissionConfig,
    MissionProgress,
    MissionCriteria,
    MissionConfigCriteria,
    MissionReward,
    MissionProgressHistory,
    MissionConfigTarget,
    MissionTarget,
    MissionTargetProgress,
)
from juloserver.account.models import AccountLimit
from juloserver.julo.models import (
    SepulsaProduct,
    Loan,
    FeatureSetting,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import (
    upload_file_to_oss
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.portal.core import functions
from juloserver.payment_point.services.sepulsa import get_payment_point_transaction_from_loan
from juloserver.loyalty.exceptions import (
    MissionConfigNotFoundException,
    MissionProgressNotFoundException,
    MissionProgressNotCompletedException,
    InvalidAPIVersionException,
)
from juloserver.loyalty.services.services import (
    update_loyalty_point_for_claim_mission_reward
)
from juloserver.moengage.services.use_cases import (
    send_loyalty_mission_progress_data_event_to_moengage
)
from juloserver.julocore.python2.utils import py2round


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class CalculateMissionPointRewards:
    def __init__(self, mission_config, mission_progress=None):
        # Mission config
        self.mission_config = mission_config
        self.mission_reward = mission_config.reward
        self.reward_category = self.mission_reward.category
        self.reward_type = self.mission_reward.type

        # Mission progress
        self.mission_progress = mission_progress

    def calculate(self):
        calculate_mission_reward_point_func = self.get_mission_reward_point_func()
        if calculate_mission_reward_point_func:
            point_amount = calculate_mission_reward_point_func()
            return point_amount
        return 0

    def get_mission_reward_point_func(self):
        func_mapping = {
            MissionCategoryConst.GENERAL: {
                MissionRewardTypeConst.FIXED: self.get_mission_reward_fixed_point
            },
            MissionCategoryConst.TRANSACTION: {
                MissionRewardTypeConst.FIXED: self.get_mission_reward_fixed_point,
                MissionRewardTypeConst.PERCENTAGE: self.get_mission_reward_percentage_point
            },
            MissionCategoryConst.REFERRAL: {
                MissionRewardTypeConst.FIXED: self.get_mission_reward_fixed_point
            },
        }
        return func_mapping.get(self.reward_category, {}).get(self.reward_type)

    def get_mission_reward_fixed_point(self):
        point_amount = self.mission_reward.value[MissionRewardTypeConst.FIXED]
        return point_amount

    def get_mission_reward_percentage_point(self):
        percentage_amount = self.mission_reward.value[MissionRewardTypeConst.PERCENTAGE]
        max_point = self.mission_reward.value[MissionRewardTypeConst.MAX_POINTS]

        if not self.mission_progress:
            return max_point

        loan_ids = self.mission_progress.reference_data['loan_ids']
        loans = Loan.objects.filter(id__in=loan_ids).aggregate(Sum('loan_amount'))
        total_loan_amount = loans["loan_amount__sum"] or 0
        point_from_loans = py2round(percentage_amount * total_loan_amount / 100)
        point_amount = min(max_point, point_from_loans)
        return point_amount


def get_customer_loyalty_mission_list(customer, category, api_version):
    mission_list = construct_mission_list_response(customer, category, api_version)
    mission_list.sort(key=order_customer_mission)
    return mission_list


def get_customer_loyalty_mission_detail(customer, mission_config_id, api_version):
    mission_config = (
        MissionConfig.objects
        .filter(pk=mission_config_id, api_version__lte=api_version)
        .last()
    )

    if not mission_config:
        raise MissionConfigNotFoundException()

    return construct_mission_detail_response(customer, mission_config, api_version)


def construct_mission_detail_response(customer, mission_config, api_version):
    mission_progress = (
        MissionProgress.objects
        .select_related("mission_config")
        .filter(mission_config=mission_config, customer_id=customer.id, is_latest=True)
        .last()
    )
    progress_func, no_progress_func = (
        get_construct_response_func(customer, api_version, is_detailed=True)
    )

    if mission_progress:
        mission_detail = progress_func(mission_progress=mission_progress)
    else:
        mission_detail = no_progress_func(mission_config=mission_config)

    return {
        **mission_detail,
        "description": mission_config.description,
        "tnc": mission_config.tnc
    }


def get_mission_progresses_and_configs(customer, category, api_version):
    # Check FS first. If turn off, return empty list
    parameters = get_mission_filter_categories_parameters()
    if not parameters:
        return [], []

    search_categories = [
        search_category['category']
        for search_category in parameters.get('search_categories', [])
        if search_category['is_active']
    ]
    if category not in search_categories:
        return [], []

    # Hidden expired missions after (expiry_days) days expired
    expiry_days = parameters.get(
        'search_days_expiry', MissionFilterCategoryConst.DEFAULT_MISSION_FILTER_EXPIRY_DAYS
    )

    mission_progresses = (
        get_eligible_mission_progresses(customer, category, expiry_days, api_version)
    )

    # Only get mission progresses that not resettable
    mission_progresses = list(filter(
        lambda mission_progress: is_mission_progress_not_resetable(customer, mission_progress),
        mission_progresses
    ))
    """
        Filter all active mission configs without mission progresses and
        construct its status is 'started' in function 'construct_mission_list_response'
        If category is not 'all_missions', no need to return mission configs without progress
    """
    if category == MissionFilterCategoryConst.ALL_MISSIONS:
        # Exclude deleted mission
        new_mission_configs = (
            MissionConfig.objects.get_visible_mission_config_queryset()
            .filter(api_version__lte=api_version)
            .exclude(
                pk__in=list(map(attrgetter("mission_config_id"), mission_progresses))
            )
        )
        new_valid_mission_config = list(
            filter(
                lambda mission: GeneralMissionCriteriaChecking(mission, customer).check(),
                new_mission_configs
            )
        )
        return mission_progresses, new_valid_mission_config

    return mission_progresses, []


def is_mission_progress_not_resetable(customer, mission_progress):
    mission_config = mission_progress.mission_config
    reset_checking = ResetMissionProgressChecking(
        mission_config, customer, latest_mission_progress=mission_progress
    )

    return not reset_checking.check_latest_mission_progress_resetable()


def get_construct_response_func(customer, api_version, is_detailed=False):
    if api_version == APIVersionConst.V1:
        construct_data_func = partial(construct_mission_with_progress_data, customer)
        construct_no_data_func = construct_mission_without_progress_data
    elif api_version == APIVersionConst.V2:
        construct_data_func = partial(
            construct_mission_with_progress_data_v2, customer, is_detailed=is_detailed
        )
        construct_no_data_func = partial(
            construct_mission_without_progress_data_v2, is_detailed=is_detailed
        )
    else:
        raise InvalidAPIVersionException()

    return construct_data_func, construct_no_data_func


def construct_mission_list_response(customer, category, api_version):
    mission_progresses, mission_configs = (
        get_mission_progresses_and_configs(customer, category, api_version)
    )
    progress_func, no_progress_func = (
        get_construct_response_func(customer, api_version, is_detailed=False)
    )

    missions_with_progress = list(map(progress_func, mission_progresses))
    missions_without_progress = list(map(no_progress_func, mission_configs))
    response_data = [*missions_with_progress, *missions_without_progress]
    return response_data


def construct_mission_with_progress_data(customer, mission_progress):
    mission_config = mission_progress.mission_config
    reset_checking = ResetMissionProgressChecking(
        mission_config, customer, latest_mission_progress=mission_progress
    )

    if reset_checking.check_latest_mission_progress_resetable():
        return construct_response_new_mission_progress(mission_config)
    else:
        return construct_response_latest_mission_progress(mission_config, mission_progress)


def construct_mission_without_progress_data(mission_config):
    return construct_response_new_mission_progress(mission_config)


def construct_response_new_mission_progress(mission):
    new_mission_progress_data = {
        "recurring_number": 0,
        "target_recurring": mission.target_recurring,
        "status": MissionProgressStatusConst.STARTED,
        "mission_progress_id": None
    }

    return {
        **get_mission_progress_general_info(mission),
        **get_mission_redirect_info(mission),
        **new_mission_progress_data
    }


def construct_response_latest_mission_progress(mission, latest_mission_progress):
    if latest_mission_progress.status == MissionProgressStatusConst.IN_PROGRESS:
        mission_target = mission.targets.last()
        target_progress = get_last_target_progress(mission_target, latest_mission_progress)
        current = target_progress and target_progress.value or 0
    else:
        current = latest_mission_progress.recurring_number

    current_mission_progress_data = {
        "recurring_number": current,
        "target_recurring": mission.target_recurring,
        "status": latest_mission_progress.status,
        "mission_progress_id": latest_mission_progress.id,
        "completion_date": latest_mission_progress.completion_date,
    }
    return {
        **get_mission_progress_general_info(mission),
        **get_mission_redirect_info(mission),
        **current_mission_progress_data
    }


def get_mission_progress_general_info(mission):
    reward_points = CalculateMissionPointRewards(mission).calculate()

    return {
        "mission_id": mission.id,
        "title": mission.title,
        "icon": mission.icon,
        "reward_points": reward_points,
        "display_order": mission.display_order,
        "expiry_date": mission.expiry_date,
        "completion_date": None,
    }


def get_mission_redirect_info(mission):
    return {
        'category': mission.category,
        'transaction_method_id': get_mission_transaction_method(mission)
    }


def get_mission_transaction_method(mission):
    transaction_method_criteria = mission.criteria.filter(
        category=MissionCategoryConst.TRANSACTION,
        type=MissionCriteriaTypeConst.TRANSACTION_METHOD
    )

    if transaction_method_criteria.count() == 1:
        criteria = transaction_method_criteria[0]
        # there are no or many transaction methods, return None
        Const = MissionCriteriaValueConst
        transaction_methods = criteria.value.get(Const.TRANSACTION_METHODS, [])
        return (transaction_methods[0][Const.TRANSACTION_METHOD_ID]
                if len(transaction_methods) == 1 else None)
    return None


def get_mission_progress_target_message(mission, mission_progress=None):
    if not mission_progress:
        return {"message": MissionStatusMessageConst.STARTED_MSG}

    progress_status = mission_progress.status
    if progress_status != MissionProgressStatusConst.IN_PROGRESS:
        return {"message": MissionStatusMessageConst.MESSAGE_MAPPING[progress_status]}

    num_of_targets = mission.targets.count()
    if num_of_targets > 1:
        return {"message": MissionStatusMessageConst.IN_PROGRESS_MSG["default"]}
    else:
        mission_target = mission.targets.last()
        return get_current_progress_over_target(mission_target, mission_progress)


def construct_mission_with_progress_data_v2(customer, mission_progress, is_detailed=False):
    mission_config = mission_progress.mission_config
    reset_checking = ResetMissionProgressChecking(
        mission_config, customer, latest_mission_progress=mission_progress
    )

    if reset_checking.check_latest_mission_progress_resetable():
        return construct_response_new_mission_progress_v2(
            mission_config, is_detailed
        )
    else:
        return construct_response_latest_mission_progress_v2(
            mission_config, mission_progress, is_detailed
        )


def construct_mission_without_progress_data_v2(mission_config, is_detailed=False):
    return construct_response_new_mission_progress_v2(mission_config, is_detailed)


def construct_response_new_mission_progress_v2(mission, is_detailed):
    new_mission_progress_data = {
        "status": MissionProgressStatusConst.STARTED,
        "mission_progress_id": None
    }

    if is_detailed:
        detailed_progress = get_detailed_progress_of_mission(mission)
        new_mission_progress_data.update(detailed_progress)
    else:
        overall_progress = get_overall_progress_of_mission(mission)
        message = get_mission_progress_target_message(mission)
        new_mission_progress_data.update({**overall_progress, **message})

    return {
        **get_mission_progress_general_info(mission),
        **get_mission_redirect_info(mission),
        **new_mission_progress_data
    }


def construct_response_latest_mission_progress_v2(mission, latest_mission_progress, is_detailed):
    """
    Construct response for latest mission progress, separate from
    single or multiple targets on the mission
    """
    current_mission_progress_data = {
        "status": latest_mission_progress.status,
        "mission_progress_id": latest_mission_progress.id,
        "completion_date": latest_mission_progress.completion_date,
    }

    if is_detailed:
        detailed_progress = get_detailed_progress_of_mission(mission, latest_mission_progress)
        current_mission_progress_data.update(detailed_progress)
    else:
        overall_progress = get_overall_progress_of_mission(mission, latest_mission_progress)
        message = get_mission_progress_target_message(mission, latest_mission_progress)
        current_mission_progress_data.update({**overall_progress, **message})

    return {
        **get_mission_progress_general_info(mission),
        **get_mission_redirect_info(mission),
        **current_mission_progress_data
    }


def get_detailed_progress_of_mission(mission, mission_progress=None):
    return {
        "detailed_progress": [
            get_current_progress_over_target(mission_target, mission_progress)
            for mission_target in mission.targets.all()
        ]
    }


def get_overall_progress_of_mission(mission, mission_progress=None):
    if not mission_progress:
        return {"overall_progress": 0}

    mission_targets = mission.targets.all()
    if not mission_targets:
        return {
            "overall_progress": py2round(
                mission_progress.recurring_number / mission.target_recurring * 100, 0
            )
        }

    progresses = []
    for mission_target in mission.targets.all():
        detailed_progress = get_current_progress_over_target(mission_target, mission_progress)
        progress = min(detailed_progress['current'] / detailed_progress['target'] * 100, 100)
        progresses.append(progress)

    return {"overall_progress": py2round(sum(progresses) / len(progresses), 0)}


def get_current_progress_over_target(mission_target, mission_progress=None):
    target_progress = get_last_target_progress(mission_target, mission_progress)

    target_type = mission_target.type
    current_value = target_progress and target_progress.value or 0
    target_value = mission_target.value
    remaining_value = max(target_value - current_value, 0)

    progress_status = (
        mission_progress and mission_progress.status or MissionProgressStatusConst.STARTED
    )
    message = MissionStatusMessageConst.MESSAGE_MAPPING[progress_status]
    if progress_status == MissionProgressStatusConst.IN_PROGRESS:
        message = message[target_type]

    return {
        "target_type": target_type,
        "current": current_value,
        "remaining": remaining_value,
        "target": target_value,
        "message": message
    }


def get_last_target_progress(mission_target, mission_progress):
    if not mission_progress:
        return None

    return (
        MissionTargetProgress.objects
        .filter(mission_target=mission_target, mission_progress=mission_progress)
        .last()
    )


def get_mission_filter_categories():
    parameters = get_mission_filter_categories_parameters()
    if not parameters:
        return []

    search_categories = parameters.get('search_categories', [])

    return [
        search_category['category']
        for search_category in search_categories
        if search_category['is_active']
    ]


def get_mission_filter_categories_parameters():
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.MISSION_FILTER_CATEGORY, is_active=True
    )
    if not fs:
        return None
    return fs.parameters or {}


def get_eligible_mission_progresses(customer, category, expiry_days, api_version):
    """Get all eligible mission progresses of a customer
        - Filter by category and API version
        - Not yet expired or deleted
    """
    now = timezone.localtime(timezone.now())
    hidden_datetime = now - timedelta(days=expiry_days)

    # Get mission filter category mapping
    mission_filter_category_mapping = (
        MissionFilterCategoryConst.FILTER_CATEGORY_MAPPING_MISSION_PROGRESS_STATUS
    )

    # Exclude deleted missions OR expired missions if expiry date less than hidden_datetime
    mission_progress_list_by_category = (
        MissionProgress.objects
        .select_related("mission_config")
        .prefetch_related("mission_config__targets")
        .filter(
            customer_id=customer.id,
            status__in=mission_filter_category_mapping[category],
            mission_config__is_deleted=False,
            mission_config__api_version__lte=api_version,
            is_latest=True
        )
        .exclude(
            status=MissionProgressStatusConst.EXPIRED,
            mission_config__expiry_date__lt=hidden_datetime
        )
    )

    return mission_progress_list_by_category


def order_customer_mission(mission_progress):
    """
        Prioritize mission based on
            - status: 'completed' -> 'in_progress' -> 'started' -> claimed -> 'expired'
            - expiry date: missions having same status
    """
    status_priority_order_mapping = MissionProgressStatusConst.PRIORITY_ORDER
    status_order = status_priority_order_mapping[mission_progress["status"]]
    display_order = mission_progress["display_order"]

    # If the status is completed, sort it by the newest completion date
    if mission_progress["status"] == MissionProgressStatusConst.COMPLETED:
        completion_date = mission_progress["completion_date"]
        return status_order, completion_date, display_order

    expiry_date = mission_progress["expiry_date"]
    """
    Handle case when expiry_date is None as infinity
        expiry_date = datetime.datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=<UTC>)
    """
    if not expiry_date:
        expiry_date = datetime.max.replace(tzinfo=pytz.UTC)
    return status_order, expiry_date, display_order


def claim_mission_rewards(mission_progress_id, customer):
    mission_progress = MissionProgress.objects.select_related("mission_config").filter(
        pk=mission_progress_id,
        customer_id=customer.id,
        status=MissionProgressStatusConst.COMPLETED
    ).last()
    if not mission_progress:
        raise MissionProgressNotFoundException()

    point_reward, _ = LoyaltyMissionUtilization\
        .process_claim_mission_rewards(mission_progress)

    send_loyalty_mission_progress_data_event_to_moengage.delay(
        customer.id,
        [{
            'mission_progress_id': mission_progress.id,
            'status': MissionProgressStatusConst.CLAIMED,
        }]
    )

    return point_reward


def get_choice_criteria_by_category(category):
    now = timezone.localtime(timezone.now())
    categories = [MissionCategoryConst.GENERAL]
    if category == MissionCategoryConst.TRANSACTION:
        categories.append(MissionCategoryConst.TRANSACTION)
    elif category == MissionCategoryConst.REFERRAL:
        categories.append(MissionCategoryConst.REFERRAL)
    qs = MissionCriteria.objects.filter(category__in=categories)

    result = {}
    for item in qs:
        if (
            item.type == MissionCriteriaTypeConst.WHITELIST_CUSTOMERS and
            (
                item.value['status'] == MissionCriteriaWhitelistStatusConst.PROCESS or
                item.cdate + relativedelta(months=item.value['duration']) < now
            )
        ):
            continue
        result[item.id] = '{} - {}'.format(item.id, item.name)
    return result


def get_choice_reward_by_category(category):
    categories = [MissionCategoryConst.GENERAL]
    if category == MissionCategoryConst.TRANSACTION:
        categories.append(MissionCategoryConst.TRANSACTION)
    elif category == MissionCategoryConst.REFERRAL:
        categories.append(MissionCategoryConst.REFERRAL)
    qs = MissionReward.objects.filter(category__in=categories)
    result = {}
    for item in qs:
        result[item.id] = '{} - {}'.format(item.id, item.name)
    return result


def get_choice_target_by_category(category):
    categories = [MissionCategoryConst.GENERAL]
    if category == MissionCategoryConst.TRANSACTION:
        categories.append(MissionCategoryConst.TRANSACTION)
    elif category == MissionCategoryConst.REFERRAL:
        categories.append(MissionCategoryConst.REFERRAL)
    qs = MissionTarget.objects.filter(category__in=categories)
    result = {}
    for item in qs:
        result[item.id] = '{} - {}'.format(item.id, item.name)
    return result


def get_choice_sepulsa_categories_by_transaction_method(transaction_method):
    sepulsa_product_type = TRANSACTION_METHOD_MAPPING_SEPULSA_PRODUCT_TYPE.get(transaction_method)
    result = {}
    qs = SepulsaProduct.objects.filter(type=sepulsa_product_type).distinct('category')
    for item in qs:
        result[item.category] = item.category
    return result


def add_criteria_mappings(mission_config, criteria_ids):
    new_mappings = [
        MissionConfigCriteria(
            config=mission_config,
            criteria_id=criteria_id,
        ) for criteria_id in criteria_ids]
    if new_mappings:
        MissionConfigCriteria.objects.bulk_create(new_mappings)


def add_target_mappings(mission_config, target_ids):
    new_mappings = [
        MissionConfigTarget(
            config=mission_config,
            target_id=target_id,
        ) for target_id in target_ids]
    if new_mappings:
        MissionConfigTarget.objects.bulk_create(new_mappings)


class BaseMissionCriteriaChecking:
    def __init__(self, mission_config, category):
        self.mission_config = mission_config
        self.category = category

    def get_criteria_qs(self):
        return self.mission_config.criteria.filter(category=self.category)

    def check(self):
        criteria_qs = self.get_criteria_qs()
        for criterion in criteria_qs:
            is_passed = getattr(self, f'check_{criterion.type}')(criterion)
            if not is_passed:
                return False

        return True


class ResetMissionProgressChecking:
    """
    Check to use latest customer mission progress or need to create a new one
        - Check not existing of latest mission progress
        - Check latest mission progress is resetable
            * Status is Completed/Claimed
            * Mission progress repeat number is less than mission config max repeat
            * Mission progress completed date is passed mission config repetition delay
    """
    def __init__(self, mission_config, customer, *args, **kwargs):
        self.customer = customer
        self.mission_config = mission_config
        self._latest_mission_progress = kwargs.get('latest_mission_progress')

    @property
    def latest_mission_progress(self):
        if not self._latest_mission_progress:
            self._latest_mission_progress = self.get_customer_latest_mission_progress()
        return self._latest_mission_progress

    def get_customer_latest_mission_progress(self):
        return (
            MissionProgress.objects.filter(
                customer_id=self.customer.id, mission_config=self.mission_config, is_latest=True
            ).last()
        )

    def check(self):
        if self.check_not_existing_mission_progress():
            return True
        if self.check_latest_mission_progress_resetable():
            return True
        return False

    def check_not_existing_mission_progress(self):
        return not self.latest_mission_progress

    def check_latest_mission_progress_resetable(self):
        condition_checks = [
            self.check_mission_config_is_active,
            self.check_latest_mission_progress_status,
            self.check_latest_mission_progress_repeat_number,
            self.check_latest_mission_progress_repeat_delay
        ]
        for condition_check in condition_checks:
            if not condition_check():
                return False
        return True

    def check_mission_config_is_active(self):
        # Only allow active missions can repeat
        return self.mission_config.is_active

    def check_latest_mission_progress_status(self):
        return self.latest_mission_progress.status in \
            MissionProgressStatusConst.ALLOWED_RESET_STATUSES

    def check_latest_mission_progress_repeat_number(self):
        if not self.mission_config.max_repeat:
            return True
        return self.latest_mission_progress.repeat_number < self.mission_config.max_repeat

    def check_latest_mission_progress_repeat_delay(self):
        now = timezone.localtime(timezone.now())
        last_completion_date = self.latest_mission_progress.completion_date
        delay_days = self.mission_config.repetition_delay_days
        next_valid_timestamp = last_completion_date + timedelta(days=delay_days)

        return now >= next_valid_timestamp


class GeneralMissionCriteriaChecking(BaseMissionCriteriaChecking):
    def __init__(self, mission_config, customer, excluded_loan=None):
        self.customer = customer
        self.account = customer.account
        self.excluded_loan = excluded_loan
        super().__init__(mission_config, MissionCategoryConst.GENERAL)

    def get_customer_target_user(self):
        loans = Loan.objects.filter(
            customer_id=self.customer.id, loan_status__gte=LoanStatusCodes.CURRENT
        )
        if self.excluded_loan:
            loans = loans.exclude(pk=self.excluded_loan.id)

        if loans.exists():
            return MissionConfigTargetUserConst.REPEAT
        else:
            return MissionConfigTargetUserConst.FTC

    def get_customer_utilization_rate(self):
        account_limit = AccountLimit.objects.filter(account=self.account).last()
        used_limit, set_limit = account_limit.used_limit, account_limit.set_limit
        return used_limit / set_limit * 100

    def check_target_user(self, criteria):
        target_user = self.get_customer_target_user()
        criteria_value = criteria.value
        return target_user == criteria_value[MissionCriteriaValueConst.TARGET_USER]

    def check_utilization_rate(self, criteria):
        utilization_rate = self.get_customer_utilization_rate()
        criteria_value = criteria.value
        return utilization_rate >= criteria_value[MissionCriteriaValueConst.UTILIZATION_RATE]

    def check_whitelist_customers_file(self, criteria):
        redis_client = get_redis_client()
        redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(criteria.id)

        if redis_client.exists(redis_key):
            return redis_client.sismember(redis_key, str(self.customer.id))

        captured_data = {
            'error': 'whitelist criteria key does not exist',
            'customer_id': self.customer.id,
            'mission_id': self.mission_config.id,
            'whitelist_criteria_id': criteria.id
        }

        sentry_client.captureMessage(captured_data)
        logger.error(captured_data)

        # Process to re-upload whitelist data into Redis
        from juloserver.loyalty.tasks import trigger_upload_whitelist_mission_criteria
        trigger_upload_whitelist_mission_criteria.delay(criteria.id)
        return False


class TransactionMissionCriteriaChecking(BaseMissionCriteriaChecking):
    def __init__(self, mission_config, loan):
        self.loan = loan
        self.customer = loan.customer
        super().__init__(mission_config, MissionCategoryConst.TRANSACTION)

    def check_transaction_method(self, criteria):
        transaction_methods = criteria.value.get(MissionCriteriaValueConst.TRANSACTION_METHODS)
        if not transaction_methods:
            return True

        TRANSACTION_METHOD_ID = MissionCriteriaValueConst.TRANSACTION_METHOD_ID
        CATEGORIES = MissionCriteriaValueConst.CATEGORIES
        categories = []
        for transaction_method in transaction_methods:
            if self.loan.transaction_method_id == transaction_method[TRANSACTION_METHOD_ID]:
                categories = transaction_method.get(CATEGORIES, [])
                break
        else:
            return False

        if categories:
            transaction = get_payment_point_transaction_from_loan(self.loan)
            if not (
                transaction
                and transaction.product
                and transaction.product.category in categories
            ):
                return False

        return True

    def check_tenor(self, criteria):
        tenor = criteria.value[MissionCriteriaValueConst.TENOR]
        return tenor <= self.loan.loan_duration

    def check_minimum_loan_amount(self, criteria):
        minimum_loan_amount = criteria.value[MissionCriteriaValueConst.MINIMUM_LOAN_AMOUNT]
        return minimum_loan_amount <= self.loan.loan_amount


class TransactionMissionProgressService:
    def __init__(self, loan):
        self.loan = loan
        self.customer = loan.customer

    @property
    def mission_progress_update_fields(self):
        return ['recurring_number', 'status', 'reference_data']

    def get_and_blocking_exists_mission_progresses(self, m_config_ids):
        """
        return dict(
            mission_config_id_1: mission_progress object,
            ....
        )
        """
        qs = (
            MissionProgress.objects
            .select_for_update()
            .filter(
                customer_id=self.customer.id,
                is_latest=True,
                mission_config_id__in=m_config_ids,
            )
            .exclude(status__in=[MissionProgressStatusConst.EXPIRED, MissionProgressStatusConst.DELETED])
        )

        data = {}
        for m_progress in qs:
            m_config_id = m_progress.mission_config_id
            data[m_config_id] = m_progress

        return data

    def process_after_loan_disbursement(self):
        """
        *** MAIN METHOD ***
        This is a main function for processing create/update mission progress:
            - create_new_mission_progresses:
                + create new mission_progress
                + create repeat mission_progress
            - update_mission_progresses
                + update recurrent_number -> status and completion_date
                + update reference_data
        """
        with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
            # Get mission config and lock mission progress for atomic
            m_config_qs = MissionConfig.objects.get_valid_mission_config_queryset().filter(
                category=MissionCategoryConst.TRANSACTION,
            )
            m_config_ids = list(m_config_qs.values_list('id', flat=True))
            m_progresses_dict = self.get_and_blocking_exists_mission_progresses(m_config_ids=m_config_ids)
            new_m_configs, repeat_m_configs, in_progress_m_configs = \
                self.classify_mission_configs(m_config_qs, m_progresses_dict)

            new_m_configs = self.create_new_mission_progresses(new_m_configs)
            repeat_m_configs = self.create_repeat_mission_progresses(repeat_m_configs)
            # continue update new mission progress (recurring number, status, ....)
            in_progress_m_configs.extend([*new_m_configs, *repeat_m_configs])

            # update mission progress
            updated_history_data = self.update_mission_progresses_after_loan(in_progress_m_configs)

            # claim mission progress which is complete
            claimed_history_data = self.process_mission_progress_to_claim(repeat_m_configs)

        # prepare data and send
        moengage_data = self.get_mission_progress_data_to_send_moengage(
            [*updated_history_data, *claimed_history_data]
        )
        if moengage_data:
            send_loyalty_mission_progress_data_event_to_moengage.delay(
                self.customer.id, moengage_data
            )

    def classify_mission_configs(self, m_config_qs, m_progresses_dict):
        new_m_configs = []
        repeat_m_configs = []
        in_progress_m_configs = []

        for m_config in m_config_qs:
            m_progress = m_progresses_dict.get(m_config.id)
            pair = {
                'm_config': m_config,
                'm_progress': m_progress,
                'next_repeat_number': None
            }

            if not m_progress:
                # New users without progress cannot do inactive mission
                if m_config.is_active and self.check_all_criteria(m_config):
                    pair['next_repeat_number'] = 1
                    new_m_configs.append(pair)
            elif m_progress.status in MissionProgressStatusConst.ALLOWED_RESET_STATUSES:
                if self.check_criteria_for_repeat_mission_config(m_config, m_progress):
                    pair['next_repeat_number'] = m_progress.repeat_number + 1
                    repeat_m_configs.append(pair)
            elif m_progress.status == MissionProgressStatusConst.IN_PROGRESS:
                if self.check_transaction_criteria(m_config):
                    in_progress_m_configs.append(pair)

        return new_m_configs, repeat_m_configs, in_progress_m_configs

    def create_new_mission_progresses(self, new_m_configs):
        for d in new_m_configs:
            repeat_number = d['next_repeat_number']
            m_config = d['m_config']

            new_m_progress = MissionProgress(
                status=MissionProgressStatusConst.STARTED,
                recurring_number=0,
                repeat_number=repeat_number,
                customer_id=self.customer.id,
                mission_config=m_config,
                is_latest=True,
                reference_data={'loan_ids': []},
            )
            new_m_progress.save()

            d['m_progress'] = new_m_progress

        return new_m_configs

    def create_repeat_mission_progresses(self, repeat_m_configs):
        # update old progresses to done, is_latest = False
        now = timezone.localtime(timezone.now())
        m_progress_olds = []
        for d in repeat_m_configs:
            d['old_m_progress'] = d['m_progress']
            d['m_progress'] = None
            d['old_m_progress'].is_latest = False
            d['old_m_progress'].udate = now
            m_progress_olds.append(d['old_m_progress'])
        bulk_update(m_progress_olds, using='utilization_db', update_fields=['is_latest', 'udate'])

        return self.create_new_mission_progresses(repeat_m_configs)

    def update_mission_progresses_after_loan(self, in_progress_m_configs):
        histories = []

        for d in in_progress_m_configs:
            histories_returned = self.update_mission_progress_after_loan(d['m_progress'])
            histories.extend(histories_returned)

        MissionProgressHistory.objects.bulk_create(histories, BULK_SIZE_DEFAULT)
        return histories

    def update_mission_progress_after_loan(self, m_progress):
        histories_data = LoyaltyMissionUtilization\
            .build_mission_progress_history_structure(m_progress)

        # update recurring_number and completed status if possible
        if m_progress.recurring_number == 0:
            m_progress.status = MissionProgressStatusConst.IN_PROGRESS

        m_progress.recurring_number += 1
        if m_progress.recurring_number >= m_progress.mission_config.target_recurring:
            m_progress.status = MissionProgressStatusConst.COMPLETED
            m_progress.completion_date = timezone.localtime(timezone.now())

        # update reference_data
        reference_data = m_progress.reference_data
        reference_data.setdefault('loan_ids', [])
        reference_data['loan_ids'].append(self.loan.id)

        m_progress.save()

        # update mission_target_progress
        self.update_mission_target_recurring(m_progress)

        return LoyaltyMissionUtilization\
                .prepare_mission_progress_histories(m_progress, histories_data)

    def update_mission_target_recurring(self, m_progress):
        m_config_id = m_progress.mission_config_id
        m_target = MissionTarget.objects.filter(
            type=MissionTargetTypeConst.RECURRING,
            mission_configs=m_config_id
        ).last()
        if m_target:
            MissionTargetProgress.objects.update_or_create(
                mission_progress_id=m_progress.id,
                type=MissionTargetTypeConst.RECURRING,
                mission_target_id=m_target.id,
                defaults=dict(
                    value=m_progress.recurring_number
                )
            )

    def process_mission_progress_to_claim(self, repeat_m_configs):
        histories = []
        for d in repeat_m_configs:
            m_progress = d['old_m_progress']
            if m_progress.status == MissionProgressStatusConst.COMPLETED:
                _, history_data = LoyaltyMissionUtilization.process_claim_mission_rewards(m_progress)
                histories.extend([*history_data])

        return histories

    def check_transaction_criteria(self, mission_config):
        transaction_checking = TransactionMissionCriteriaChecking(mission_config, self.loan)
        return transaction_checking.check()

    def check_general_criteria(self, mission_config):
        general_checking = GeneralMissionCriteriaChecking(mission_config, self.customer, self.loan)
        return general_checking.check()

    def check_all_criteria(self, mission_config):
        return (
            self.check_general_criteria(mission_config)
            and self.check_transaction_criteria(mission_config)
        )

    def check_criteria_for_repeat_mission_config(self, m_config, m_progress):
        if self.check_all_criteria(m_config):
            reset_checking = ResetMissionProgressChecking(
                mission_config=m_config,
                customer=self.customer,
                latest_mission_progress=m_progress
            )
            if reset_checking.check_latest_mission_progress_resetable():
                return True
        return False

    def get_mission_progress_data_to_send_moengage(self, histories):
        m_progresses_dict = {}
        for history in histories:
            if history.field == 'status':
                m_progresses_dict[history.mission_progress_id] = history.mission_progress

        returned_data = []
        for m_progress_id, m_progress in m_progresses_dict.items():
            returned_data.append({
                'mission_progress_id': m_progress_id,
                'status': m_progress.status
            })

        return returned_data


class LoyaltyMissionUtilization:
    @staticmethod
    def prepare_mission_progress_histories(m_progress, histories_data):
        for field in MISSION_PROGRESS_TRACKING_FIELDS:
            new_value = getattr(m_progress, field)
            if new_value is not None:
                new_value = str(new_value)
            histories_data[field]['new_value'] = new_value

        histories = []
        for hist_data in histories_data.values():
            if hist_data['old_value'] != hist_data['new_value']:
                histories.append(MissionProgressHistory(**hist_data))

        return histories

    @staticmethod
    def build_mission_progress_history_structure(m_progress):
        histories_struct = {}
        for field in MISSION_PROGRESS_TRACKING_FIELDS:
            old_value = getattr(m_progress, field)
            if old_value is not None:
                old_value = str(old_value)

            histories_struct[field] = {
                'mission_progress': m_progress,
                'field': field,
                'old_value': old_value,
                'new_value': old_value,
                'note': f'Update {field} field',
            }

        return histories_struct

    @staticmethod
    def process_claim_mission_rewards(m_progress):
        if m_progress.status != MissionProgressStatusConst.COMPLETED:
            raise MissionProgressNotCompletedException()

        mission_config = m_progress.mission_config
        with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
            point_reward = CalculateMissionPointRewards(mission_config, m_progress).calculate()
            point_earning, point_history = update_loyalty_point_for_claim_mission_reward(
                m_progress, point_reward
            )
            data_changes = [
                {
                    'field': 'status',
                    'new_value': MissionProgressStatusConst.CLAIMED
                },
                {
                    'field': 'point_earning',
                    'new_value': point_earning
                },
            ]
            history_data = LoyaltyMissionUtilization.update_mission_progress(
                m_progress, data_changes
            )
            return point_reward, history_data

    @staticmethod
    def update_mission_progress(m_progress, data_changes):
        history_data = LoyaltyMissionUtilization\
            .build_mission_progress_history_structure(m_progress)

        for data_change in data_changes:
            field = data_change['field']
            new_value = data_change['new_value']
            setattr(m_progress, field, new_value)

        m_progress.save()

        history_data = LoyaltyMissionUtilization\
            .prepare_mission_progress_histories(m_progress, history_data)
        MissionProgressHistory.objects.bulk_create(history_data)

        return history_data

def populate_whitelist_mission_criteria_on_redis(customer_ids, criteria):
    expired_at = timezone.localtime(timezone.now()) + relativedelta(
        months=criteria.value['duration']
    )

    redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(criteria.id)
    redis_client = get_redis_client()
    result = redis_client.sadd(redis_key, customer_ids)
    redis_client.expireat(redis_key, expired_at)
    criteria.value['status'] = MissionCriteriaWhitelistStatusConst.SUCCESS
    criteria.save()

    logger.info({
        'action': "populate_whitelist_mission_criteria_on_redis",
        'criteria_id': criteria.id,
        'customer_affected_count': result
    })


def delete_whitelist_mission_criteria_on_redis(criteria):
    redis_key = MissionCriteriaValueConst.WHITELIST_CUSTOMERS_REDIS_KEY.format(criteria.id)
    redis_client = get_redis_client()
    redis_client.delete_key(redis_key)

    logger.info({
        'action': "delete_whitelist_mission_criteria_on_redis",
        'criteria_id': criteria.id,
    })


def upload_whitelist_customers_csv_to_oss(obj, request_file):
    remote_path = 'loyalty_customers_whitelist_{}'.format(obj.id)
    obj.value['upload_url'] = remote_path
    obj.value['status'] = MissionCriteriaWhitelistStatusConst.PROCESS
    obj.save()
    file = functions.upload_handle_media(request_file, "loyalty_customers_whitelist")
    if file:
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET,
            file['file_name'],
            remote_path
        )
