import csv
import io
import os

from celery import group
from typing import List, Dict

from juloserver.dana.dana_lender.crm.serializers import DanaLenderSettlementFileSerializer
from juloserver.julo.models import UploadAsyncState
from juloserver.fdc.files import TempDir
from juloserver.dana.loan.crm.services import upload_csv_data_to_oss


DANA_LENDER_PAYMENT_UPLOAD_HEADER = [
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
    "transTime",
    "isPartialRefund",
    "failCode",
    "originalOrderAmount",
    "originalPartnerReferenceNo",
    "txnId",
    "waivedPrincipalAmount",
    "waivedInterestFeeAmount",
    "waivedLateFeeAmount",
    "totalWaivedAmount",
    "note",
]


def process_file_from_dana_lender_upload(upload_async_state: UploadAsyncState):
    from juloserver.dana.dana_lender.crm.tasks import dana_lender_process_upload_data

    batch_size = 300

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

        cleaned_data_list = []
        all_rows = []
        for row in reader:
            # Validate row data
            validation_errors = set()

            serializer = DanaLenderSettlementFileSerializer(data=row)
            error_validation = serializer.validate()

            if error_validation:
                # If validation errors exist, mark the row as invalid and write error notes
                validation_errors.update(error_validation)

            if validation_errors:
                # If validation errors exist, mark the row as invalid and write error notes
                row["note"] = ", ".join(validation_errors)
                row["is_valid"] = False
            else:
                row["note"] = ""  # Clear any existing note
                row["is_valid"] = True
                # Data is valid, continue processing
                validated_data = serializer.data
                cleaned_data_list.append(validated_data)

            all_rows.append(row)
        # Split cleaned data list into batches
        tasks = []
        for i in range(0, len(cleaned_data_list), batch_size):
            start = i
            end = i + batch_size
            batch = cleaned_data_list[start:end]
            tasks.append(dana_lender_process_upload_data.s(batch))

        # Run all batch tasks in parallel
        group(tasks).apply_async()

        # Iterate over the default dict and write all rows to the result, including invalid ones
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(DANA_LENDER_PAYMENT_UPLOAD_HEADER)

            # Write all rows to the result, including invalid ones
            for row in all_rows:
                is_inserted = row.get("is_inserted", False)
                is_valid = row.get("is_valid", False)
                row_result = write_row_result(row, is_inserted=is_inserted, is_valid=is_valid)
                write.writerow(row_result)

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all


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
        row.get('transTime', 'null'),
        row.get('isPartialRefund', 'null'),
        row.get('failCode', 'null'),
        row.get('originalOrderAmount', 'null'),
        row.get('originalPartnerReferenceNo', 'null'),
        row.get('txnId', 'null'),
        row.get('waivedPrincipalAmount', 'null'),
        row.get('waivedInterestFeeAmount', 'null'),
        row.get('waivedLateFeeAmount', 'null'),
        row.get('totalWaivedAmount', 'null'),
        row.get('note', 'null'),
    ]
