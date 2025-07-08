from __future__ import absolute_import
from __future__ import division

from builtins import str
from builtins import range
from past.utils import old_div
import logging
import hashlib
import os
import json
import math
import urllib.parse

from dateutil.relativedelta import relativedelta
from django.conf import settings
from datetime import datetime, timedelta

from juloserver.julo.constants import (
    MINIMUM_LOAN_DURATION_IN_DAYS,
    MINIMUM_DAY_DIFF_LDDE_OLD_FLOW,
    MINIMUM_DAY_DIFF_LDDE_v2_FLOW,
)
from juloserver.julo.constants import FalseRejectMiniConst
from ..product_lines import ProductLineCodes
from ..exceptions import JuloException
from babel.dates import format_date

logger = logging.getLogger(__name__)
MAX_CYCLE_DAY = 28
DAYS_TO_ACTIVATE_LOAN = relativedelta(days=0)
FIRST_OF_NEXT_MONTH = relativedelta(months=1, day=1)
ONE_MONTH_LATER = relativedelta(months=1)


def round_rupiah(number):
    """
    Rounds number down to previous thousand, returns int.
    """
    return int(math.floor(number / 1000.0) * 1000)


def round_rupiah_grab(number):
    """
    Rounds number down to previous thousand, returns int.
    """
    return int(math.floor(number))


def round_rupiah_merchant_financing(number):
    """
    Rounds number down to previous thousand, returns int.
    """
    return int(math.floor(number))


def round_cashback(number):
    """
    Rounds number down to previous whole number, returns int.
    """
    return int(math.floor(number))


def round_nearest_500000(number):
    """
    Return number round to nearest 500000
    """
    from juloserver.julocore.python2.utils import py2round
    return int(py2round(old_div(number, 500000)) * 500000)


def compute_cashback_total(
        loan_amount, cashback_initial_pct, cashback_payment_pct):

    cashback_initial = compute_cashback(loan_amount, cashback_initial_pct)
    cashback_earned = compute_cashback(loan_amount, cashback_payment_pct)
    cashback_total = cashback_initial + cashback_earned
    logger.debug({
        'loan_amount': loan_amount,
        'cashback_initial_pct': cashback_initial_pct,
        'cashback_payment_pct': cashback_payment_pct,
        'cashback_total': cashback_total,
        'status': 'computed'
    })
    return cashback_total


def compute_skiptrace_effectiveness(skiptrace):
    effectiveness = 0.0
    count = 0
    query = skiptrace.skiptracehistory_set.all()
    query = query.prefetch_related('call_result')
    for history in query:
        if history.call_result.name in ['Not Connected', 'Rejected/Busy', 'No Answer']:
            count += 1
        else:
            effectiveness += history.call_result.weight
    effectiveness -= count // 3
    return effectiveness


def determine_loan_start_date(verification_call_date):
    """
    To avoid picking due dates on 29.-31. for applications without payday
    """
    loan_start_date = verification_call_date + DAYS_TO_ACTIVATE_LOAN

    if loan_start_date.day > MAX_CYCLE_DAY:
        loan_start_date = loan_start_date + FIRST_OF_NEXT_MONTH

    logger.debug({
        'offer_accepted_date': verification_call_date,
        'loan_start_date': loan_start_date,
        'cycle_day': loan_start_date.day
    })
    return loan_start_date


def determine_due_dates(loan_start_date, loan_duration):
    """The due dates are returned in chronological order"""
    first_due_date = loan_start_date + ONE_MONTH_LATER
    logger.debug({
        'loan_start_date': loan_start_date,
        'first_due_date': first_due_date,
        'loan_duration': loan_duration
    })

    due_date = first_due_date
    due_dates = []
    for i in range(loan_duration):
        due_dates.append(due_date)
        logger.debug({
            'due_date': due_date,
            'due_date_number': i + 1
        })
        due_date = due_date + ONE_MONTH_LATER

    return due_dates


def filter_due_dates_by_offerday(offerday):
    # get possible due_dates by offerday rule
    min_rule_offerday = 15
    max_rule_offerday = 45

    due_dates = []

    # get possible due date by rule1 (offerday rule)
    for days in range(min_rule_offerday, max_rule_offerday):
        due_date = offerday + relativedelta(days=days)
        due_dates.append(due_date)

    if len(due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_offerday',
            'first_possible_date': due_dates[0],
            'last_possible_dates': due_dates[-1]
        })
        return due_dates
    else:
        raise JuloException


