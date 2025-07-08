import io
import csv
import os
import logging
import uuid

from datetime import datetime
from typing import List, Dict, Tuple
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from collections import defaultdict

from juloserver.dana.constants import (
    BILL_STATUS_PAID_OFF,
    DanaProductType,
)
from juloserver.dana.constants import DanaReferenceStatus
from juloserver.dana.constants import PaymentReferenceStatus
from juloserver.dana.models import DanaLoanReferenceStatus
from juloserver.dana.models import (
    DanaPaymentBill,
    DanaLoanReference,
)
from juloserver.dana.loan.crm.services import (
    upload_csv_data_to_oss,
)
from juloserver.dana.models import DanaRefundReference
from juloserver.dana.models import DanaRefundTransaction
from juloserver.dana.models import DanaRefundedBill
from juloserver.dana.models import DanaRepaymentReference

from juloserver.dana.refund.crm.serializers import DanaRefundSettlementSerializer
from juloserver.dana.repayment.services import create_manual_repayment_settlement

from juloserver.julo.models import (
    Payment,
    UploadAsyncState,
)

from juloserver.fdc.files import TempDir

logger = logging.getLogger(__name__)

DANA_REFUND_SETTLEMENT_HEADER = [
    "is_inserted",
    "is_valid",
    "is_changed",
    "customerId",
    "partnerId",
    "lenderProductId",
    "partnerReferenceNo",
    "txnType",
    "amount",
    "status",
    "billId",
    "dueDate",
    "periodNo",
    "creditUsageMutation",
    "principalAmount",
    "interestFeeAmount",
    "lateFeeAmount",
    "totalAmount",
    "paidPrincipalAmount",
    "paidInterestFeeAmount",
    "paidLateFeeAmount",
    "totalPaidAmount",
    "originalPartnerReferenceNo",
    "isPartialRefund",
    "originalOrderAmount",
    "transTime",
    "failCode",
    "note",
]


def write_row_result(
    row: Dict, is_inserted: bool, is_valid: bool, is_changed: bool = False
) -> List:
    return [
        is_inserted,
        is_valid,
        is_changed,
        row.get('customerId', 'null'),
        row.get('partnerId', 'null'),
        row.get('lenderProductId', 'null'),
        row.get('partnerReferenceNo', 'null'),
        row.get('txnType', 'null'),
        row.get('amount', 'null'),
        row.get('status', 'null'),
        row.get('billId', 'null'),
        row.get('dueDate', 'null'),
        row.get('periodNo', 'null'),
        row.get('creditUsageMutation', 'null'),
        row.get('principalAmount', 'null'),
        row.get('interestFeeAmount', 'null'),
        row.get('lateFeeAmount', 'null'),
        row.get('totalAmount', 'null'),
        row.get('paidPrincipalAmount', 'null'),
        row.get('paidInterestFeeAmount', 'null'),
        row.get('paidLateFeeAmount', 'null'),
        row.get('totalPaidAmount', 'null'),
        row.get('originalPartnerReferenceNo', 'null'),
        row.get('isPartialRefund', 'null'),
        row.get('originalOrderAmount', 'null'),
        row.get('transTime', 'null'),
        row.get('failCode', 'null'),
        row.get('note', 'null'),
    ]


