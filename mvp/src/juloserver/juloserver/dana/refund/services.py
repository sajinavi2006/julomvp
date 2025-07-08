import csv
import io
import logging
import os
import uuid

from datetime import datetime
from django.conf import settings

from bulk_update.helper import bulk_update

from juloserver.dana.constants import DanaReferenceStatus, DANA_REPAYMENT_SETTLEMENT_HEADERS
from juloserver.dana.models import (
    DanaRefundReference,
    DanaRefundTransaction,
    DanaRefundedRepayment,
    DanaRefundedBill,
    DanaLoanReference,
    DanaRepaymentReference,
)
from juloserver.dana.refund.serializers import DanaRefundRepaymentSettlementSerializer
from juloserver.dana.utils import convert_str_to_abs_int
from juloserver.fdc.files import TempDir
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julo.models import UploadAsyncState

from typing import Dict, List

logger = logging.getLogger(__name__)


def insert_refund_data(data: Dict) -> DanaRefundReference:
    # insert to dana_refund_reference_table
    try:
        partner_refund_no = data['partnerRefundNo']
        refund_no = str(uuid.uuid4())
        original_partner_reference_no = data.get('originalPartnerReferenceNo')
        original_reference_no_from_dana_loan_reference = (
            DanaLoanReference.objects.filter(partner_reference_no=original_partner_reference_no)
            .values('reference_no')
            .last()
        )

        original_reference_no = data.get(
            'originalReferenceNo',
            str(original_reference_no_from_dana_loan_reference.get('reference_no', ''))
            if original_reference_no_from_dana_loan_reference
            else '',
        )
        original_external_id = data.get('originalExternalId', '')
        refund_amount = int(float(data['refundAmount']['value']))
        reason = data.get('reason', '')
        customer_id = data['additionalInfo']['customerId']
        refund_time = data['additionalInfo']['refundTime']
        lender_product_id = data['additionalInfo']['lenderProductId']
        credit_usage_mutation = int(float(data['additionalInfo']['creditUsageMutation']['value']))
        disburse_back_amount = int(float(data['additionalInfo']['disburseBackAmount']['value']))
        refunded_bill_detail_list = data['additionalInfo']['refundedTransaction'][
            'refundedBillDetailList'
        ]
        refunded_repayment_detail_list = data.get('additionalInfo', {}).get(
            'refundedRepaymentDetailList'
        )
        dana_refunded_repayment_list = []
        dana_refunded_bill_list = []

        dana_refund_reference = DanaRefundReference.objects.create(
            partner_refund_no=partner_refund_no,
            refund_no=refund_no,
            original_partner_reference_no=original_partner_reference_no,
            original_reference_no=original_reference_no,
            original_external_id=original_external_id,
            refund_amount=refund_amount,
            reason=reason,
            customer_id=customer_id,
            refund_time=refund_time,
            lender_product_id=lender_product_id,
            credit_usage_mutation=credit_usage_mutation,
            disburse_back_amount=disburse_back_amount,
            status=DanaReferenceStatus.PENDING,
        )
        dana_loan_reference = DanaLoanReference.objects.get(
            partner_reference_no=original_partner_reference_no
        )
        dana_refund_transaction = DanaRefundTransaction.objects.create(
            dana_loan_reference=dana_loan_reference,
            dana_refund_reference=dana_refund_reference,
        )

        if refunded_repayment_detail_list:
            # bulk insert to dana_refunded_repayment table
            for refunded_repayment_detail in refunded_repayment_detail_list:
                waived_principal_amount = (
                    int(float(refunded_repayment_detail["refundedWaivedPrincipalAmount"]["value"]))
                    if refunded_repayment_detail.get("refundedWaivedPrincipalAmount")
                    else None
                )
                waived_interest_fee_amount = (
                    int(
                        float(refunded_repayment_detail["refundedWaivedInterestFeeAmount"]["value"])
                    )
                    if refunded_repayment_detail.get("refundedWaivedInterestFeeAmount")
                    else None
                )
                waived_late_fee_amount = (
                    int(float(refunded_repayment_detail["refundedWaivedLateFeeAmount"]["value"]))
                    if refunded_repayment_detail.get("refundedWaivedLateFeeAmount")
                    else None
                )
                total_waived_amount = (
                    int(float(refunded_repayment_detail["refundedTotalWaivedAmount"]["value"]))
                    if refunded_repayment_detail.get("refundedTotalWaivedAmount")
                    else None
                )
                dana_refunded_repayment_data = {
                    'dana_refund_transaction': dana_refund_transaction,
                    'bill_id': refunded_repayment_detail['billId'],
                    'repayment_partner_reference_no': refunded_repayment_detail[
                        'repaymentPartnerReferenceNo'
                    ],
                    'principal_amount': int(
                        float(
                            refunded_repayment_detail['refundedRepaymentPrincipalAmount']['value']
                        )
                    ),
                    'interest_fee_amount': int(
                        float(
                            refunded_repayment_detail['refundedRepaymentInterestFeeAmount']['value']
                        )
                    ),
                    'late_fee_amount': int(
                        float(refunded_repayment_detail['refundedRepaymentLateFeeAmount']['value'])
                    ),
                    'total_amount': int(
                        float(refunded_repayment_detail['refundedTotalRepaymentAmount']['value'])
                    ),
                    'waived_principal_amount': waived_principal_amount,
                    'waived_interest_fee_amount': waived_interest_fee_amount,
                    'waived_late_fee_amount': waived_late_fee_amount,
                    'total_waived_amount': total_waived_amount,
                }
                dana_refunded_repayment = DanaRefundedRepayment(**dana_refunded_repayment_data)
                dana_refunded_repayment_list.append(dana_refunded_repayment)

            DanaRefundedRepayment.objects.bulk_create(dana_refunded_repayment_list, batch_size=30)

        # bulk insert to dana_refunded_bill table
        for refunded_bill_detail in refunded_bill_detail_list:
            waived_principal_amount = (
                int(float(refunded_bill_detail["waivedPrincipalAmount"]["value"]))
                if refunded_bill_detail.get("waivedPrincipalAmount")
                else None
            )
            waived_interest_fee_amount = (
                int(float(refunded_bill_detail["waivedInterestFeeAmount"]["value"]))
                if refunded_bill_detail.get("waivedInterestFeeAmount")
                else None
            )
            waived_late_fee_amount = (
                int(float(refunded_bill_detail["waivedLateFeeAmount"]["value"]))
                if refunded_bill_detail.get("waivedLateFeeAmount")
                else None
            )
            total_waived_amount = (
                int(float(refunded_bill_detail["totalWaivedAmount"]["value"]))
                if refunded_bill_detail.get("totalWaivedAmount")
                else None
            )
            dana_refunded_bill_data = {
                'dana_refund_transaction': dana_refund_transaction,
                'cumulate_due_date_id': refunded_bill_detail.get('cumulateDueDateId'),
                'bill_id': refunded_bill_detail['billId'],
                'due_date': datetime.strptime(refunded_bill_detail['dueDate'], "%Y%m%d").strftime(
                    "%Y-%m-%d"
                ),
                'period_no': refunded_bill_detail['periodNo'],
                'principal_amount': int(float(refunded_bill_detail['principalAmount']['value'])),
                'interest_fee_amount': int(
                    float(refunded_bill_detail['interestFeeAmount']['value'])
                ),
                'late_fee_Amount': int(float(refunded_bill_detail['lateFeeAmount']['value'])),
                'paid_principal_amount': int(
                    float(refunded_bill_detail['paidPrincipalAmount']['value'])
                ),
                'paid_interest_fee_amount': int(
                    float(refunded_bill_detail['paidInterestFeeAmount']['value'])
                ),
                'paid_late_fee_amount': int(
                    float(refunded_bill_detail['paidLateFeeAmount']['value'])
                ),
                'total_amount': int(float(refunded_bill_detail['totalAmount']['value'])),
                'total_paid_amount': int(float(refunded_bill_detail['totalPaidAmount']['value'])),
                'waived_principal_amount': waived_principal_amount,
                'waived_interest_fee_amount': waived_interest_fee_amount,
                'waived_late_fee_amount': waived_late_fee_amount,
                'total_waived_amount': total_waived_amount,
            }
            dana_refunded_bill = DanaRefundedBill(**dana_refunded_bill_data)
            dana_refunded_bill_list.append(dana_refunded_bill)

        DanaRefundedBill.objects.bulk_create(dana_refunded_bill_list, batch_size=30)
        return dana_refund_transaction

    except Exception as e:
        message = "Failed create refund reference for partner_refund_no {}".format(
            data.get('partnerRefundNo'),
        )
        logger.exception(
            {
                "action": "refund_failed_insert_repayment_reference_data",
                "message": message,
                "error": str(e),
            }
        )
        raise Exception(e)


