from datetime import date
from operator import attrgetter

from django.db import transaction
from django.utils import timezone

from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.julo.constants import RedisLockKeyName
from juloserver.account_payment.models import AccountPayment
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.loyalty.models import LoyaltyPoint, PointHistory, PointEarning
from juloserver.loyalty.constants import (
    PointHistoryChangeReasonConst,
    PointEarningExpiryTimeMilestoneConst,
    FeatureNameConst,
    PointExpiredReminderConst,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.models import FeatureSetting
from juloserver.julo.utils import display_rupiah, execute_after_transaction_safely

def update_loyalty_point_for_daily_checkin(daily_checkin_progress, today_reward, reason):
    customer_id = daily_checkin_progress.customer_id
    customer_point = get_and_lock_loyalty_point(customer_id)
    change_reason = get_point_history_change_reason(reason=reason)

    return update_customer_total_points(
        customer_id=customer_id,
        customer_point=customer_point,
        point_amount=today_reward,
        reason=change_reason,
        adding=True
    )


def update_loyalty_point_for_claim_mission_reward(mission_progress, mission_reward):
    customer_id = mission_progress.customer_id
    customer_point = get_and_lock_loyalty_point(customer_id)
    change_reason = get_point_history_change_reason(
        reason=PointHistoryChangeReasonConst.MISSION_COMPLETED,
        mission_progress=mission_progress
    )

    return update_customer_total_points(
        customer_id=customer_id,
        customer_point=customer_point,
        point_amount=mission_reward,
        reason=change_reason,
        adding=True
    )


def get_and_lock_loyalty_point(customer_id):
    # Split select_for_update because it's not supported in create method
    loyalty_point = get_non_locked_loyalty_point(customer_id)
    LoyaltyPoint.objects.select_for_update().filter(id=loyalty_point.id)
    return loyalty_point


def get_non_locked_loyalty_point(customer_id):
    loyalty_point = LoyaltyPoint.objects.filter(customer_id=customer_id).last()
    if not loyalty_point:
        with redis_lock_for_update(RedisLockKeyName.CREATE_LOYALTY_POINT, customer_id):
            loyalty_point, _ = (
                LoyaltyPoint.objects.get_or_create(customer_id=customer_id)
            )

    return loyalty_point


def create_point_earning(loyalty_point, customer_id, point_history, points):
    expiry_date = calculate_expiry_date()

    point_earning = PointEarning.objects.create(
        loyalty_point=loyalty_point,
        customer_id=customer_id,
        point_history_id=point_history.id,
        points=points,
        expiry_date=expiry_date
    )
    return point_earning


def calculate_expiry_date(create_date=None):
    """
        Calculate expiry date of point earning based on creation date:
            - Created on the first half of the year -> expired on 7/1 of the next year
            - Created on the second half of the year -> expired on 1/1 of the next 2 years
    """
    if not create_date:
        create_date = timezone.localtime(timezone.now()).date()

    year = create_date.year
    if create_date.month <= 6:
        milestone = PointEarningExpiryTimeMilestoneConst.FIRST_MILESTONE
    else:
        milestone = PointEarningExpiryTimeMilestoneConst.SECOND_MILESTONE

    expiry_year = year + milestone["duration"]
    expiry_month = milestone["month"]
    expiry_day = milestone["day"]
    return date(expiry_year, expiry_month, expiry_day)


def expire_per_customer_point_earning(customer, expiry_date):
    with transaction.atomic(using='utilization_db'):
        customer_point = get_and_lock_loyalty_point(customer.id)
        will_expired, available = get_unexpired_point_earnings(customer, expiry_date)
        if not will_expired:
            return

        will_expired_remaining_points = calculate_will_expired_remaining_points(
            customer_point, available
        )

        change_reason = get_point_history_change_reason(reason=PointHistoryChangeReasonConst.EXPIRED)
        if will_expired_remaining_points > 0:
            update_customer_total_points(
                customer_id=customer.id,
                customer_point=customer_point,
                point_amount=will_expired_remaining_points,
                reason=change_reason,
                adding=False
            )
        will_expired.update(is_expired=True)


def get_unexpired_point_earnings(customer, expiry_date):
    unexpired = PointEarning.objects.filter(
        customer_id=customer.id,
        is_expired=False
    )
    will_expired = unexpired.filter(expiry_date__lte=expiry_date)
    available = unexpired.filter(expiry_date__gt=expiry_date)
    return will_expired, available


def calculate_will_expired_remaining_points(customer_point, available_point_earnings):
    """
        Calculate will expire points of customer
            - Points <= 0: customer used more than the amount of will expire -> return 0
            - Points > 0: customer used less than the amount of will expire -> return points
    """
    total_points = customer_point.total_point
    available_points = sum(map(attrgetter("points"), available_point_earnings))
    return max(total_points - available_points, 0)


def update_customer_total_points(customer_id, customer_point, point_amount, reason, adding):
    from juloserver.julo.tasks import send_pn_invalidate_caching_point_change
    with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
        loyalty_point = get_and_lock_loyalty_point(customer_id)
        old_point = loyalty_point.total_point
        if adding:
            new_point = old_point + point_amount
        else:
            new_point = old_point - point_amount

        customer_point.update_safely(total_point=new_point)
        point_history = create_point_history(customer_id, old_point, new_point, reason)

        point_earning = None
        if adding:
            point_earning = create_point_earning(
                customer_point, customer_id, point_history, point_amount
            )

        execute_after_transaction_safely(
            lambda: send_pn_invalidate_caching_point_change.delay(customer_id)
        )

    return point_earning, point_history


def create_point_history(customer_id, old_point, new_point, reason):
    point_history = PointHistory.objects.create(
        customer_id=customer_id,
        old_point=old_point,
        new_point=new_point,
        change_reason=reason
    )
    return point_history


def get_point_history_change_reason(reason, mission_progress=None, point_deduct=None):
    if reason == PointHistoryChangeReasonConst.MISSION_COMPLETED:
        return mission_progress.mission_config.title
    elif reason == PointHistoryChangeReasonConst.POINT_REPAYMENT:
        return PointHistoryChangeReasonConst.REASON_MAPPING[reason].format(
            display_rupiah(point_deduct)
        )
    return PointHistoryChangeReasonConst.REASON_MAPPING[reason]


def get_account_payments_list(account):
    account_payments = AccountPayment.objects.filter(
        account=account, status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(due_amount=0, paid_amount=0).order_by('due_date')

    account_payments_list = []
    for account_payment in account_payments:
        account_payments_list.append(
            dict(
                due_status=account_payment.due_status(False),
                due_amount=account_payment.due_amount,
                due_date=account_payment.due_date,
                paid_date=account_payment.paid_date,
                account_payment_id=account_payment.id,

            )
        )
    return account_payments_list


def get_next_expired_date_and_point(customer, loyalty_point):
    """
        Get next expired_date & the
        total amount of expired point up to that date
    """
    today = timezone.localtime(timezone.now()).date()
    next_point_earning = PointEarning.objects.filter(
        customer_id=customer.id, is_expired=False, expiry_date__gte=today
    ).order_by('expiry_date').first()
    if not next_point_earning:
        return None, 0

    next_expiry_date = next_point_earning.expiry_date
    will_expired, available = get_unexpired_point_earnings(customer, next_expiry_date)
    will_expired_remaining_points = calculate_will_expired_remaining_points(
        loyalty_point, available
    )
    return next_expiry_date, will_expired_remaining_points


def get_point_reminder_config():
    setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.POINT_EXPIRE_REMINDER_CONFIGURATION)
    if not setting or not setting.is_active:
        return {}

    return setting.parameters or {}


def get_amount_deduct(account, total_point):
    from juloserver.julo.point_repayment_services import get_paid_amount_and_point_amount
    from juloserver.loyalty.utils import convert_point_to_rupiah
    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        return 0

    exchange_amount = convert_point_to_rupiah(total_point)
    return get_paid_amount_and_point_amount(exchange_amount, account_payment)


def construct_data_point_information(customer):
    loyalty_point = get_non_locked_loyalty_point(customer_id=customer.id)
    point_reminder_config = get_point_reminder_config()
    next_expiry_date, next_expiry_point = get_next_expired_date_and_point(
        customer, loyalty_point
    )
    total_point = loyalty_point.total_point
    # construct data
    data = {
        'point_amount': total_point,
        'point_reminder_config': point_reminder_config,
        'amount_deduct': get_amount_deduct(customer.account, total_point),
    }
    today = timezone.localtime(timezone.now()).date()
    reminder_days = point_reminder_config.get(
        'reminder_days', PointExpiredReminderConst.DEFAULT_REMINDER_DAYS
    )
    is_show_point_expiry_info = bool(
        next_expiry_point > 0 and (next_expiry_date - today).days <= reminder_days
    )
    if is_show_point_expiry_info:
        data.update({
            'next_expiry_date': next_expiry_date,
            'next_expiry_point': next_expiry_point,
        })
    return data


def check_loyalty_whitelist_fs(customer_id):
    loyalty_whitelist_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_LOYALTY_CUST, is_active=True
    ).last()

    if not loyalty_whitelist_fs:
        return True

    whitelist_customer_ids = loyalty_whitelist_fs.parameters.get('customer_ids', [])
    return customer_id in whitelist_customer_ids