def process_dana_refund_payment_settlement_result(upload_async_state: UploadAsyncState):
    fn_name = "process_dana_refund_payment_settlement_result"
    logger.info(
        {"action": fn_name, "upload_async_state_id": upload_async_state.id, "status": "STARTED"}
    )
    # Read the uploaded file and prepare for CSV processing
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path

    # Create a temporary directory for processing
    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        success_note = "Success with originalPartnerReferenceNo: {}"
        checked_bill_ids = {}  # To track unique billIds per originalPartnerReferenceNo

        # Initialize a default dict to store bill data by originalPartnerReferenceNo
        bill_notes = defaultdict(lambda: {"is_inserted": False, "is_valid": False, "bill_data": []})

        row_count = 0  # Counter for processed rows
        for row in reader:
            row_count += 1
            # Log every 10 rows processed
            if row_count % 10 == 0:
                logger.info(
                    {
                        "action": fn_name,
                        "upload_async_state_id": upload_async_state.id,
                        "processed_rows": row_count,
                        "status": "PROCESSING {} rows data".format(row_count),
                    }
                )

            # Validate row data
            validation_errors = set()

            if row["failCode"] and row["failCode"] != 'null':
                validation_errors.add(
                    "have failCode: {} but status not failed".format(row["failCode"])
                )

            serializer = DanaRefundSettlementSerializer(data=row)
            error_validation = serializer.validate()

            if error_validation:
                # If validation errors exist, mark the row as invalid and write error notes
                validation_errors.update(error_validation)

            original_partner_reference = row["originalPartnerReferenceNo"]

            # Check if billId is the same as in other rows for the same originalPartnerReferenceNo
            if row["billId"] in checked_bill_ids.get(original_partner_reference, set()):
                validation_errors.add(
                    "billId {} cannot be the same with other billIds "
                    "for originalPartnerReferenceNo {}".format(
                        row["billId"], original_partner_reference
                    )
                )

            checked_bill_ids.setdefault(original_partner_reference, set()).add(row["billId"])

            if validation_errors:
                # If validation errors exist, mark the row as invalid and write error notes
                row["note"] = ", ".join(validation_errors)
                row["is_valid"] = False
            else:
                row["note"] = ""  # Clear any existing note
                row["is_valid"] = True

            # Data is valid, continue processing
            validated_data = serializer.data

            # Add the data to the defaultdict based on originalPartnerReferenceNo
            bill_notes[original_partner_reference]["bill_data"].append(validated_data)

        for original_partner_reference, data in bill_notes.items():
            lender_product_ids = set(bill["lenderProductId"] for bill in data.get("bill_data", []))
            if DanaProductType.CICIL in lender_product_ids and all(
                bill["is_valid"] for bill in data.get("bill_data", [])
            ):
                try:
                    logger.info(
                        {
                            "action": fn_name,
                            "upload_async_state_id": upload_async_state.id,
                            "product_type": DanaProductType.CICIL,
                            "status": "PROCESSING process_refund_payment_data",
                        }
                    )
                    err, ref_no, is_successful = process_refund_payment_data(
                        bill_notes[original_partner_reference]["bill_data"]
                    )
                    if err:
                        # Error during refund payment, mark the bills as invalid
                        error_message = err
                        is_success_all = is_successful
                        for bill in bill_notes[original_partner_reference]["bill_data"]:
                            bill["note"] = error_message
                            bill["is_inserted"] = False
                            bill["is_valid"] = False

                    else:
                        # Refund payment success, mark the bills as valid
                        note = success_note.format(str(ref_no))
                        is_success_all = True
                        for bill in bill_notes[original_partner_reference]["bill_data"]:
                            bill["note"] = note
                            bill["is_inserted"] = True
                            bill["is_valid"] = True

                    logger.info(
                        {
                            "action": fn_name,
                            "upload_async_state_id": upload_async_state.id,
                            "product_type": DanaProductType.CICIL,
                            "status": "FINISHED process_refund_payment_data",
                        }
                    )
                except Exception as e:
                    # Error during refund payment, mark the bills as invalid
                    try:
                        error_message = str(e)
                    except TypeError:
                        error_message = str(e.detail["additionalInfo"])
                    for bill in bill_notes[original_partner_reference]["bill_data"]:
                        bill["note"] = error_message
                        bill["is_inserted"] = False
                        bill["is_valid"] = True

            if DanaProductType.CASH_LOAN in lender_product_ids and all(
                bill["is_valid"] for bill in data.get("bill_data", [])
            ):
                try:
                    logger.info(
                        {
                            "action": fn_name,
                            "upload_async_state_id": upload_async_state.id,
                            "product_type": DanaProductType.CASH_LOAN,
                            "status": "PROCESSING process_refund_payment_data",
                        }
                    )
                    err, ref_no, is_successful = process_refund_payment_data(
                        bill_notes[original_partner_reference]["bill_data"]
                    )
                    if err:
                        # Error during refund payment, mark the bills as invalid
                        error_message = err
                        is_success_all = is_successful
                        for bill in bill_notes[original_partner_reference]["bill_data"]:
                            bill["note"] = error_message
                            bill["is_inserted"] = False
                            bill["is_valid"] = False

                    else:
                        # Refund payment success, mark the bills as valid
                        note = success_note.format(str(ref_no))
                        is_success_all = True
                        for bill in bill_notes[original_partner_reference]["bill_data"]:
                            bill["note"] = note
                            bill["is_inserted"] = True
                            bill["is_valid"] = True

                    logger.info(
                        {
                            "action": fn_name,
                            "upload_async_state_id": upload_async_state.id,
                            "product_type": DanaProductType.CASH_LOAN,
                            "status": "FINISHED process_refund_payment_data",
                        }
                    )
                except Exception as e:
                    # Error during refund payment, mark the bills as invalid
                    try:
                        error_message = str(e)
                    except TypeError:
                        error_message = str(e.detail["additionalInfo"])
                    for bill in bill_notes[original_partner_reference]["bill_data"]:
                        bill["note"] = error_message
                        bill["is_inserted"] = False
                        bill["is_valid"] = True

        logger.info(
            {
                "action": fn_name,
                "upload_async_state_id": upload_async_state.id,
                "status": "FINISHED all process refund payment",
            }
        )

        # Iterate over the default dict and write all rows to the result, including invalid ones
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(DANA_REFUND_SETTLEMENT_HEADER)

            # Set note to remaining is_valid bills data on invalid original_partner_reference
            for original_partner_reference, data in bill_notes.items():
                if any(not bill["is_valid"] for bill in data.get("bill_data", [])):
                    is_success_all = False  # Set is_success_all to False if any bill is invalid
                    for bill in data.get("bill_data", []):
                        if bill["is_valid"]:
                            bill["note"] = (
                                "one of the billId "
                                "with originalPartnerReferenceNo : {} is invalid"
                            ).format(bill["originalPartnerReferenceNo"])

                # Write all rows to the result, including invalid ones
                for bill in data.get("bill_data", []):
                    is_inserted = bill.get("is_inserted", False)
                    is_valid = bill.get("is_valid")
                    row_result = write_row_result(bill, is_inserted=is_inserted, is_valid=is_valid)
                    write.writerow(row_result)

        logger.info(
            {
                "action": fn_name,
                "upload_async_state_id": upload_async_state.id,
                "status": "PROCESSING upload_csv_data_to_oss",
            }
        )
        # Upload the processed CSV data to OSS
        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
        logger.info(
            {
                "action": fn_name,
                "upload_async_state_id": upload_async_state.id,
                "status": "FINISHED upload_csv_data_to_oss",
            }
        )

    logger.info(
        {"action": fn_name, "upload_async_state_id": upload_async_state.id, "status": "FINISHED"}
    )
    return is_success_all


