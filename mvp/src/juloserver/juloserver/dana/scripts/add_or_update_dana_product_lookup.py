from bulk_update.helper import bulk_update

from juloserver.dana.loan.services import create_product_lookup_for_dana
from juloserver.dana.loan.utils import calculate_dana_interest_rate
from juloserver.dana.models import DanaLoanReference


def add_or_update_product_lookup_for_dana():
    dana_loan_references = DanaLoanReference.objects.all()
    updated_dana_loan_references = []
    updated_loan = []
    for dana_loan_reference in dana_loan_references.iterator(chunk_size=1000):
        if not dana_loan_reference.interest_rate:
            dana_loan_reference.interest_rate = calculate_dana_interest_rate(
                dana_loan_reference.original_order_amount,
                dana_loan_reference.credit_usage_mutation,
            )
            updated_dana_loan_references.append(dana_loan_reference)

        loan = dana_loan_reference.loan
        product_lookup = loan.product
        yearly_interest_rate = ((dana_loan_reference.interest_rate * 30) * 12) / 100
        if product_lookup.interest_rate == yearly_interest_rate:
            print("{} loan already have the correct product".format(dana_loan_reference.id))
            continue

        if not dana_loan_reference.late_fee_rate:
            print("{} not have late_fee_rate".format(dana_loan_reference.id))
            continue

        new_product_lookup = create_product_lookup_for_dana(
            yearly_interest_rate,
            dana_loan_reference.late_fee_rate,
            product_lookup.product_line,
        )
        loan.product = new_product_lookup
        updated_loan.append(loan)
        print("{} dlr loan.product updated".format)

    bulk_update(updated_dana_loan_references, batch_size=500)
    bulk_update(updated_loan, batch_size=500)
