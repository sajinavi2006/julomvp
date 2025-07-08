import csv

from django_bulk_update.helper import bulk_update

from juloserver.dana.models import DanaLoanReference


def fix_null_order_original_amount(file_path: str):
    with open(file_path) as csv_file:
        reader = csv.DictReader(csv_file)
        counter = 0
        partner_reference_no_list = []
        original_amount_dict = {}
        updated_dlrs = []
        for row in reader:
            counter += 1
            if not row["partnerReferenceNo"] or row["partnerReferenceNo"] == "":
                print("row {} has no partnerReferenceNo".format(counter))
                continue

            if not row["originalOrderAmount"] or row["originalOrderAmount"] == "":
                print(
                    "partnerReferenceNo: {} has no originalOrderAmount".format(
                        row["partnerReferenceNo"]
                    )
                )
                continue

            partner_reference_no_list.append(row["partnerReferenceNo"])
            original_amount_dict[row["partnerReferenceNo"]] = float(row["originalOrderAmount"])

        dana_loan_references = DanaLoanReference.objects.filter(
            partner_reference_no__in=partner_reference_no_list
        )

        for dana_loan_reference in dana_loan_references.iterator():
            if dana_loan_reference.original_order_amount is None:
                dana_loan_reference.original_order_amount = original_amount_dict[
                    dana_loan_reference.partner_reference_no
                ]
                updated_dlrs.append(dana_loan_reference)

        bulk_update(
            updated_dlrs, update_fields=['original_order_amount'], batch_size=100
        )

        print("Success update originalOrderAmount")