def filter_due_dates_by_payday(payday, offerday, mtl=True, loan_duration=None):
    # filter possible due_dates by payday rule
    if mtl:
        min_rule_payday = 2
    else:
        min_rule_payday = -4
    max_rule_payday = 4

    if loan_duration == 2:
        min_rule_payday = 0
        max_rule_payday = 17

    filtered_due_dates = []
    paydate = None
    # force payday more then 28
    payday = payday or 0
    if payday > 28:
        payday = 28

    # get possible paydate parameter by payday and offer_accepted_day

    if payday <= offerday.day:
        paydate = offerday + relativedelta(months=1, day=payday)
    else:
        paydate = offerday + relativedelta(day=payday)

    # get possible due date in rule 1 by rule2 (payday rule)
    for days in range(min_rule_payday, max_rule_payday + 1):
        due_date_payday = paydate + relativedelta(days=days)
        due_date_payday_next = paydate + relativedelta(days=days, months=1)
        if 45 >= (due_date_payday - offerday).days >= 15:
            filtered_due_dates.append(due_date_payday)
        if 45 >= (due_date_payday_next - offerday).days >= 15:
            filtered_due_dates.append(due_date_payday_next)

    if len(filtered_due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_payday',
            'first_possible_date': filtered_due_dates[0],
            'last_possible_dates': filtered_due_dates[-1]
        })
        return filtered_due_dates
    else:
        raise JuloException


def filter_due_dates_by_payday_monthly(payday, offerday):
    # filter possible due_dates by payday rule
    min_rule_payday = 1
    max_rule_payday = 7
    max_count_monthly = 4

    filtered_due_dates = []
    paydate = None
    # get possible paydate parameter by payday and offer_accepted_day
    if payday <= offerday.day:
        paydate = offerday + relativedelta(months=1, day=payday)
    else:
        paydate = offerday + relativedelta(day=payday)

    # get possible due date in rule 1 by rule2 (payday rule)
    for days in range(min_rule_payday, max_rule_payday + 1):
        due_date_payday = paydate + relativedelta(days=days)
        filtered_due_dates.append(due_date_payday)
        for x in range(0, max_count_monthly):
            due_date_payday_next = paydate + relativedelta(days=days, months=x + 1)
            filtered_due_dates.append(due_date_payday_next)

    if len(filtered_due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_payday',
            'first_possible_date': filtered_due_dates[0],
            'last_possible_dates': filtered_due_dates[-1]
        })
        return filtered_due_dates
    else:
        raise JuloException


def filter_due_dates_by_weekend(due_dates):
    # get available due date after filter by weekend "Saturday"& "Sunday"
    filtered_due_dates = []

    for due_date in due_dates:
        if due_date.weekday() < 5:
            filtered_due_dates.append(due_date)
    if len(filtered_due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_weekend',
            'first_possible_date': filtered_due_dates[0],
            'last_possible_dates': filtered_due_dates[-1]
        })
        return filtered_due_dates
    else:
        raise JuloException


def get_pub_holiday(product_line_code):
    restricted_dates = []
    product_list = ProductLineCodes.mtl() + ProductLineCodes.laku6() + ProductLineCodes.\
        icare() + ProductLineCodes.julo_one()
    mtl = True if product_line_code in product_list else False
    json_file = 'public_holiday.json'

    if mtl:
        json_file = 'mtl_public_holiday.json'
    file = os.path.join(settings.BASE_DIR, 'juloserver', 'julo', 'helpers',
                        json_file)
    filepath = os.path.abspath(file)

    with open(filepath, 'r') as f:
        restricted_dates = json.loads(f.read())
    return restricted_dates