def process_refund_payment_data(bill_data: List[Dict]) -> Tuple[str, str, bool]:
    fn_name = "process_refund_payment_data"
    logger.info({"action": fn_name, "status": "STARTED"})
    try:
        with transaction.atomic():
            refund_no = str(uuid.uuid4())
            partner_reference_no = bill_data[0]['partnerReferenceNo']
            original_partner_reference_no = bill_data[0]['originalPartnerReferenceNo']
            customer_id = bill_data[0]['customerId']

            # get dana_repayment_reference data
            bill_list = [bill['billId'] for bill in bill_data]

            # Additional validation for customerId uniqueness
            unique_customer_ids = set(bill['customerId'] for bill in bill_data)
            if len(unique_customer_ids) > 1:
                error_message = (
                    "customerId with originalPartnerReferenceNo : {} cannot be different"
                ).format(original_partner_reference_no)
                return error_message, original_partner_reference_no, False

            # Check if all requested billIds have been requested as a loan
            dana_payment_matching_bill = DanaPaymentBill.objects.filter(bill_id__in=bill_list)
            matching_bill_ids = set(dana_payment_matching_bill.values_list('bill_id', flat=True))

            if set(bill_list) != matching_bill_ids:
                missing_bill_ids = list(set(bill_list) - matching_bill_ids)
                error_message = (
                    "Some of billId you requested have never been requested as a loan. "
                    "The billId(s): {}".format(', '.join(missing_bill_ids))
                )
                return error_message, original_partner_reference_no, False

            # validate bill based on original_partner_reference_no
            org_part_ref_no = original_partner_reference_no
            payments = Payment.objects.select_related('loan').filter(
                loan__danaloanreference__partner_reference_no=org_part_ref_no,
                loan__danaloanreference__customer_id=customer_id,
            )
            payment_ids = payments.values_list('id', flat=True)
            bill_ids = DanaPaymentBill.objects.filter(
                payment_id__in=set(payment_ids),
                bill_id__in=bill_list,
            ).values_list('bill_id', flat=True)
            if set(bill_ids) != set(bill_list) or not bill_ids:
                error_message = (
                    "This originalPartnerReferenceNo '{}' "
                    "not match with billId and/or customerId."
                ).format(original_partner_reference_no)
                return error_message, original_partner_reference_no, False

            # revalidate total billIds requested with actual count billIds -> for DACAL
            if len(bill_list) != len(payments):
                error_message = (
                    "This originalPartnerReferenceNo '{}' must have {} billIds"
                ).format(original_partner_reference_no, len(payments))
                return error_message, original_partner_reference_no, False

            dana_loan_reference = DanaLoanReference.objects.filter(
                partner_reference_no=original_partner_reference_no
            ).last()
            if not dana_loan_reference:
                error_message = "originalPartnerReferenceNo : {} not have loan.".format(
                    original_partner_reference_no
                )

                return error_message, original_partner_reference_no, False

            refund_amount = abs(int(float(bill_data[0]['amount'])))
            reason = bill_data[0].get('reason', '')
            customer_id = bill_data[0]['customerId']
            refund_time = bill_data[0]['transTime']
            lender_product_id = bill_data[0]['lenderProductId']
            credit_usage_mutation = abs(int(float(bill_data[0]['creditUsageMutation'])))

            if dana_loan_reference.lender_product_id != lender_product_id:
                error_message = (
                    "This originalPartnerReferenceNo {} doesn't match with lender product id {}"
                ).format(original_partner_reference_no, lender_product_id)
                return error_message, original_partner_reference_no, False

            disburse_back_amount = DanaRepaymentReference.objects.filter(
                bill_id__in=bill_list
            ).aggregate(Sum('total_repayment_amount'))
            disburse_back_amount = (
                disburse_back_amount['total_repayment_amount__sum'] or 0
            )  # Set default to 0 if disburse_back_amount = None.

            existing_refund_reference = DanaRefundReference.objects.filter(
                Q(partner_refund_no=partner_reference_no)
                | Q(original_partner_reference_no=original_partner_reference_no)
            )
            if existing_refund_reference:
                error_message = (
                    "partner_reference_no: '{}' or "
                    "original_partner_reference_no '{}' already refunded."
                ).format(partner_reference_no, original_partner_reference_no)
                return error_message, original_partner_reference_no, False
            else:
                dana_refund_reference = DanaRefundReference.objects.create(
                    partner_refund_no=partner_reference_no,
                    refund_no=refund_no,
                    original_partner_reference_no=original_partner_reference_no,
                    refund_amount=refund_amount,
                    disburse_back_amount=disburse_back_amount,
                    reason=reason,
                    customer_id=customer_id,
                    refund_time=refund_time,
                    original_reference_no=str(dana_loan_reference.reference_no),
                    lender_product_id=lender_product_id,
                    credit_usage_mutation=credit_usage_mutation,
                    status=DanaReferenceStatus.PENDING,
                )
                dana_refund_transaction = DanaRefundTransaction.objects.create(
                    dana_loan_reference=dana_loan_reference,
                    dana_refund_reference=dana_refund_reference,
                )

                logger.info({"action": fn_name, "status": "PROCESSING"})
                # do refund
                do_refund_payment_process(dana_refund_transaction.id, bill_data)

                dana_refunded_bill_list = []
                # bulk insert to dana_refunded_bill table
                for refunded_bill_detail in bill_data:
                    due_date_formatted = parse_datetime(refunded_bill_detail['dueDate']).strftime(
                        '%Y%m%d'
                    )

                    dana_refunded_bill_data = {
                        'dana_refund_transaction': dana_refund_transaction,
                        'cumulate_due_date_id': refunded_bill_detail.get('cumulateDueDateId'),
                        'bill_id': refunded_bill_detail['billId'],
                        'due_date': datetime.strptime(due_date_formatted, "%Y%m%d").strftime(
                            "%Y-%m-%d"
                        ),
                        'period_no': refunded_bill_detail['periodNo'],
                        'principal_amount': abs(
                            int(float(refunded_bill_detail['principalAmount']))
                        ),
                        'interest_fee_amount': abs(
                            int(float(refunded_bill_detail['interestFeeAmount']))
                        ),
                        'late_fee_Amount': abs(int(float(refunded_bill_detail['lateFeeAmount']))),
                        'paid_principal_amount': abs(
                            int(float(refunded_bill_detail['paidPrincipalAmount']))
                        ),
                        'paid_interest_fee_amount': abs(
                            int(float(refunded_bill_detail['paidInterestFeeAmount']))
                        ),
                        'paid_late_fee_amount': abs(
                            int(float(refunded_bill_detail['paidLateFeeAmount']))
                        ),
                        'total_amount': abs(int(float(refunded_bill_detail['totalAmount']))),
                        'total_paid_amount': abs(
                            int(float(refunded_bill_detail['totalPaidAmount']))
                        ),
                    }
                    dana_refunded_bill = DanaRefundedBill(**dana_refunded_bill_data)
                    dana_refunded_bill_list.append(dana_refunded_bill)

                DanaRefundedBill.objects.bulk_create(dana_refunded_bill_list, batch_size=30)

            logger.info({"action": fn_name, "status": "FINISHED"})

            return "", original_partner_reference_no, True

    except Exception as e:
        message = "Failed create refund reference for originalPartnerReferenceNo {}".format(
            bill_data[0].get('originalPartnerReferenceNo'),
        )
        logger.exception(
            {
                "action": "refund_failed_insert_refund_reference_data",
                "message": message,
                "error": str(e),
            }
        )
        raise Exception(e)


