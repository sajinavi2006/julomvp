from django_bulk_update.helper import bulk_update

from juloserver.dana.models import DanaLoanReference


def fill_dana_sphp_accepted_ts_loan(limit: int = 500):
    empty_trans_time = []
    updated_sphp_accepted_ts_loan = []
    dana_loan_references = DanaLoanReference.objects.filter(
        loan__sphp_accepted_ts__isnull=True, loan__sphp_sent_ts__isnull=True
    ).select_related("loan")

    counter = 0
    for dana_loan_reference in dana_loan_references.iterator():
        counter += 1
        loan = dana_loan_reference.loan
        print("{} - Update Loan ID {}".format(counter, loan.id))

        if not dana_loan_reference.trans_time:
            empty_trans_time.append(loan.id)

        trans_time = dana_loan_reference.trans_time
        loan.sphp_accepted_ts = trans_time
        loan.sphp_sent_ts = trans_time
        updated_sphp_accepted_ts_loan.append(loan)

        if len(updated_sphp_accepted_ts_loan) == limit:
            bulk_update(
                updated_sphp_accepted_ts_loan,
                update_fields=['sphp_accepted_ts', 'sphp_sent_ts'],
                batch_size=limit + 1,
            )
            updated_sphp_accepted_ts_loan = []

    bulk_update(
        updated_sphp_accepted_ts_loan,
        update_fields=['sphp_accepted_ts', 'sphp_sent_ts'],
    )
    print("Done updating")
    print("Loan without trans time: ")
    for loan_id in empty_trans_time:
        print(loan_id)