def calculate_first_due_date_ldde_old_flow(payday, cycle_day, offer_date):
    if payday < offer_date.day:
        due_date = offer_date + relativedelta(months=1)
    else:
        due_date = offer_date
    first_due_date = due_date + relativedelta(day=cycle_day)
    if (first_due_date - offer_date).days < MINIMUM_DAY_DIFF_LDDE_OLD_FLOW:
        first_due_date = first_due_date + relativedelta(months=1, day=cycle_day)
        if (first_due_date - offer_date).days < MINIMUM_DAY_DIFF_LDDE_OLD_FLOW:
            first_due_date = first_due_date + relativedelta(months=1, day=cycle_day)
    return first_due_date


def calculate_first_due_date_ldde_v2_flow(payday, cycle_day, offer_date):
    if payday < offer_date.day:
        due_date = offer_date + relativedelta(months=1)
    else:
        due_date = offer_date
    first_due_date = due_date + relativedelta(day=cycle_day)
    if (first_due_date - offer_date).days < MINIMUM_DAY_DIFF_LDDE_v2_FLOW:
        first_due_date = first_due_date + relativedelta(months=1, day=cycle_day)
        if (first_due_date - offer_date).days < MINIMUM_DAY_DIFF_LDDE_v2_FLOW:
            first_due_date = first_due_date + relativedelta(months=1, day=cycle_day)
    return first_due_date


def filter_due_dates_by_pub_holiday(due_dates, mtl=False):
    # get possible due_dates filtered by public_holiday
    filtered_due_dates = []
    json_file = 'public_holiday.json'
    if mtl:
        json_file = 'mtl_public_holiday.json'
    file = os.path.join(settings.BASE_DIR, 'juloserver', 'julo', 'helpers',
                        json_file)
    filepath = os.path.abspath(file)

    with open(filepath, 'r') as f:
        restricted_dates = json.loads(f.read())

    for due_date in due_dates:
        if str(due_date) not in restricted_dates:
            filtered_due_dates.append(due_date)
    if len(filtered_due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_pub_holiday',
            'first_possible_date': filtered_due_dates[0],
            'last_possible_dates': filtered_due_dates[-1]
        })
        return filtered_due_dates
    else:
        raise JuloException


def filter_due_dates_by_restrict_dates(due_dates, loan_duration=None):
    # get due_date filter by dates 31
    restrict_dates = []
    max_day = 30
    for due_date in due_dates:
        if due_date.day <= max_day:
            continue
        if not loan_duration or due_date.day == 31:
            restrict_dates.append(due_date)
            continue
        start_month = due_date.month
        end_month = start_month + loan_duration - 1
        if not (start_month > 2 and end_month < 14):
            restrict_dates.append(due_date)
    for restrict_date in restrict_dates:
        due_dates.remove(restrict_date)
    if len(due_dates) > 0:
        logger.debug({
            'action': 'filter_due_dates_by_restrict_dates',
            'first_possible_date': due_dates[0],
            'last_possible_dates': due_dates[-1]
        })
        return due_dates
    else:
        raise JuloException


def filter_due_dates_by_experiment(payday, offerday, customer_id):
    # get possible duedates filtered by experiment
    filtered_due_dates = []
    payday = payday or 0
    origin_payday = payday

    cycle_day = 1 if payday == 31 else payday + 1

    last_day = (datetime(offerday.year, offerday.month, 1) + relativedelta(months=1, days=-1)).day
    if (
        cycle_day <= offerday.day
        or ((last_day - offerday.day) < 6 and origin_payday == 30)
        or (cycle_day - offerday.day) < 6):
        paydate = offerday + relativedelta(months=1, day=cycle_day)
        if (paydate - offerday).days < 6:
            paydate = paydate + relativedelta(months=1)
        filtered_due_dates.append(paydate)
    else:
        paydate = offerday + relativedelta(day=cycle_day)
        filtered_due_dates.append(paydate)

    logger.info({
        'action': 'filter_due_dates_by_experiment',
        'offer_date': offerday,
        'filtered_due_dates': filtered_due_dates,
        'cycle_day': cycle_day,
        'customer_id': customer_id
    })
    return filtered_due_dates


