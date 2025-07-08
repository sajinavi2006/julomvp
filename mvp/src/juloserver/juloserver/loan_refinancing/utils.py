from __future__ import division
from builtins import str
from past.utils import old_div
from babel.dates import format_date
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from datetime import datetime
import calendar

from .constants import LoanRefinancingConst, CovidRefinancingConst
from ..julo.product_lines import ProductLineCodes


def convert_string_date_to_date_object(string_date):
    try:
        result = datetime.strptime(string_date, '%Y-%m-%d').date()

        return result
    except ValueError:
        return False


def convert_payment_format_to_plaform_for_agent(payments, is_object=True):
    data_to_return = {}
    today = timezone.localtime(timezone.now()).date()
    converted_payments = []
    total_principal = 0
    total_interest = 0
    total_late_fee = 0
    total_all_installment_amount = 0
    total_paid_amount = 0
    total_outstanding_amount = 0

    for payment in payments:
        paid_date = "-"
        installment_late_fee = "-"
        paid_amount = "-"
        due_status = "N"
        if is_object:
            payment_number = payment.payment_number
            due_date = payment.due_date
            due_date_formated = format_date(payment.due_date, 'dd-MMM-YYYY', locale='id_ID')
            if hasattr(payment, 'paid_date'):
                paid_date = format_date(payment.paid_date, 'dd-MMM-YYYY', locale='id_ID')
            installment_principal = payment.installment_principal
            installment_interest = payment.installment_interest
            installment_late_fee = payment.late_fee_amount
            total_installment_amount = payment.installment_principal+payment.installment_interest + \
                                       payment.late_fee_amount

            outstanding = payment.due_amount
            paid_amount = payment.paid_amount
        else:
            payment_number = payment['payment_number']
            due_date = payment['due_date']
            due_date_formated = format_date(payment['due_date'], 'dd-MMM-YYYY', locale='id_ID')
            if 'paid_date' in payment:
                paid_date = format_date(payment['paid_date'], 'dd-MMM-YYYY', locale='id_ID')
            if 'principal_amount' in payment:
                installment_principal = payment['principal_amount']
                installment_interest = payment['interest_amount']
            else:
                installment_principal = payment['installment_principal']
                installment_interest = payment['installment_interest']
            if 'paid_amount' in payment:
                paid_amount = payment['paid_amount']
            if 'late_fee' in payment:
                installment_late_fee = payment['late_fee']

            total_installment_amount = installment_principal+installment_interest
            outstanding = payment['due_amount']


        if due_date < today:
            due_status = "Y"

        total_principal += installment_principal
        total_interest += installment_interest
        total_late_fee += 0 if installment_late_fee == '-' else installment_late_fee
        total_all_installment_amount += total_installment_amount
        total_paid_amount += 0 if paid_amount == '-' else paid_amount
        total_outstanding_amount += outstanding

        converted_payments.append(
            dict(
                payment_number=payment_number, due_date=due_date_formated, paid_date=paid_date, due_status=due_status,
                installment_principal=installment_principal,
                installment_interest=installment_interest,
                installment_late_fee=installment_late_fee, total_installment_amount=total_installment_amount,
                paid_amount=paid_amount, outstanding=outstanding,

            )
        )
    data_to_return['simulated_payments'] = converted_payments
    data_to_return['total_principal'] = int(total_principal)
    data_to_return['total_interest'] = int(total_interest)
    data_to_return['total_late_fee'] = total_late_fee
    data_to_return['total_all_installment_amount'] = int(total_all_installment_amount)
    data_to_return['total_paid_amount'] = total_paid_amount
    data_to_return['total_outstanding_amount'] = int(total_outstanding_amount)
    return data_to_return


def add_rupiah_separator_without_rp(amount):

    if not amount or amount == 0:
        return ''

    amount_str = str(int(amount))
    result = []

    for index, number in enumerate(reversed(amount_str)):
        if index != 0 and index % 3 == 0:
            result.append(',')

        result.append(number)

    result.reverse()
    result = "".join(result)

    return result


