from __future__ import division
from builtins import str
from past.utils import old_div
from .account_related import get_is_covid_risky

from juloserver.julo.exceptions import JuloException
from juloserver.account_payment.models import AccountPayment
from juloserver.loan_refinancing.models import (
    LoanRefinancingOffer,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.utils import get_partner_product


def generate_j1_waiver_default_offer(loan_refinancing_request, bucket, product_type):
    account = loan_refinancing_request.account
    account_payments = AccountPayment.objects.filter(
        account=account).not_paid_active().order_by('due_date')
    account_payment = account_payments.first()

    remaining_late_fee = account_payment.remaining_late_fee
    remaining_interest = account_payment.remaining_interest
    remaining_principal = account_payment.remaining_principal
    total_unpaid = remaining_late_fee + remaining_interest + remaining_principal

    product_line_code = account.application_set.last().product_line_code
    product_line_name = get_partner_product(product_line_code)

    principal_recommended_waiver_percent = 0
    interest_recommended_waiver_percent = 0
    is_covid_risky = get_is_covid_risky(account)
    if product_type == CovidRefinancingConst.PRODUCTS.r4:
        principal_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'principal_waiver',
                is_covid_risky, product_line_name
            )
        ]

    r4_and_r6 = (CovidRefinancingConst.PRODUCTS.r4, CovidRefinancingConst.PRODUCTS.r6)
    if product_type in r4_and_r6:
        interest_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'interest_fee_waiver',
                is_covid_risky, product_line_name
            )
        ]

    late_fee_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
        '{}_{}_{}_{}_{}'.format(
            product_type, bucket, 'late_fee_waiver',
            is_covid_risky, product_line_name
        )
    ]

    default_bucket_params = CovidRefinancingConst.BUCKET_BASED_DEFAULT_PARAMS[product_type]
    validity_in_days = default_bucket_params[bucket]['validity_in_days']
    total_latefee_discount = py2round(
        old_div(float(late_fee_recommended_waiver_percent) * remaining_late_fee, 100)
    )
    total_interest_discount = py2round(
        old_div(float(interest_recommended_waiver_percent) * remaining_interest, 100)
    )
    total_principal_discount = py2round(
        old_div(float(principal_recommended_waiver_percent) * remaining_principal, 100)
    )
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        product_type=product_type,
        prerequisite_amount=total_unpaid - total_discount,
        total_latefee_discount=total_latefee_discount,
        total_interest_discount=total_interest_discount,
        total_principal_discount=total_principal_discount,
        validity_in_days=validity_in_days,
        interest_discount_percentage=str(interest_recommended_waiver_percent) + '%',
        principal_discount_percentage=str(principal_recommended_waiver_percent) + '%',
        latefee_discount_percentage=str(late_fee_recommended_waiver_percent) + '%',
    )


def get_r4_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_j1_waiver_default_offer(loan_refinancing_request, bucket, "R4")


def get_r5_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_j1_waiver_default_offer(loan_refinancing_request, bucket, "R5")


def get_r6_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_j1_waiver_default_offer(loan_refinancing_request, bucket, "R6")


def get_offer_constructor_function(product_type):
    offer_function = {
        'R4': get_r4_default_loan_refinancing_offer,
        'R5': get_r5_default_loan_refinancing_offer,
        'R6': get_r6_default_loan_refinancing_offer,
    }
    return offer_function[product_type]


def generated_j1_default_offers(
        loan_refinancing_request, refinancing_products, is_proactive_offer=False):
    if not refinancing_products:
        return False

    default_offers = []
    account_payment = AccountPayment.objects.filter(
        account=loan_refinancing_request.account).normal().not_paid_active()\
        .order_by('due_amount').first()
    if not account_payment:
        raise JuloException("tidak dapat diproses. pinjaman belum aktif")
    bucket_number = loan_refinancing_request.account.bucket_number
    refinancing_product = refinancing_products.split(',')
    refinancing_product = list([_f for _f in refinancing_product if _f])
    LoanRefinancingOffer.objects.filter(
        loan_refinancing_request__account=loan_refinancing_request.account
    ).update(is_latest=False)
    recommendation_order = 1
    for product in refinancing_product:
        offer_constructor = get_offer_constructor_function(product)
        offer_dict = offer_constructor(loan_refinancing_request, bucket_number)
        offer_dict['is_latest'] = True
        offer_dict['recommendation_order'] = recommendation_order
        offer_dict['is_proactive_offer'] = is_proactive_offer
        default_offers.append(LoanRefinancingOffer(**offer_dict))
        recommendation_order = recommendation_order + 1
    LoanRefinancingOffer.objects.bulk_create(default_offers)
    return True