def pick_date_closest_to_one_month(due_dates, offer_date, payday, loan_duration):
    """
    Pick the date that is closest to one month from the offer date
    """
    deltas = []
    if loan_duration == 2:
        next_month = offer_date + relativedelta(days=30)
        best_date = next_month + relativedelta(day=payday+2) #to get due_date near payday if posibble
    else:
        best_date = offer_date + relativedelta(days=30)

    for due_date in due_dates:
        delta = abs((due_date - best_date).days)
        deltas.append((due_date, delta))

    closest_due_dates = sorted(deltas, key=lambda x: x[1])
    if len(closest_due_dates) == 0:
        raise JuloException('There is no available date to pick please contact administrator!!')

    closest_due_date = closest_due_dates[0][0]
    if len(closest_due_dates) > 1:
        if closest_due_dates[0][1] == closest_due_dates[1][1]:
            closest_due_date = closest_due_dates[0][0] if closest_due_dates[0][0] > closest_due_dates[1][0] else closest_due_dates[1][0]
    logger.info({
        'closest_due_date': closest_due_date,
        'due_dates': [str(d) for d in due_dates],
        'offerdate': offer_date
    })
    return closest_due_date


# seems no longer used
def determine_due_dates_by_payday(payday, offer_accepted_date, loan_duration, product_line_code):
    """
    The first due date will return adjusted with the payday and
    offer_accepted_date by rule
    rule 1 :
    due_date must be in range of offerday+18 <= due_date <= offerday+43
    rule2 :
    due_date from rule 1 must be in range of payday+1 <= due_date payday+7
    rule3:
    due_date from rule 3 should not in weekend day eg: 'Saturday', 'Sunday'
    rule4:
    due_date from rule 4 should not in public holiday
    """
    due_dates_by_rule2 = get_available_due_dates_by_payday(payday, offer_accepted_date, product_line_code, loan_duration)
    # due_dates_by_rule3 = filter_due_dates_by_weekend(due_dates_by_rule2)
    due_dates_by_rule4 = filter_due_dates_by_pub_holiday(due_dates_by_rule2)

    if product_line_code in ProductLineCodes.mtl():
        try:
            due_dates_by_rule4 = filter_due_dates_by_restrict_dates(due_dates_by_rule4)
        except JuloException:
            raise JuloException(payday, offer_accepted_date)

    due_date = pick_date_closest_to_one_month(due_dates_by_rule4, offer_accepted_date, payday, loan_duration)
    due_dates = []

    for i in range(loan_duration):
        due_dates.append(due_date)
        logger.debug({
            'due_date': due_date,
            'due_date_number': i + 1
        })
        due_date = due_date + ONE_MONTH_LATER

    return due_dates


def filter_due_dates_create_second_due_date_less_61_days(due_dates, offer_accepted_date):
    filtered_due_dates = []
    for due_date in due_dates:
        second_due_date = due_date + relativedelta(months=1)
        days_diff = (second_due_date - offer_accepted_date).days
        if days_diff >= MINIMUM_LOAN_DURATION_IN_DAYS:
            filtered_due_dates.append(due_date)
    return filtered_due_dates


def determine_first_due_dates_by_payday(payday, offer_accepted_date, product_line_code,
    loan_duration=None, customer_id=None, experiment_flag=False):
    """
    get possible due_dates by payday and pick one from these due dates which is closest to one month
    """
    due_dates = get_available_due_dates_by_payday(
        payday, offer_accepted_date, product_line_code, loan_duration, customer_id, experiment_flag
    )
    due_date = pick_date_closest_to_one_month(due_dates, offer_accepted_date, payday, loan_duration)

    return due_date