def upload_dana_csv_data_to_oss(upload_async_state, file_path=None):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "dana/{}/{}".format(upload_async_state.id, file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def write_row_result(
    row: Dict, is_inserted: bool, is_valid: bool, errors: str = '', action: str = '', note: str = ''
) -> List:
    return [
        is_inserted,
        is_valid,
        row.get('partnerId'),
        row.get('lenderProductId'),
        "'{}".format(row.get('partnerReferenceNo')),
        "'{}".format(row.get('billId')),
        row.get('billStatus'),
        row.get('principalAmount'),
        row.get('interestFeeAmount'),
        row.get('lateFeeAmount'),
        row.get('totalAmount'),
        row.get('transTime'),
        row.get('waivedPrincipalAmount'),
        row.get('waivedInterestFeeAmount'),
        row.get('waivedLateFeeAmount'),
        row.get('totalWaivedAmount'),
        errors,
        action,
        note,
    ]


def process_dana_refund_repayment_settlement_result(upload_async_state: UploadAsyncState) -> bool:
    updated_drb = []

    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(DANA_REPAYMENT_SETTLEMENT_HEADERS)

            for row in reader:
                formatted_data = dict(row)
                serializer = DanaRefundRepaymentSettlementSerializer(
                    data=formatted_data,
                )

                is_inserted = False
                is_valid = False
                action = 'not_updated'
                error_str = '-'
                note = '-'
                if not serializer.is_valid():
                    error_list = serializer.errors.get('non_field_errors')
                    error_str = ', '.join(error_list)
                    note = 'Format data tidak valid, tolong cek kembali'
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    is_success_all = False
                    continue

                validated_data = serializer.validated_data
                bill_id = validated_data['billId']
                lender_product_id = validated_data['lenderProductId']
                repayment_partner_reference_no = validated_data['partnerReferenceNo']
                paid_principal_amount = abs(int(validated_data['principalAmount']))
                paid_interest_amount = abs(int(validated_data['interestFeeAmount']))
                paid_late_fee_amount = abs(int(validated_data['lateFeeAmount']))
                total_amount = abs(int(validated_data['totalAmount']))
                waived_principal_amount = convert_str_to_abs_int(
                    validated_data.get('waivedPrincipalAmount', 0)
                )
                waived_interest_fee_amount = convert_str_to_abs_int(
                    validated_data.get('waivedInterestFeeAmount', 0)
                )
                waived_late_fee_amount = convert_str_to_abs_int(
                    validated_data.get('waivedLateFeeAmount', 0)
                )
                total_waived_amount = convert_str_to_abs_int(
                    validated_data.get('totalWaivedAmount', 0)
                )

                bill_refunded = DanaRefundedBill.objects.filter(bill_id=bill_id).last()
                if not bill_refunded:
                    error_str = 'Bill ID tidak ada di list refund'
                    note = 'Pastikan Bill ID tercatat di table dana_refunded_bill'
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    is_success_all = False
                    continue

                dana_refund_transaction = bill_refunded.dana_refund_transaction
                dana_repayment_reference = DanaRepaymentReference.objects.filter(
                    partner_reference_no=repayment_partner_reference_no, bill_id=bill_id
                ).last()

                if not dana_repayment_reference:
                    error_str = 'partner reference no dan Bill ID tidak tercatat di sisi JULO'
                    note = (
                        'Pastikan partner reference no dan Bill ID sudah '
                        'di table dana_repayment_reference'
                    )
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    is_success_all = False
                    continue

                if dana_repayment_reference.lender_product_id != lender_product_id:
                    error_str = 'Bill ID ini bukan milik dari lender product id ini'
                    note = 'Pastikan Bill ID memiliki lender product id yang tepat'
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    is_success_all = False
                    continue

                # Success Processing
                is_bill_in_refunded_repayment = DanaRefundedRepayment.objects.filter(
                    bill_id=bill_id,
                    repayment_partner_reference_no=repayment_partner_reference_no,
                ).exists()

                is_valid = True
                action = 'data_is_similar_no_need_to_update'
                if not is_bill_in_refunded_repayment:
                    DanaRefundedRepayment.objects.create(
                        dana_refund_transaction=dana_refund_transaction,
                        bill_id=bill_id,
                        repayment_partner_reference_no=repayment_partner_reference_no,
                        principal_amount=paid_principal_amount,
                        interest_fee_amount=paid_interest_amount,
                        late_fee_amount=paid_late_fee_amount,
                        total_amount=total_amount,
                        waived_principal_amount=waived_principal_amount,
                        waived_interest_fee_amount=waived_interest_fee_amount,
                        waived_late_fee_amount=waived_late_fee_amount,
                        total_waived_amount=total_waived_amount,
                    )
                    action = 'inserted_new_data_in_refund_table'
                    is_inserted = True

                existing_principal_paid = dana_repayment_reference.principal_amount
                existing_interest_paid = dana_repayment_reference.interest_fee_amount
                existing_late_fee_paid = dana_repayment_reference.late_fee_amount

                if (
                    existing_principal_paid != paid_principal_amount
                    or existing_interest_paid != paid_interest_amount
                    or existing_late_fee_paid != paid_late_fee_amount
                ):
                    is_success_all = False
                    is_valid = False
                    error_str = 'Jumlah yang diupload tidak sama dengan yang tercatat di JULO'
                    note = 'Jumlah yang tercatat principal={}, interest={}, late fee={}'.format(
                        existing_principal_paid, existing_interest_paid, existing_late_fee_paid
                    )

                bill_refunded.waived_principal_amount = waived_principal_amount
                bill_refunded.waived_interest_fee_amount = waived_interest_fee_amount
                bill_refunded.waived_late_fee_amount = waived_late_fee_amount
                bill_refunded.total_waived_amount = total_waived_amount
                updated_drb.append(bill_refunded)

                write.writerow(
                    write_row_result(formatted_data, is_inserted, is_valid, error_str, action, note)
                )

            bulk_update(
                updated_drb,
                update_fields=[
                    "waived_principal_amount",
                    "waived_interest_fee_amount",
                    "waived_late_fee_amount",
                    "total_waived_amount",
                ],
            )

        upload_dana_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all
