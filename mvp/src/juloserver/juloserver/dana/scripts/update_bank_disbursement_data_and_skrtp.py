import csv

from django.conf import settings

from bulk_update.helper import bulk_update

from juloserver.julo.models import Document
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.dana.tasks import generate_dana_loan_agreement, get_dana_loan_agreement_template
from juloserver.dana.onboarding.utils import decrypt_personal_information
from juloserver.dana.models import DanaLoanReference
from juloserver.dana.constants import DanaDisbursementMethod, DanaDocumentConstant
from juloserver.dana.loan.services import dana_generate_hashed_loan_xid


def update_bank_disbursement_data_and_skrtp(csv_file_path):
    with open(csv_file_path) as csv_file:
        loan_xids = set()
        partner_ref_nos = set()
        destination_account_info_dict = dict()
        reader = csv.DictReader(csv_file)

        for row in reader:
            partner_ref_nos.add(row["partnerReferenceNo"])
            encrypted_destination_account_info = row["disbursementDestinationInfo"]

            try:
                decrypt_destination_account_info = decrypt_personal_information(
                    encrypted_destination_account_info
                )
            except ValueError:
                continue

            if decrypt_destination_account_info:
                destination_account_info_dict[row["partnerReferenceNo"]] = {
                    "beneficiary_account_number": decrypt_destination_account_info.get(
                        "beneficiaryAccountNumber",
                    ),
                    "beneficiary_account_name": decrypt_destination_account_info.get(
                        "beneficiaryAccountName"
                    ),
                    "beneficiary_bank_code": decrypt_destination_account_info.get(
                        "beneficiaryBankCode"
                    ),
                    "beneficiary_bank_name": decrypt_destination_account_info.get(
                        "beneficiaryBankName"
                    ),
                }

        dana_loan_references = DanaLoanReference.objects.filter(
            partner_reference_no__in=partner_ref_nos
        ).select_related("loan", "loan__loan_status")

        for dlr in dana_loan_references:
            if dlr.loan.loan_status.status_code != LoanStatusCodes.CURRENT:
                msg = "skipping dlr.partner_reference_no: " + str(dlr.partner_reference_no)
                msg += " invalid loan status (" + str(dlr.loan.loan_status.status_code) + ")"
                print(msg)
                continue

            destination_account_info = destination_account_info_dict.get(dlr.partner_reference_no)

            if destination_account_info:
                loan_xids.add(dlr.loan.loan_xid)

                dlr.disbursement_method = DanaDisbursementMethod.BANK_ACCOUNT
                dlr.beneficiary_account_number = destination_account_info.get(
                    "beneficiary_account_number"
                )
                dlr.beneficiary_account_name = destination_account_info.get(
                    "beneficiary_account_name"
                )
                dlr.beneficiary_bank_code = destination_account_info.get("beneficiary_bank_code")
                dlr.beneficiary_bank_name = destination_account_info.get("beneficiary_bank_name")

        bulk_update(
            dana_loan_references,
            update_fields=[
                "disbursement_method",
                "beneficiary_account_number",
                "beneficiary_account_name",
                "beneficiary_bank_code",
                "beneficiary_bank_name",
            ],
            batch_size=500,
        )

        generate_new_skrtp_with_bank_info(loan_xids, dana_loan_references)


def generate_new_skrtp_with_bank_info(loan_xids, dana_loan_references):
    old_skrtp_documents = dict()

    documents = Document.objects.filter(
        loan_xid__in=loan_xids, document_type=DanaDocumentConstant.LOAN_AGREEMENT_TYPE
    )

    for doc in documents:
        old_skrtp_documents[doc.loan_xid] = doc

    old_skrtps = list()
    for dlr in dana_loan_references:
        old_skrtp = old_skrtp_documents.get(dlr.loan.loan_xid)

        if not old_skrtp:
            msg = "skipping dlr.partner_reference_no: " + str(dlr.partner_reference_no)
            msg += " has no skrtp in loan status " + str(dlr.loan.loan_status.status_code)
            print(msg)
            continue

        old_skrtp.document_type = "old_" + DanaDocumentConstant.LOAN_AGREEMENT_TYPE

        old_skrtps.append(old_skrtp)

        content = get_dana_loan_agreement_template(dlr.loan, True, only_content=True)

        generate_dana_loan_agreement(dlr.application_id, dlr.loan.id, content)

        hashed_loan_xid = dana_generate_hashed_loan_xid(dlr.loan.loan_xid)
        loan_agreement_url = "{}/{}/{}".format(
            settings.BASE_URL, "v1.0/agreement/content", hashed_loan_xid
        )

        msg = "loan_agreement_url: " + loan_agreement_url
        msg += ", dlr.reference_no: " + str(dlr.reference_no)
        msg += ", dlr.partner_reference_no: " + str(dlr.partner_reference_no)
        print(msg)

    bulk_update(
        old_skrtps,
        update_fields=[
            "document_type",
        ],
        batch_size=500,
    )