def get_available_due_dates_by_payday(payday, offer_accepted_date, product_line_code, loan_duration=None, customer_id=None, experiment_flag=False):
    """
    The first due date will return adjusted with the payday and
    offer_accepted_date by rule
    rule 1 :
    due_date must be in range of offerday+18 <= due_date <= offerday+43
    rule2 :
    due_date from rule 1 must be in range of payday+2 <= due_date payday+4
    rule3:
    due_date from rule 3 should not in weekend day eg: 'Saturday', 'Sunday'
    rule4:
    due_date from rule 4 should not in public holiday
    rule5:
    due_date from rule 4 that will create second_due_date <61
    """
    product_list = ProductLineCodes.mtl() + ProductLineCodes.laku6() + ProductLineCodes.\
        icare() + ProductLineCodes.julo_one()
    mtl = True if product_line_code in product_list else False
    if not experiment_flag:
        due_dates_by_rule2 = filter_due_dates_by_payday(payday, offer_accepted_date, mtl, loan_duration)
        # due_dates_by_rule3 = filter_due_dates_by_weekend(due_dates_by_rule2) --> disabled by Card #2501 on trello
        due_dates_by_rule4 = filter_due_dates_by_pub_holiday(due_dates_by_rule2, mtl)
    else:
        due_dates_by_rule4 = filter_due_dates_by_experiment(
            payday, offer_accepted_date, customer_id)

    if product_line_code in ProductLineCodes.mtl():
        try:
            due_dates_by_rule4 = filter_due_dates_by_restrict_dates(due_dates_by_rule4, loan_duration)

            # rule5 to filter first_due_date that will create second_due_date <61 when loan duration is 2
            if loan_duration and loan_duration == FalseRejectMiniConst.MIN_DURATION:
                due_dates_by_rule4 = filter_due_dates_create_second_due_date_less_61_days(
                    due_dates_by_rule4, offer_accepted_date)
        except JuloException:
            raise JuloException(payday, offer_accepted_date)

    return due_dates_by_rule4


def get_available_due_dates_by_payday_monthly(payday, offer_accepted_date, product_line_code, loan_duration=None):
    """
    The first due date will return adjusted with the payday and
    offer_accepted_date by rule
    rule 1 :
    due_date must be in range of offerday+18 <= due_date <= offerday+43
    rule2 :
    due_date from rule 1 must be in range of payday+1 <= due_date payday+7
    rule3:
    due_date from rule 3 should not in weekend day eg: 'Saturday', 'Sunday'
    rule4:
    due_date from rule 4 should not in public holiday
    """

    due_dates_by_rule2 = filter_due_dates_by_payday_monthly(payday, offer_accepted_date)
    # due_dates_by_rule3 = filter_due_dates_by_weekend(due_dates_by_rule2) --> disabled by Card #2501 on trello
    mtl = True if product_line_code in ProductLineCodes.mtl() else False
    due_dates_by_rule4 = filter_due_dates_by_pub_holiday(due_dates_by_rule2, mtl)

    if product_line_code in ProductLineCodes.mtl():
        try:
            due_dates_by_rule4 = filter_due_dates_by_restrict_dates(due_dates_by_rule4, loan_duration)
        except JuloException:
            raise JuloException(payday, offer_accepted_date)

    return due_dates_by_rule4


def get_new_due_dates_by_cycle_day(new_cycle_day, remaining_due_dates):

    new_due_dates = []

    remaining_loan_duration = len(remaining_due_dates)
    if remaining_loan_duration == 0:
        logger.warn({
            'remaining_loan_duration': remaining_loan_duration,
            'new_due_dates': new_due_dates
        })
        return new_due_dates

    if new_cycle_day > MAX_CYCLE_DAY:
        logger.warn({
            'new_cycle_day': new_cycle_day,
            'new_due_dates': new_due_dates
        })
        return new_due_dates

    next_due_date = remaining_due_dates[0]
    old_cycle_day = next_due_date.day
    if new_cycle_day >= old_cycle_day:
        next_due_date = next_due_date + relativedelta(day=new_cycle_day)
    else:
        next_due_date = next_due_date + relativedelta(months=1, day=new_cycle_day)
    logger.debug({
        'new_cycle_day': new_cycle_day,
        'old_cycle_day': old_cycle_day,
        'next_due_date': next_due_date
    })

    new_due_date = next_due_date
    for i in range(remaining_loan_duration):
        logger.debug({
            'new_due_date': new_due_date,
            'status': 'changed'
        })
        new_due_dates.append(new_due_date)
        new_due_date = new_due_date + ONE_MONTH_LATER

    return new_due_dates


def get_restricted_dates():

    file = os.path.join(settings.BASE_DIR,
                        'juloserver',
                        'julo',
                        'helpers',
                        'public_holiday.json')
    filepath = os.path.abspath(file)

    with open(filepath, 'r') as f:
        restricted_dates = json.loads(f.read())

    return restricted_dates


def get_available_due_dates_weekday_daily(start_date, loan_duration):

    daily_due_dates = []
    restricted_dates = get_restricted_dates()
    state = 0

    while len(daily_due_dates) < loan_duration:
        current_date = start_date + relativedelta(days=state)
        if current_date.weekday() < 5 and str(current_date) not in restricted_dates:
            daily_due_dates.append(current_date)
        state += 1

    return daily_due_dates


