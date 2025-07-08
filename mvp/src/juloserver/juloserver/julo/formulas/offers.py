from builtins import range
from collections import namedtuple
import logging

from . import compute_payment_installment
from juloserver.julo.exceptions import JuloException


logger = logging.getLogger(__name__)

OfferOption = namedtuple(
    'OfferOption', ['loan_amount', 'loan_duration', 'principal', 'interest', 'installment']
)


def get_offer_options(
        product_line, loan_amount_requested, loan_duration_requested, monthly_interest_rate,
        affordable_payment):
    offer_options = get_all_offer_options(
        product_line.min_amount,
        product_line.max_amount,
        product_line.amount_increment,
        product_line.min_duration,
        product_line.max_duration,
        monthly_interest_rate
    )
    offer_options = filter_max_installment(offer_options, affordable_payment)
    offer_options = filter_amount_range(offer_options, product_line.min_amount, loan_amount_requested)
    duration_margin = 2
    duration_min, duration_max = get_min_max(
        loan_duration_requested,
        duration_margin,
        product_line.min_duration,
        product_line.max_duration)
    offer_options = filter_duration_range(offer_options, duration_min, duration_max)
    offer_options = filter_top_installments_per_duration(offer_options)
    offer_options = sorted(
        sorted(
            offer_options,
            key=lambda x: x.loan_duration),
        key=lambda y: y.loan_amount,
        reverse=True)

    #if len(offer_options) == 0:
    #    raise JuloException('could not find offer matching criteria')

    return offer_options[:1]


def get_all_offer_options(
        amount_min, amount_max, amount_increment,
        duration_min, duration_max,
        monthly_interest_rate):
    offer_options = []
    for duration in range(duration_min, duration_max + 1):
        for amount in range(amount_min, amount_max + amount_increment, amount_increment):
            principal, interest, installment = compute_payment_installment(
                amount, duration, monthly_interest_rate)

            offer_option = OfferOption(
                loan_amount=amount,
                loan_duration=duration,
                principal=principal,
                interest=interest,
                installment=installment)
            offer_options.append(offer_option)
    return offer_options


def filter_max_installment(offer_options, max_installment):
    affordable_options = [
        oo for oo in offer_options if oo.installment <= max_installment
    ]
    return affordable_options


def filter_amount_range(offer_options, amount_min, amount_max):
    options_within_amount_range = [
        oo for oo in offer_options if amount_min <= oo.loan_amount <= amount_max
    ]
    return options_within_amount_range


def filter_duration_range(offer_options, duration_min, duration_max):
    options_within_duration_range = [
        oo for oo in offer_options if duration_min <= oo.loan_duration <= duration_max
    ]
    return options_within_duration_range


def filter_top_installments_per_duration(offer_options):

    all_durations = set()
    for offer_option in offer_options:
        all_durations.add(offer_option.loan_duration)

    closests_to_line = []
    for duration in sorted(all_durations):

        options_by_duration = [
            oo for oo in offer_options if oo.loan_duration == duration
        ]

        best_installment_by_duration = sorted(
            options_by_duration, key=lambda option: option.installment, reverse=True)[0]

        closests_to_line.append(best_installment_by_duration)

    closests_to_line.sort(key=lambda option: option.loan_duration)
    return closests_to_line


def get_min_max(loan_duration_requested, margin, min_duration, max_duration):
    # minimum duration is the loan request duration, except loan request duration greater than max
    result_min = loan_duration_requested if loan_duration_requested < max_duration else max_duration
    result_min = min_duration if result_min < min_duration else result_min
    # determine max duration
    unbounded_max = loan_duration_requested + margin
    result_max = max_duration if unbounded_max > max_duration else unbounded_max
    return result_min, result_max
