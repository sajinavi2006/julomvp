from django.db import transaction
from django.utils import timezone

from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loyalty.constants import (
    DailyCheckinConst,
    AdminSettingDailyRewardErrorMsg,
    PointHistoryChangeReasonConst, MissionEntryPointTooltip,
)
from juloserver.loyalty.exceptions import (
    DailyCheckinHasBeenClaimedException,
    DailyCheckinNotFoundException
)
from juloserver.loyalty.models import DailyCheckin, DailyCheckinProgress
from juloserver.loyalty.services.services import update_loyalty_point_for_daily_checkin


def get_latest_daily_checkin():
    daily_checkin = DailyCheckin.objects.filter(is_latest=True).last()
    if not daily_checkin:
        raise DailyCheckinNotFoundException
    return daily_checkin


def create_daily_checkin_progress(customer):
    return DailyCheckinProgress.objects.create(
        daily_checkin=get_latest_daily_checkin(), customer_id=customer.id, is_latest=True
    )


def get_or_create_daily_checkin_progress(customer):
    daily_checkin_progress = get_daily_checkin_progress(customer)
    if daily_checkin_progress is None:
        daily_checkin_progress = create_daily_checkin_progress(customer)

    if daily_checkin_progress.latest_update is not None:
        today = timezone.localtime(timezone.now()).date()
        interval_day = (today - daily_checkin_progress.latest_update).days
        # Reset the daily check-in user complete weekly check-n user fails to complete weekly
        # check-in / miss 1 day
        is_checkin_cycle_completed = (interval_day == 1 and daily_checkin_progress.is_completed)
        is_missing_checkin_days = (interval_day > 1)
        if is_checkin_cycle_completed or is_missing_checkin_days:
            daily_checkin_progress = reset_daily_check_in_progress(daily_checkin_progress, customer)

    data = construct_get_daily_checkin_response(daily_checkin_progress)

    return data


def get_daily_checkin_progress(customer):
    return DailyCheckinProgress.objects.filter(customer_id=customer.id, is_latest=True).last()


def reset_daily_check_in_progress(daily_checkin_progress, customer):
    # reset daily_check in
    with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
        daily_checkin_progress.is_latest = False
        daily_checkin_progress.save()
        daily_checkin_progress = create_daily_checkin_progress(customer)

    return daily_checkin_progress


def construct_get_daily_checkin_response(daily_checkin_progress):
    today = timezone.localtime(timezone.now()).date()
    is_claimable_today = daily_checkin_progress.latest_update != today
    daily_checkin = daily_checkin_progress.daily_checkin
    data = {
        "is_claimable_today": is_claimable_today,
        "daily_check_in": [],
        "reward": {
            "value": daily_checkin.reward,
            "status": DailyCheckinConst.STATUS_LOCKED
        }
    }
    daily_reward = daily_checkin.daily_reward
    interval_day = 1 if daily_checkin_progress.latest_update is None else \
        (today - daily_checkin_progress.latest_update).days
    days_count = daily_checkin_progress.days_count
    # construct response
    for day_number in range(daily_checkin.max_days_reach_bonus):
        temp = {
            "value": daily_reward.get(str(day_number+1), daily_reward.get("default"))
        }

        if days_count == 0 and interval_day > 0:
            temp["status"] = DailyCheckinConst.STATUS_TODAY
            days_count -= 1
        elif days_count > 0:
            temp['status'] = DailyCheckinConst.STATUS_CLAIMED
            days_count -= 1
        else:
            temp['status'] = DailyCheckinConst.STATUS_AVAILABLE
        data['daily_check_in'].append(temp)

    # return daily check in response
    if daily_checkin_progress.days_count == daily_checkin.max_days_reach_bonus and interval_day > 0:
        data['reward']['status'] = DailyCheckinConst.STATUS_TODAY
    elif daily_checkin_progress.days_count > daily_checkin.max_days_reach_bonus:
        data['reward']['status'] = DailyCheckinConst.STATUS_CLAIMED
    elif interval_day == 0:
        data['reward']['status'] = DailyCheckinConst.STATUS_AVAILABLE

    return data


def claim_daily_checkin_point(customer):
    # check whether the claim is locked or no
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        daily_checkin_progress = DailyCheckinProgress.objects.select_for_update().filter(
            customer_id=customer.id, is_latest=True
        ).last()
        today = timezone.localtime(timezone.now()).date()

        if daily_checkin_progress.latest_update is not None:
            interval_day = (today - daily_checkin_progress.latest_update).days
            if interval_day < 1:
                raise DailyCheckinHasBeenClaimedException

        # update mission progress
        today_reward = update_daily_checkin_progress(daily_checkin_progress)

    return today_reward


def update_daily_checkin_progress(daily_checkin_progress):
    today = timezone.localtime(timezone.now()).date()
    daily_checkin = daily_checkin_progress.daily_checkin
    daily_reward = daily_checkin.daily_reward

    with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
        day_count = daily_checkin_progress.days_count + 1
        is_last_day = day_count > daily_checkin.max_days_reach_bonus
        if is_last_day:
            today_reward = daily_checkin.reward
            reason = PointHistoryChangeReasonConst.BONUS_CHECKING
            daily_checkin_progress.is_completed = True
        else:
            today_reward = daily_reward.get(str(day_count), daily_reward.get("default"))
            reason = PointHistoryChangeReasonConst.DAILY_CHECKING

        daily_checkin_progress.total_claimed += today_reward
        daily_checkin_progress.days_count = day_count
        daily_checkin_progress.latest_update = today
        daily_checkin_progress.save()

        update_loyalty_point_for_daily_checkin(
            daily_checkin_progress=daily_checkin_progress,
            today_reward=today_reward,
            reason=reason
        )

    return today_reward


def is_validate_input_data(cleaned_data):
    daily_reward = cleaned_data.get('daily_reward')
    if not daily_reward:
        return True, None

    if not isinstance(daily_reward, dict):
        return False, AdminSettingDailyRewardErrorMsg.INVALID_FORMAT

    max_days_reach_bonus = cleaned_data['max_days_reach_bonus']
    if "default" not in daily_reward:
        return False, AdminSettingDailyRewardErrorMsg.KEY_REQUIRED
    for key, val in daily_reward.items():
        if key != "default":
            if not isinstance(key, str) or not key.isdigit():
                return False, AdminSettingDailyRewardErrorMsg.INVALID_DATA_TYPE
            day = int(key)
            if day <= 0 or day > max_days_reach_bonus:
                return False, AdminSettingDailyRewardErrorMsg.INVALID_DATA_CONDITION

        if not isinstance(val, int) or val < 0:
            return False, AdminSettingDailyRewardErrorMsg.INVALID_VALUE_TYPE

    return True, None


def is_eligible_for_daily_checkin(customer_id):
    today = timezone.localtime(timezone.now()).date()
    last_checkin = DailyCheckinProgress.objects.filter(
        customer_id=customer_id
    ).last()
    if not last_checkin:
        return True

    latest_update = last_checkin.latest_update
    return latest_update != today


def get_loyalty_entry_point_information(customer_id):
    if is_eligible_for_daily_checkin(customer_id):
        return True, MissionEntryPointTooltip.DAILY_CHECKIN
    return False, None