def get_start_date_in_business_day(start_date, delta):

    dates = []
    restricted_dates = get_restricted_dates()
    state = 1

    while len(dates) < delta:
        current_date = start_date + relativedelta(days=state)
        if current_date.weekday() < 5 and str(current_date) not in restricted_dates:
            dates.append(current_date)
        state += 1

    return dates[-1]


def compute_cashback(loan_amount, cashback_pct):
    cashback = round_cashback(float(loan_amount) * cashback_pct)

    logger.debug({
        'loan_amount': loan_amount,
        'cashback_pct': cashback_pct,
        'cashback': cashback,
        'status': 'computed'
    })
    return cashback


def compute_cashback_monthly(loan_amount, cashback_payment_pct, loan_duration):
    """
    cashback earned = ( loan amount x cashback payment percentage )
                      --------------------------------------------
                                   loan duration
    """
    cashback_earned_total = float(loan_amount) * cashback_payment_pct
    cashback_earned_monthly = round_cashback(old_div(cashback_earned_total, loan_duration))
    logger.debug({
        'loan_amount': loan_amount,
        'loan_duration': loan_duration,
        'cashback_payment_pct': cashback_payment_pct,
        'cashback_earned_total': cashback_earned_total,
        'cashback_earned_monthly': cashback_earned_monthly,
        'status': 'computed'
    })
    return cashback_earned_monthly


def compute_new_cashback_monthly(loan_amount, cashback_payment_pct, loan_duration, counter):
    """
    cashback earned =   loan amount 
                        ------------ x (cashback percentage x counter)
                        loan duration
    """
    loan_amount_monthly = loan_amount / loan_duration
    cashback_percentage = cashback_payment_pct * counter
    final_cashback = round_cashback(loan_amount_monthly * cashback_percentage)
    logger.debug({
        'loan_amount': loan_amount,
        'loan_duration': loan_duration,
        'cashback_payment_pct': cashback_payment_pct,
        'counter': counter,
        'final_cashback': final_cashback,
        'status': 'computed'
    })
    return final_cashback


def compute_xid(application_id):
    app_xid = None

    xid_replacement = {
        '2000365566': 9756700563,
        '2000234341': 1071069935,
        '2000208709': 5988899334,
        '2000395245': 5354417138,
        '2000835885': 3685877690,
        '2000747987': 6955849929,
        '2000561040': 7191626843,
        '2000428090': 3905331204,
        '2000057065': 4334073761,
        '2000066755': 3824898436,
        '2000260510': 2804802015,
        '2000067057': 3991210658,
        '2000177044': 9314080482,
        '2000302244': 6219321364,
        '2000057631': 7046013944,
        '2000607846': 8784937775,
        '2000334477': 6845937253,
        '2000317252': 1879061868,
        '2000051580': 9727926369,
        '2000181630': 4893457160,
        '2000014560': 9812163578,
        '2000013934': 1773848385,
        '2000608623': 7946511209,
        '2000047116': 1453182444,
        '2000190560': 1772771445,
        '2000763093': 4764822548,
        '2000294914': 1187182595,
        '2000567473': 8420751969,
        '2000509834': 2257055531,
        '2000338426': 4884931402,
        '2000849024': 1442947222,
        '2000171387': 2013756094,
        '2000478659': 4956001341,
        '2000220362': 6431846556,
        '2000593960': 6368173236,
        '2000231399': 7641879031,
        '2000228376': 3387696489,
        '2000103958': 3559800078,
        '2000639768': 1547210235,
        '2000115938': 6721770250,
        '2000081298': 6384698518,
        '2000137971': 3352012254,
        '2000322817': 9712980912,
        '2000308154': 5698779000,
        '2000649773': 8571333618,
        '2000316212': 6758994856,
        '2000351527': 4483716775,
        '2000252606': 5417270876,
        '2000127118': 7638056729,
        '2000021278': 4211643144,
        '2000727163': 9310728035,
        '2000199847': 7450220307,
        '2000224421': 4985491530,
        '2000321433': 7257239245,
        '2000156956': 7903402750,
        '2000260792': 5758262974,
        '2000260485': 2022061793}

    xid_repl = xid_replacement.get(str(application_id))

    if xid_repl:  # if xid found in the replacement list then use it
        app_xid = xid_repl
    else:
        app_xid = int(hashlib.sha1(str(application_id).encode()).hexdigest(), 16) % (10 ** 10)

        # has to be 10 digits
        if app_xid < 1000000000:
            app_xid = app_xid + 1000000000

    return app_xid


