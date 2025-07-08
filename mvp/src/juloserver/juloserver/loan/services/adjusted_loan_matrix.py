from typing import Tuple

from django.utils import timezone

from juloserver.julo.models import FeatureSetting
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import LoanFeatureNameConst

from juloserver.payment_point.constants import (
    TransactionMethodCode,
)


def get_daily_max_fee():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE, is_active=True
    ).last()
    if not feature_setting:
        return None
    params = feature_setting.parameters
    return float(params.get("daily_max_fee")) / float(100)


def get_adjusted_total_interest_rate(
    max_fee,
    provision_fee,
    insurance_premium_rate,
):
    """
    Get adjusted total interest rate case simple fee > max fee
    """
    adjusted_total_interest_rate = max_fee - provision_fee - insurance_premium_rate
    if adjusted_total_interest_rate < 0:

        # if negative, deduct this into provision fee
        provision_fee += adjusted_total_interest_rate

        # set zero
        adjusted_total_interest_rate = 0

        # if provision fee is negative again, deduct this into insurance
        if provision_fee < 0:
            insurance_premium_rate += provision_fee
            provision_fee = 0

    return (
        py2round(adjusted_total_interest_rate, 7),
        py2round(provision_fee, 7),
        py2round(insurance_premium_rate, 7),
    )


def get_global_cap_for_tenure_threshold(tenure):
    global_cap_fs = FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.GLOBAL_CAP_PERCENTAGE, is_active=True
    ).last()
    if not global_cap_fs:
        return None
    thresholds = global_cap_fs.parameters.get("tenure_thresholds", {})

    if str(tenure) in thresholds:
        return float(thresholds[str(tenure)]) / float(100)

    # Fallback to default threshold if no specific range matches
    return float(global_cap_fs.parameters.get("default")) / float(100)


def get_adjusted_monthly_interest_rate_case_exceed(
    adjusted_total_interest_rate,
    first_month_delta_days,
    loan_duration,
    days_in_month=30,
) -> Tuple[float, float]:
    """
    Calculate first and monthly interest (30 days) rates when total fee > max fee
    """
    adjusted_single_day_interest_rate = adjusted_total_interest_rate / (
        (loan_duration - 1) * days_in_month + first_month_delta_days
    )

    first = adjusted_single_day_interest_rate * first_month_delta_days
    monthly = adjusted_single_day_interest_rate * days_in_month

    return (
        py2round(first, 7),
        py2round(monthly, 7),
    )


def validate_max_fee_rule(
    first_payment_date,
    monthly_interest_rate,
    loan_duration,
    provision_fee_rate,
    insurance_premium_rate=0,
    delayed_disbursement_rate=0,
    kwargs={},
):
    today_date = timezone.localtime(timezone.now()).date()
    days_in_month = 30.0
    delta_days = days_in_month
    if first_payment_date:
        delta_days = (first_payment_date - today_date).days
    first_month_interest = (monthly_interest_rate / days_in_month) * delta_days
    rest_months_interest = monthly_interest_rate * (loan_duration - 1)
    total_fee_rate = (
        provision_fee_rate
        + first_month_interest
        + rest_months_interest
        + insurance_premium_rate
        + delayed_disbursement_rate
    )

    daily_max_fee = get_daily_max_fee()
    if not daily_max_fee:
        return False, total_fee_rate, None, None, None, None, None

    global_cap_fee = get_global_cap_for_tenure_threshold(loan_duration)
    if global_cap_fee:
        daily_max_fee = min(daily_max_fee, global_cap_fee)

    max_fee_rate = (((loan_duration - 1) * days_in_month) + delta_days) * daily_max_fee
    if kwargs.get("is_buku_warung"):
        max_fee_rate = kwargs.get("duration_in_days") * daily_max_fee

    # if eligible dd, and transaction method other than TARIK DANA
    dd_premium = kwargs.get("dd_premium", 0)
    if dd_premium and kwargs.get("transaction_method_id") != TransactionMethodCode.SELF.code:
        return get_adjusted_loan_non_tarik_dana(
            max_fee_rate=max_fee_rate,
            disbursement_amount=kwargs.get("disbursement_amount"),
            interest_rate=first_month_interest + rest_months_interest,
            provision_rate=provision_fee_rate,
            loan_duration=loan_duration,
            dd_premium=dd_premium,
        )

    adjusted_monthly_interest_rate = 0
    is_exceeded = total_fee_rate > max_fee_rate

    # if total > max, exclude insurance rate out of it (if any) to maximize our interest
    exceeded_with_insurance = is_exceeded and insurance_premium_rate > 0
    if exceeded_with_insurance:
        insurance_premium_rate = 0
        total_fee_rate = (
            provision_fee_rate
            + first_month_interest
            + rest_months_interest
            + delayed_disbursement_rate
        )
        # check exceeded again
        is_exceeded = total_fee_rate > max_fee_rate

    # continue adjusting other rates
    adjusted_total_interest_rate = 0
    if is_exceeded:
        (
            adjusted_total_interest_rate,
            provision_fee_rate,
            insurance_premium_rate,
        ) = get_adjusted_total_interest_rate(
            max_fee=max_fee_rate,
            provision_fee=provision_fee_rate,
            insurance_premium_rate=insurance_premium_rate,
        )

        adjusted_monthly_interest_rate = adjusted_total_interest_rate / float(loan_duration)

    # adjustment priority:
    # 1. julocares (must deduct to zero (completely))
    # 2. interest (can be deduct in %)
    # 3. provision (can be deduct in %)
    # 4. delay disbursement (must deduct to zero (completely))
    is_exceeded_with_dd = (
        (provision_fee_rate + adjusted_total_interest_rate + delayed_disbursement_rate)
        > max_fee_rate
    ) and delayed_disbursement_rate > 0
    if is_exceeded_with_dd:
        adjusted_total_interest_rate = max_fee_rate - provision_fee_rate - delayed_disbursement_rate
        if adjusted_total_interest_rate < 0:

            # if negative, deduct this into provision fee
            provision_fee_rate += adjusted_total_interest_rate

            # set zero
            adjusted_total_interest_rate = 0

            # if provision fee is negative again, remove delayed disbursement
            if provision_fee_rate < 0:
                provision_fee_rate = 0
                delayed_disbursement_rate = 0

        total_fee_rate = (
            provision_fee_rate + adjusted_total_interest_rate + delayed_disbursement_rate
        )

        adjusted_monthly_interest_rate = adjusted_total_interest_rate / float(loan_duration)

    return (
        is_exceeded,
        py2round(total_fee_rate, 7),
        py2round(max_fee_rate, 7),
        py2round(provision_fee_rate, 7),
        py2round(adjusted_monthly_interest_rate, 7),
        py2round(insurance_premium_rate, 7),
        py2round(delayed_disbursement_rate, 7),
    )


