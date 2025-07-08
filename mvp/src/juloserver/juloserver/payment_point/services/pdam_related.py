from datetime import datetime
from django.db.models import Q

from juloserver.julo.models import SepulsaProduct
from juloserver.payment_point.constants import SepulsaProductType
from juloserver.payment_point.services.sepulsa import SepulsaLoanService


def get_pdam_operator(q=None):
    operator_list = []
    operators = SepulsaProduct.objects.filter(
        is_not_blocked=True, is_active=True, type=SepulsaProductType.PDAM
    ).order_by('product_name')

    if q:
        operators = SepulsaProduct.objects.filter(
            Q(product_desc__icontains=q) | Q(product_name__icontains=q),
            is_not_blocked=True, is_active=True, type=SepulsaProductType.PDAM
        )
    if operators:
        for operator in operators:
            operator_list.append({
                "code": operator.product_desc,
                "description": operator.product_name,
                "enabled": operator.is_active,
            })
        return operator_list, None

    if not operators:
        return [], "Operator not found"

    return operators, None


def get_pdam_bill_information(data, sepulsa_product):
    api_response, error = SepulsaLoanService().inquire_pdam(data)
    if error:
        return api_response, error
    elif api_response['status'] is False:
        return api_response, error

    bills = []
    for bill in api_response['bills']:
        sepulsa_total_fee = bill['total_fee'] if bill['total_fee'] else 0
        sepulsa_bill_penalty = 0
        for penalty in bill['penalty']:
            if penalty:
                sepulsa_bill_penalty += int(penalty)

        sepulsa_waterusage_bill = bill['waterusage_bill'] if bill['waterusage_bill'] else "0"
        sepulsa_bill_amount = 0
        for bill_amount in bill['bill_amount']:
            sepulsa_bill_amount += int(bill_amount)

        bills.append({
            "info_text": bill['info_text'],
            "due_date": datetime.strptime(bill['bill_date'][0], '%Y%m').strftime('%Y-%m'),
            "totals_bill": sepulsa_bill_amount,
            "waterusage_bill": sepulsa_waterusage_bill,
            "total_fee": int(sepulsa_total_fee),
            "penalty": sepulsa_bill_penalty
        })

    api_response_amount = api_response['amount'] if api_response['amount'] else 0
    sepulsa_product_admin_fee = sepulsa_product.admin_fee if sepulsa_product.admin_fee else 0
    sepulsa_total_bills = int(api_response_amount)

    response_data = dict(
        admin_fee=sepulsa_product_admin_fee,
        customer_name=api_response['name'],
        total_bills=sepulsa_total_bills,
        product_id=sepulsa_product.id,
        bills=bills
    )
    if not bills:
        return [], "Bill not found"

    return response_data, None