def get_after_refinancing_due_date(next_due_date, original_cycle_day,due_date_before=None):
    if not due_date_before:
        due_date_before = next_due_date - relativedelta(months=1)
    last_day = calendar.monthrange(next_due_date.year, next_due_date.month)[1]
    original_cycle_day = original_cycle_day if original_cycle_day <= last_day else last_day
    new_next_due_date = next_due_date.replace(day=original_cycle_day)
    return new_next_due_date if new_next_due_date - relativedelta(
        days=LoanRefinancingConst.LOAN_REFINANCING_DUE_DATE_MIN_DELTA_DAYS) >= due_date_before \
        else new_next_due_date + relativedelta(months=1)


def generate_status_and_tips_loan_refinancing_status(loan_refinancing_req, data):
    data['current_loan_refinancing_status'] = '-'
    data['offer_selected_label'] = '-'
    if loan_refinancing_req:
        data['current_loan_refinancing_status'] = loan_refinancing_req.status
        if loan_refinancing_req.status in (
                CovidRefinancingConst.STATUSES.offer_selected,
                CovidRefinancingConst.STATUSES.approved,
        ):
            data['offer_selected_label'] = CovidRefinancingConst.SELECTED_OFFER_LABELS[
                loan_refinancing_req.product_type
            ]

    if data['current_loan_refinancing_status'] not in CovidRefinancingConst.STATUSES_TIPS_LABEL:
        data['current_loan_refinancing_status'] = '-'

    data['tips'] = CovidRefinancingConst.STATUSES_TIPS_LABEL[
        data['current_loan_refinancing_status']
    ]

    if data['current_loan_refinancing_status'] == CovidRefinancingConst.STATUSES.activated:
        data['current_loan_refinancing_status'] = '-'

    return data


def convert_date_to_word(date):
    date_split = format_date(date, 'd MMMM yyyy', locale='id_ID').split(" ")
    return "%s %s %s" % (
        convert_number_to_word(date_split[0]), date_split[1],
        convert_number_to_word(date_split[2])
    )


def convert_number_to_word(number):
    number = int(number)
    word = ['nol', 'satu', 'dua', 'tiga', 'empat',
            'lima', 'enam', 'tujuh', 'delapan', 'sembilan']
    endwords = ['', 'puluh', 'ratus', 'ribu']

    if number > 9999:
        return

    if number < 10:
        return word[number]

    if number >= 11 and number <= 19:
        firstword = word[number % 10]
        if firstword == word[1]:
            firstword = 'se'
        return '%s%s%s' % (firstword, ' ' if firstword != 'se' else '', 'belas')

    wordindex = len(str(number)) - 1
    devider = 10 ** wordindex
    firstword = word[number // devider]
    if firstword == word[1]:
        firstword = 'se'

    endword = ''
    if number % devider > 0:
        endword = convert_number_to_word(number % devider)

    return '%s%s%s%s%s' % (firstword, ' ' if firstword != 'se' else '',
                           endwords[wordindex], ' ' if endword != '' else '', endword)


def get_partner_product(product_line_code):
    if product_line_code in ProductLineCodes.normal_product():
        return 'normal'
    elif product_line_code in ProductLineCodes.pede():
        return 'pede'
    elif product_line_code in ProductLineCodes.laku6():
        return 'laku6'
    elif product_line_code in ProductLineCodes.icare():
        return 'icare'
    return ''


def get_waiver_is_need_approvals(data, dpd=None):
    is_need_approval_tl = False
    is_need_approval_supervisor = False
    is_need_approval_colls_head = False
    is_need_approval_ops_head = False

    if not data['is_automated']:
        if (
            data['calculated_unpaid_waiver_percentage']
            > data['recommended_unpaid_waiver_percentage']
        ):
            is_need_approval_tl = True
            is_need_approval_supervisor = True
        if data['selected_program_name'] == 'r4':
            is_need_approval_tl = True
            is_need_approval_supervisor = True
            is_need_approval_colls_head = True
            is_need_approval_ops_head = True
        if data['selected_program_name'] == 'r6' and dpd and dpd <= 7:
            is_need_approval_tl = True
            is_need_approval_supervisor = True
            is_need_approval_colls_head = True

    return (
        is_need_approval_tl,
        is_need_approval_supervisor,
        is_need_approval_colls_head,
        is_need_approval_ops_head,
    )