def validate_max_fee_rule_by_loan_requested(first_payment_date, loan_requested, kwargs={}):
    insurance_premium = loan_requested.get('insurance_premium') or 0
    loan_amount = loan_requested.get('loan_amount')
    if insurance_premium:
        insurance_premium = float(insurance_premium) / float(loan_amount)

    dd_premium = loan_requested.get('delayed_disbursement_premium') or 0
    if dd_premium:
        dd_premium = float(dd_premium) / float(loan_amount)

    (
        is_exceeded,
        total_fee_rate,
        max_fee_rate,
        provision_fee_rate,
        monthly_interest_rate,
        insurance_premium_rate,
        dd_premium_rate,
    ) = validate_max_fee_rule(
        first_payment_date,
        loan_requested['interest_rate_monthly'],
        loan_requested['loan_duration_request'],
        loan_requested['provision_fee'],
        insurance_premium,
        dd_premium,
        kwargs,
    )

    loan_requested['provision_fee'] = provision_fee_rate
    return (
        is_exceeded,
        total_fee_rate,
        max_fee_rate,
        monthly_interest_rate,
        insurance_premium_rate,
        provision_fee_rate,
        dd_premium_rate,
    )


# DD functions here instead of `delayed_disbursement_related`
# because of circular dependency

# Function to calculate the loan amount (for non tarik dana)
def calculate_loan_amount_non_tarik_dana_delay_disbursement(
    disbursement_amount, provision_rate, dd_premium=0
):
    return int(py2round((disbursement_amount + dd_premium) / (1 - provision_rate)))


# Function to calculate total fee rate
def calculate_total_fee_rate(interest_rate, provision_rate, loan_amount, dd_premium=0):
    dd_rate = dd_premium / loan_amount
    return interest_rate + provision_rate + dd_rate, dd_rate


def get_adjusted_loan_non_tarik_dana(
    max_fee_rate, disbursement_amount, interest_rate, provision_rate, loan_duration, dd_premium=0
):
    """
    Calculate the adjusted loan amount based on the given parameters
    adjustment hierarchy:
        DD
        INTEREST
        PROVISION
    """

    loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
        disbursement_amount, provision_rate, dd_premium
    )
    total_fee_rate, dd_rate = calculate_total_fee_rate(
        interest_rate, provision_rate, loan_amount, dd_premium
    )

    current_interest_rate = interest_rate  # total interest rate
    current_provision_rate = provision_rate
    current_dd_premium = dd_premium

    # Step 1: Remove dd_premium first
    if py2round(total_fee_rate, 7) > py2round(max_fee_rate, 7):
        current_dd_premium = 0
        loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
            disbursement_amount, current_provision_rate, current_dd_premium
        )
        total_fee_rate, dd_rate = calculate_total_fee_rate(
            current_interest_rate, current_provision_rate, loan_amount, current_dd_premium
        )

    # Step 2: Reduce interest rate next
    is_exceeded = py2round(total_fee_rate, 7) > py2round(max_fee_rate, 7)
    if is_exceeded:
        current_interest_rate = max(0, max_fee_rate - current_provision_rate)
        total_fee_rate, dd_rate = calculate_total_fee_rate(
            current_interest_rate, current_provision_rate, loan_amount, current_dd_premium
        )

    # Step 3.3: Reduce provision rate analytically
    if py2round(total_fee_rate, 7) > py2round(max_fee_rate, 7):
        current_provision_rate = max(0, min(provision_rate, max_fee_rate - current_interest_rate))
        loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
            disbursement_amount, current_provision_rate, current_dd_premium
        )
        total_fee_rate, dd_rate = calculate_total_fee_rate(
            current_interest_rate, current_provision_rate, loan_amount, current_dd_premium
        )

    return (
        is_exceeded,  # interest/provision adjusted
        py2round(total_fee_rate, 7),
        py2round(max_fee_rate, 7),
        py2round(current_provision_rate, 7),
        py2round(current_interest_rate / float(loan_duration), 7),  # monthly interest rate
        py2round(0, 7),
        py2round(dd_rate, 7),
    )


def get_loan_amount_and_provision_non_tarik_dana_delay_disbursement(
    original_loan_amount_requested, provision_fee_rate, dd_premium, *other_provisions
):

    loan_amount = calculate_loan_amount_non_tarik_dana_delay_disbursement(
        original_loan_amount_requested,
        provision_fee_rate,
        dd_premium,
    )

    # base provision
    provision_amount = int(py2round(loan_amount * provision_fee_rate))

    # add other provision components
    # other provisions including: insurance_premium, digisign_fee, total_registration_fee
    provision_amount += dd_premium + sum(other_provisions)

    return loan_amount, provision_amount
