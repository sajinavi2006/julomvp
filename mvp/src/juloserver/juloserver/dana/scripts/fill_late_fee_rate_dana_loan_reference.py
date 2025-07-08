from django_bulk_update.helper import bulk_update
from juloserver.dana.models import DanaLoanReference
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def fill_late_fee_rate_dana_loan_reference(limiter: int) -> None:

    dana_loan_references = DanaLoanReference.objects.filter(late_fee_rate__isnull=True)

    feature_dana_late_fee = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_LATE_FEE,
    ).last()
    late_fee_rate = feature_dana_late_fee.parameters.get('late_fee') * 100

    loan_reference_update = []
    counter = 0

    for dana_loan_reference in dana_loan_references.iterator():
        counter += 1
        dana_loan_reference.late_fee_rate = late_fee_rate
        loan_reference_update.append(dana_loan_reference)
        print('Row {}, Process Dana Loan Reference ID: {}'.format(counter, dana_loan_reference.id))
        if len(loan_reference_update) == limiter:
            bulk_update(
                loan_reference_update, update_fields=['late_fee_rate', 'udate'], batch_size=limiter
            )
            loan_reference_update = []
            print("success update existing {} Dana Loan Reference".format(limiter))

    try:
        bulk_update(loan_reference_update)
        print("---------finish update existing Dana Loan Reference---------")
    except Exception as err:
        print("error when bulk_update Dana Loan Reference with error {}".format(str(err)))
