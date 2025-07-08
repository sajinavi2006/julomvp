from juloserver.dana.models import DanaLoanReference
from django_bulk_update.helper import bulk_update


def update_dana_loan_reference_late_fee_rate(
    start_date, end_date, correct_value: float = 0.27, batch_size: int = 100
):
    print("Fetching DanaLoanReference...")
    dana_loan_references = DanaLoanReference.objects.filter(
        cdate__range=(start_date, end_date)
    ).exclude(late_fee_rate=correct_value)
    print("Got {} DanaLoanReference".format(len(dana_loan_references)))

    dana_loan_reference_update_list = []

    for dana_loan_reference in dana_loan_references.iterator():
        dana_loan_reference.late_fee_rate = correct_value
        dana_loan_reference_update_list.append(dana_loan_reference)

        if len(dana_loan_reference_update_list) == batch_size:
            print("Updating with batch_size {}...".format(batch_size))
            bulk_update(
                dana_loan_reference_update_list,
                update_fields=['late_fee_rate'],
                batch_size=batch_size,
            )
            dana_loan_reference_update_list = []
            print("Success update {} DanaLoanReference".format(batch_size))

    if dana_loan_reference_update_list:
        print("Updating the rest {} data...".format(len(dana_loan_reference_update_list)))
        bulk_update(
            dana_loan_reference_update_list,
            update_fields=['late_fee_rate'],
            batch_size=batch_size,
        )
        print("Success update {} DanaLoanReference".format(len(dana_loan_reference_update_list)))
    else:
        print("No update -> all data already correct")
    print("---------Finish update DanaLoanReference---------")