def compute_payment_installment(loan_amount, loan_duration_months, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    principal = int(math.floor(float(loan_amount) / float(loan_duration_months)))
    interest = int(math.floor(float(loan_amount) * monthly_interest_rate))

    installment_amount = round_rupiah(principal + interest)
    derived_interest = installment_amount - principal

    return principal, derived_interest, installment_amount


def compute_adjusted_payment_installment(
        loan_amount, loan_duration, monthly_interest_rate, start_date, end_date):
    """
    Computes installment and interest for first installment
    """
    days_in_month = 30.0
    delta_days = (end_date - start_date).days
    principal = int(math.floor(float(loan_amount) / float(loan_duration)))
    basic_interest = float(loan_amount) * monthly_interest_rate
    adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))

    installment_amount = round_rupiah(principal + adjusted_interest)
    derived_adjusted_interest = installment_amount - principal

    return principal, derived_adjusted_interest, installment_amount


def compute_weekly_payment_installment(loan_amount, loan_duration_weeks, interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    principal = float("{0:.2f}".format(float(loan_amount) / loan_duration_weeks))
    interest = float("{0:.2f}".format(old_div((float(loan_amount) * interest_rate), loan_duration_weeks)))

    installment_amount = round_rupiah(principal + interest)
    derived_interest = float("{0:.2f}".format(installment_amount - principal))

    return principal, derived_interest, installment_amount


def next_grab_food_payment_date(previous_date):
    skiped_date = (datetime.strptime("2018-06-13", '%Y-%m-%d').date(),
                   datetime.strptime("2018-06-19", '%Y-%m-%d').date())

    next_date = previous_date + relativedelta(weeks=1)
    if skiped_date[0] <= next_date <= skiped_date[1]:
        next_date = next_date + relativedelta(weeks=1)
    return next_date

def next_partner_payment_date(previous_date, type="monthly"):
    skiped_date = (datetime.strptime("2018-06-13", '%Y-%m-%d').date(),
                   datetime.strptime("2018-06-19", '%Y-%m-%d').date())

    next_date = previous_date + relativedelta(weeks=1)
    if skiped_date[0] <= next_date <= skiped_date[1]:
        next_date = next_date + relativedelta(weeks=1)
    return next_date


def count_expired_date_131(date):
    date_range = list(date + relativedelta(days=x) for x in range((date + relativedelta(days=14) - date).days))
    filtered_date_range = filter_due_dates_by_pub_holiday(filter_due_dates_by_weekend(date_range))
    return format_date(filtered_date_range[1], 'EEEE', locale='id_ID')


def compute_laku6_payment_installment(loan_amount, loan_principal, loan_duration_months, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    principal = int(math.floor(float(loan_principal) / int(loan_duration_months)))
    interest = int(math.floor(float(loan_principal) * monthly_interest_rate))
    last_payment = int(math.floor(old_div((float(loan_amount) * 0.45), 12)))

    installment_amount = round_rupiah(principal + interest - last_payment)
    derived_interest = interest

    return principal, derived_interest, installment_amount


def compute_laku6_adjusted_payment_installment(
        loan_amount, loan_principal, loan_duration, monthly_interest_rate, start_date, end_date):
    """
    Computes installment and interest for first installment
    """
    days_in_month = 30.0
    delta_days = (end_date - start_date).days

    principal = int(math.floor(float(loan_principal) / int(loan_duration)))
    basic_interest = float(loan_principal) * monthly_interest_rate
    adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))
    last_payment = int(math.floor(old_div((float(loan_amount) * 0.45), 12)))

    installment_amount = round_rupiah(principal + adjusted_interest - last_payment)
    derived_adjusted_interest = adjusted_interest

    return principal, derived_adjusted_interest, installment_amount