def do_refund_payment_process(dana_refund_transaction_id: int, bill_data: List[Dict]) -> None:
    """
    In this process the calculation to be paid using inner process and data from JULO side
    and the bill status should mark as FULLY PAID (PAID)
    set as CANCELLED is mean marked as REFUNDED (Treatment as repayment in JULO)
    """
    fn_name = "do_refund_payment_process"
    logger.info(
        {
            "action": fn_name,
            "dana_refund_transaction_id": dana_refund_transaction_id,
            "status": "STARTED",
        }
    )
    dana_refund_transaction = DanaRefundTransaction.objects.get(id=dana_refund_transaction_id)
    dana_refund_reference = dana_refund_transaction.dana_refund_reference

    for refunded_repayment_detail in bill_data:
        dana_payment_bill = DanaPaymentBill.objects.filter(
            bill_id=refunded_repayment_detail['billId']
        ).last()

        payment = Payment.objects.filter(id=dana_payment_bill.payment_id).last()
        principal_amount = payment.installment_principal - payment.paid_principal
        interest_fee_amount = payment.installment_interest - payment.paid_interest
        late_fee_amount = payment.late_fee_amount - payment.paid_late_fee
        total_amount = principal_amount + interest_fee_amount + late_fee_amount
        time_to_str = str(timezone.localtime(dana_refund_reference.refund_time))

        data = {
            'partnerReferenceNo': dana_refund_reference.partner_refund_no,
            'billId': refunded_repayment_detail['billId'],
            'billStatus': BILL_STATUS_PAID_OFF,
            'principalAmount': principal_amount,
            'interestFeeAmount': interest_fee_amount,
            'lateFeeAmount': late_fee_amount,
            'totalAmount': total_amount,
            'transTime': time_to_str,
            'lenderProductId': refunded_repayment_detail['lenderProductId'],
            # for event payment needed
            # example:
            # refunded_repayment_detail['lateFeeAmount'] = "-25.0"
            # float("-25.0") => -25.0
            # int(-25.0) => -25
            # abs(-25) => 25
            'danaLateFeeAmount': abs(int(float(refunded_repayment_detail['lateFeeAmount']))),
        }

        dana_loan_reference = payment.loan.danaloanreference
        is_recalculated = True
        if hasattr(payment.loan.danaloanreference, 'danaloanreferenceinsufficienthistory'):
            is_recalculated = (
                dana_loan_reference.danaloanreferenceinsufficienthistory.is_recalculated
            )

        logger.info(
            {
                "action": fn_name,
                "dana_refund_transaction_id": dana_refund_transaction_id,
                "status": "PROCESSING",
            }
        )
        create_manual_repayment_settlement(
            data=data, is_pending_process=True, is_refund=True, is_recalculated=is_recalculated
        )

    dana_refund_reference.update_safely(status=DanaReferenceStatus.SUCCESS)
    DanaLoanReferenceStatus.objects.update_or_create(
        dana_loan_reference=dana_refund_transaction.dana_loan_reference,
        defaults={'status': PaymentReferenceStatus.CANCELLED},
    )

    logger.info(
        {
            "action": fn_name,
            "dana_refund_transaction_id": dana_refund_transaction_id,
            "status": "FINISHED",
        }
    )
