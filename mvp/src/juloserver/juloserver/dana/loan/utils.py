import math
import re
import calendar
from datetime import datetime
from typing import Dict, List

from dateutil.relativedelta import relativedelta
from django.conf import settings

from juloserver.dana.loan.services import dana_generate_hashed_loan_xid
from juloserver.dana.models import DanaLoanReference
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import (
    FeatureSetting,
    ProductLookup,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.utils import generate_product_name


def create_redis_key_for_payment_api(request_data: Dict) -> str:
    additional_info = request_data["additionalInfo"]
    bill_detail_list = additional_info["billDetailList"]
    sorted_bills = sorted(bill_detail_list, key=lambda d: d["billId"])
    bill_key = []
    for bill in sorted_bills:
        bill_key.append(
            "{}+{}+{}+{}".format(
                bill["billId"],
                bill["principalAmount"]["value"],
                bill["interestFeeAmount"]["value"],
                bill["totalAmount"]["value"],
            )
        )
    partner_reference_no = request_data["partnerReferenceNo"]
    customer_id = additional_info.get("customerId")
    amount = request_data["amount"]["value"]
    credit_usage_mutation = additional_info["creditUsageMutation"]["value"]
    key = "{}+{}+{}+{}+{}".format(
        partner_reference_no, customer_id, str(bill_key), amount, credit_usage_mutation
    )
    return key


def get_dana_loan_agreement_url(dana_loan_reference: DanaLoanReference) -> str:
    hashed_loan_xid = dana_generate_hashed_loan_xid(dana_loan_reference.id)  # noqa: F821
    loan_agreement_url = "{}/{}/{}".format(
        settings.BASE_URL, "v1.0/agreement/content", hashed_loan_xid
    )
    return loan_agreement_url


def dana_filter_search_field(keyword):
    from django.core.validators import ValidationError, validate_email
    from django.db.models import Max

    from juloserver.account.models import Account

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if keyword.isdigit():
        account_id_max = Account.objects.aggregate(Max('id'))['id__max']

        if len(keyword) == 2 and int(keyword) == ProductLineCodes.DANA:
            return 'product_line_id', [int(keyword)]
        elif len(keyword) == 10 and keyword[:1] == '2':
            return 'id', keyword
        elif int(keyword) in range(1, account_id_max + 1):
            return 'account_id', [int(keyword)]
        else:
            mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
            if mobile_phone_regex.match(keyword):
                return 'dana_customer_data__mobile_number', keyword
            else:
                return 'dana_customer_data__nik', keyword
    else:
        try:
            validate_email(keyword)
            return 'email', keyword
        except ValidationError:
            return 'fullname', keyword


def create_dana_bill_detail(
    loan_amount: int,
    loan_amount_with_interest: int,
    reference_no: str,
    repayment_plan_list: List,
) -> List:

    bill_details = []
    tenure = len(repayment_plan_list)
    principal_amount = loan_amount / tenure
    interest_amount = (loan_amount_with_interest / tenure) - principal_amount
    total_amount = principal_amount + interest_amount

    principal_amount = str(math.ceil(principal_amount))
    interest_amount = str(math.ceil(interest_amount))
    total_amount = str(math.ceil(total_amount))
    for idx, repayment_plan in enumerate(repayment_plan_list):
        index = str(idx + 1)

        due_date = repayment_plan.get("dueDate")
        bill_detail = {
            "billId": reference_no + '000' + index,
            "periodNo": index,
            "dueDate": due_date,
            "principalAmount": {"currency": "IDR", "value": principal_amount},
            "interestFeeAmount": {"currency": "IDR", "value": interest_amount},
            "lateFeeAmount": {"currency": "IDR", "value": "0.00"},
            "totalAmount": {"currency": "IDR", "value": total_amount},
            "paidPrincipalAmount": {"currency": "IDR", "value": "0.00"},
            "paidInterestFeeAmount": {"currency": "IDR", "value": "0.00"},
            "paidLateFeeAmount": {"currency": "IDR", "value": "0.00"},
            "totalPaidAmount": {"currency": "IDR", "value": "0.00"},
        }
        bill_details.append(bill_detail)

    return bill_details


def create_dana_bill_detail_cash_loan(
    transaction_datetime: datetime,
    loan_amount: int,
    reference_no: str,
    tenure: int,
) -> List:

    feature_setting = FeatureSetting.objects.get_or_none(
        is_active=True, feature_name=FeatureNameConst.DANA_CASH_LOAN
    )

    cdate = transaction_datetime
    cut_off_date = feature_setting.parameters.get('cut_off_date')
    first_due_date = feature_setting.parameters.get('first_due_date')

    if cdate.day <= cut_off_date:
        if cut_off_date > first_due_date:
            cdate += relativedelta(months=1)
        max_date = calendar.monthrange(cdate.year, cdate.month)[1]
        if first_due_date > max_date:
            first_repayment_date = cdate.replace(day=max_date)
        else:
            first_repayment_date = cdate.replace(day=first_due_date)
    else:
        if cut_off_date > first_due_date:
            cdate += relativedelta(months=1)
        cdate += relativedelta(months=1)
        max_date = calendar.monthrange(cdate.year, cdate.month)[1]
        if first_due_date > max_date:
            first_repayment_date = cdate.replace(day=max_date)
        else:
            first_repayment_date = cdate.replace(day=first_due_date)

    current_repayment_date = first_repayment_date

    interest_rate = (
        ProductLookup.objects.filter(product_line=ProductLineCodes.DANA_CASH_LOAN)
        .values_list('interest_rate', flat=True)
        .last()
    )
    monthly_interest_rate = round(interest_rate / 12, 4)
    monthly_principal_amount = math.floor(loan_amount / tenure)
    monthly_interest_amount = math.ceil(loan_amount * monthly_interest_rate)

    remaining_principal = loan_amount - (monthly_principal_amount * tenure)
    adjust_principal = tenure - remaining_principal

    bill_details = []
    for i in range(1, (tenure + 1)):
        monthly_principal_installment = monthly_principal_amount
        if i > adjust_principal:
            monthly_principal_installment += 1
        monthly_total_amount = monthly_principal_installment + monthly_interest_amount

        index = str(i)
        bill_detail = {
            "billId": reference_no + '000' + index,
            "periodNo": index,
            "dueDate": current_repayment_date.strftime("%Y%m%d"),
            "principalAmount": {"currency": "IDR", "value": monthly_principal_installment},
            "interestFeeAmount": {"currency": "IDR", "value": monthly_interest_amount},
            "lateFeeAmount": {"currency": "IDR", "value": "0.00"},
            "totalAmount": {"currency": "IDR", "value": monthly_total_amount},
            "paidPrincipalAmount": {"currency": "IDR", "value": "0.00"},
            "paidInterestFeeAmount": {"currency": "IDR", "value": "0.00"},
            "paidLateFeeAmount": {"currency": "IDR", "value": "0.00"},
            "totalPaidAmount": {"currency": "IDR", "value": "0.00"},
        }
        bill_details.append(bill_detail)

        current_repayment_date += relativedelta(months=1)
        max_date = calendar.monthrange(
            current_repayment_date.year,
            current_repayment_date.month,
        )[1]

        if first_due_date > max_date:
            current_repayment_date = current_repayment_date.replace(
                day=max_date,
            )
        else:
            current_repayment_date = current_repayment_date.replace(
                day=first_due_date,
            )

    return bill_details


def round_decimals_down(number: float, decimals: int = 2) -> float:
    """
    Returns a value rounded down to a specific number of decimal places.
    """
    if not isinstance(decimals, int):
        raise TypeError("decimal places must be an integer")
    elif decimals < 0:
        raise ValueError("decimal places has to be 0 or more")
    elif decimals == 0:
        return math.floor(number)

    factor = 10**decimals
    return math.floor(number * factor) / factor


def calculate_dana_interest_rate(loan_amount: float, loan_amount_with_interest: float) -> float:
    interest_rate = (loan_amount_with_interest / loan_amount) - 1
    return round_decimals_down(interest_rate, 3)


def generate_dana_product_name(interest_rate: float, late_fee_rate: float):
    params_product_name = {
        "interest_value": interest_rate,
        "origination_value": 0.00,
        "late_fee_value": late_fee_rate,
        "cashback_initial_value": 0.00,
        "cashback_payment_value": 0.00,
    }
    return generate_product_name(params_product_name)
