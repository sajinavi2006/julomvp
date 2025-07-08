from __future__ import division
from builtins import str
from builtins import range
import math

from juloserver.julocore.python2.utils import py2round

from .constants import FIELDS_MAP, ProductProfileCode


def get_cleaned_data(data):
    list_type = ['job_type', 'job_industry', 'job_description', 'location', 'credit_score']
    bool_type = ['is_active', 'is_initial', 'is_product_exclusive']

    for key in data:
        if key not in list_type and key not in bool_type:
            if data[key] != None:
                data[key] = FIELDS_MAP[key](str(data[key])) if key in FIELDS_MAP else data[key]
            else:
                data[key] = None
        if key in list_type:
            if data[key] != None:
                data[key] = FIELDS_MAP[key](data[key]) if key in FIELDS_MAP else data[key]

    return data


def generate_rate(min_value, max_value, increment_value):
    rate_list = [min_value]
    delta = max_value - min_value
    count = 1

    if min_value > max_value:
        raise Exception('min_value could not greater than max_value')

    if increment_value > max_value:
        raise Exception('increment value could not greater than max value')

    if 0 < increment_value < delta:
        count = int(py2round(delta / increment_value))

    if min_value == max_value:
        return rate_list

    for counter in range(1, (count + 1)):
        rate = min_value + (increment_value * counter)
        rate_dec = float("%.4f" % rate)

        if rate_dec < max_value and rate_dec not in rate_list:
            rate_list.append(rate_dec)

        if counter == count:
            rate_list.append(max_value)

    return rate_list


def generate_product_name(interest_rate, origination_fee, late_fee,
                          cashback_initial, cashback_payment, payment_frequency):

    interest_rate_str = "{0:.3f}".format(interest_rate)[1:]
    origination_fee_str = "{0:.3f}".format(origination_fee)[1:]
    late_fee_str = "{0:.3f}".format(late_fee)[1:]
    cashback_initial_str = "{0:.3f}".format(cashback_initial)[1:]
    cashback_payment_str = "{0:.3f}".format(cashback_payment)[1:]

    if interest_rate > 0.9999:
        interest_rate_str = "{0:.3f}".format(interest_rate)[0:]
    if origination_fee > 0.9999:
        origination_fee_str = "{0:.3f}".format(origination_fee)[0:]
    if late_fee > 0.9999:
        late_fee_str = "{0:.3f}".format(late_fee)[0:]
    if cashback_initial > 0.9999:
        cashback_initial_str = "{0:.3f}".format(cashback_initial)[0:]
    if cashback_payment > 0.9999:
        cashback_payment_str = "{0:.3f}".format(cashback_payment)[0:]

    product_name = 'I%s-O%s-L%s-C1%s-C2%s-%s' % (interest_rate_str,
                                                 origination_fee_str,
                                                 late_fee_str,
                                                 cashback_initial_str,
                                                 cashback_payment_str,
                                                 payment_frequency[0])
    return product_name


def generate_product_lookup(product_profile, product_line):
    min_interest_rate = product_profile.min_interest_rate
    max_interest_rate = product_profile.max_interest_rate
    interest_rate_increment = product_profile.interest_rate_increment
    min_origination_fee = product_profile.min_origination_fee
    max_origination_fee = product_profile.max_origination_fee
    origination_fee_increment = product_profile.origination_fee_increment
    late_fee = product_profile.late_fee
    cashback_initial = product_profile.cashback_initial
    cashback_payment = product_profile.cashback_payment
    payment_frequency = product_profile.payment_frequency

    interest_rate_list = generate_rate(min_interest_rate,
                                       max_interest_rate,
                                       interest_rate_increment)

    origination_fee_list = generate_rate(min_origination_fee,
                                         max_origination_fee,
                                         origination_fee_increment)
    product_lookup_list = []

    for interest_rate in interest_rate_list:
        if product_profile.code == ProductProfileCode.EMPLOYEE_FINANCING:  # for employee financing multiply with 12
            interest_rate = interest_rate * 12
        for origination_fee in origination_fee_list:
            product_lookup = {}
            product_name = generate_product_name(interest_rate, origination_fee, late_fee,
                                                 cashback_initial, cashback_payment,
                                                 payment_frequency)
            product_lookup['interest_rate'] = interest_rate
            product_lookup['origination_fee_pct'] = origination_fee
            product_lookup['product_name'] = product_name
            product_lookup['late_fee_pct'] = late_fee
            product_lookup['cashback_initial_pct'] = cashback_initial
            product_lookup['cashback_payment_pct'] = cashback_payment
            product_lookup['is_active'] = True
            product_lookup['product_line'] = product_line
            product_lookup['product_profile'] = product_profile
            product_lookup_list.append(product_lookup)

    return product_lookup_list