def get_point_expiry_info(customer, loyalty_point):
    """
        Get nearest expiry date and expiry point amount
        Return formatted point expiry information
    """
    point_reminder_config = get_point_reminder_config()
    next_expiry_date, next_expiry_point = get_next_expired_date_and_point(
        customer, loyalty_point
    )
    today = timezone.localtime(timezone.now()).date()
    reminder_days = point_reminder_config.get(
        'reminder_days', PointExpiredReminderConst.DEFAULT_REMINDER_DAYS
    )
    is_show_point_expiry_info = bool(
        next_expiry_point > 0 and (next_expiry_date - today).days <= reminder_days
    )
    if not is_show_point_expiry_info:
        return None

    formatted_next_expiry_point = '{:,}'.format(next_expiry_point).replace(',', '.')
    formatted_next_expiry_date = next_expiry_date.strftime('%d %b %Y')
    return point_reminder_config.get(
        'point_expiry_info', PointExpiredReminderConst.Message.EXPIRY_INFO
    ).format(
        formatted_next_expiry_point, formatted_next_expiry_date
    )


def get_floating_action_button_info():
    fs = FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.FLOATING_ACTION_BUTTON,
    ).last()
    if not (fs and fs.parameters):
        return {'is_show_fab': False}

    return fs.parameters


def is_eligible_for_loyalty_entry_point(customer_id):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOYALTY_ENTRY_POINT,
        is_active=True
    ).last()
    if not feature_setting:
        return False

    if not check_loyalty_whitelist_fs(customer_id):
        return False

    return True
