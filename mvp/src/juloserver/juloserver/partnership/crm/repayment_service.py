import csv
import uuid
from datetime import datetime
import io
import logging
import os
from typing import Dict, List

import pytz

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.utils import upload_file_to_oss

from django.db import transaction
from django.db.models import Sum
from django.utils.dateparse import parse_datetime
from django.conf import settings

from juloserver.fdc.files import TempDir
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    Partner,
    PaybackTransaction, Payment,
    PaymentMethod, UploadAsyncState,
)
from juloserver.julo.partners import PartnerConstant

from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes, PaymentStatusCodes,
)

from juloserver.partnership.constants import (
    PRODUCT_FINANCING_LOAN_REPAYMENT_UPLOAD_HEADERS,
    ProductFinancingUploadActionType,
)

from juloserver.partnership.crm.serializers import (
    ProductFinancingLoanRepaymentSerializer,
)

logger = logging.getLogger(__name__)


def write_row_result(
    row: Dict,
    is_passed: bool,
    notes: str,
    type: str,
) -> List:
    if type == ProductFinancingUploadActionType.LOAN_REPAYMENT:
        return [
            row.get("NIK"),
            row.get("Repayment Date"),
            row.get("Total Repayment"),
            is_passed,
            notes,
        ]


def upload_csv_data_to_oss(upload_async_state, file_path=None, product_name='agent_assisted'):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "{}/{}/{}".format(
        product_name, upload_async_state.id, file_name_elements[-1] + extension
    )
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def product_financing_loan_repayment_upload(upload_async_state: UploadAsyncState) -> bool:
    upload_file = upload_async_state.file
    file_io = io.StringIO(upload_file.read().decode("utf-8"))
    reader = csv.DictReader(file_io, delimiter=",")
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split("/")
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "w", encoding="utf-8-sig") as f:
            write = csv.writer(f)
            write.writerow(PRODUCT_FINANCING_LOAN_REPAYMENT_UPLOAD_HEADERS)
            checked_nik = set()

            file_io.seek(0)
            reader.__init__(file_io, delimiter=",")
            for row in reader:
                is_passed = False
                validation_errors = set()

                serializer = ProductFinancingLoanRepaymentSerializer(data=row)
                error_validation = serializer.validate()

                if error_validation:
                    # If validation errors exist, mark the row as invalid and write error notes
                    validation_errors.update(error_validation)
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row=row,
                            is_passed=is_passed,
                            notes=", ".join(validation_errors),
                            type=ProductFinancingUploadActionType.LOAN_REPAYMENT,
                        )
                    )
                    continue

                nik = row['NIK']
                if nik in checked_nik:
                    validation_errors.add("NIK {} sudah ada dalam file ini".format(nik))
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row=row,
                            is_passed=is_passed,
                            notes=", ".join(validation_errors),
                            type=ProductFinancingUploadActionType.LOAN_REPAYMENT,
                        )
                    )
                    continue

                else:
                    checked_nik.add(nik)

                validated_data = serializer.data

                try:
                    is_success, message = product_financing_loan_repayment(validated_data)
                    if not is_success:
                        is_success_all = False
                        validation_errors.add(message)
                        write.writerow(
                            write_row_result(
                                row=row,
                                is_passed=is_passed,
                                notes=", ".join(validation_errors),
                                type=ProductFinancingUploadActionType.LOAN_REPAYMENT,
                            )
                        )
                        continue

                except Exception as e:
                    is_success_all = False
                    write.writerow(
                        write_row_result(
                            row=row,
                            is_passed=is_passed,
                            notes=str(e),
                            type=ProductFinancingUploadActionType.LOAN_REPAYMENT,
                        )
                    )
                    continue

                write.writerow(
                    write_row_result(
                        row=row,
                        is_passed=is_success,
                        notes=message,
                        type=ProductFinancingUploadActionType.LOAN_REPAYMENT,
                    )
                )

        upload_csv_data_to_oss(
            upload_async_state, file_path=file_path, product_name="product_financing"
        )

    return is_success_all


def product_financing_loan_repayment(loan_repayment_data: Dict) -> (bool, str):
    nik = loan_repayment_data["NIK"]
    total_repayment_file_upload = float(loan_repayment_data["Total Repayment"])
    repayment_date_formatted = parse_datetime(loan_repayment_data["Repayment Date"]).strftime(
        '%d%m%Y'
    )
    repayment_date_file_upload = datetime.strptime(repayment_date_formatted, "%d%m%Y").strftime(
        "%d-%m-%Y"
    )

    partner_obj = Partner.objects.get(name=PartnerConstant.GOSEL)

    application = Application.objects.get_or_none(
        partner=partner_obj, ktp=nik, application_status=ApplicationStatusCodes.LOC_APPROVED
    )
    if not application:
        return False, "Pinjaman ini bukan termasuk pinjaman GOSEL"

    payments = Payment.objects.filter(
        loan__customer=application.customer,
        loan__partnerloanrequest__partner=partner_obj,
        account_payment__isnull=False,
    ).exclude(loan__loan_status=LoanStatusCodes.PAID_OFF)
    if not payments:
        return False, "Tidak ditemukan satu pun pinjaman untuk NIK {}".format(nik)

    total_payment_amount = payments.aggregate(
        total_paid_amount=Sum('paid_amount'))
    total_paid_amount = total_payment_amount.get('total_paid_amount', 0)

    actual_repayment_amount = total_repayment_file_upload - total_paid_amount

    if actual_repayment_amount <= 0:
        return False, "Pembayaran tidak cukup, mohon masukkan akumulasi pembayaran sebelumnya"

    total_due_amount = payments.aggregate(total_due_amount=Sum('due_amount'))
    if actual_repayment_amount > total_due_amount.get('total_due_amount', 0):
        return False, "Pembayaran melebihi total pinjaman"

    payment = (
        payments.filter(payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)
        .order_by('due_date')
        .first()
    )
    if not payment:
        return False, "Tidak ditemukan pinjaman untuk NIK {}".format(nik)

    note = "Repayment from GOSEL File Upload"
    local_timezone = pytz.timezone('Asia/Jakarta')

    try:
        with transaction.atomic():
            account_payment = payment.account_payment
            customer = account_payment.account.customer

            payment_method = PaymentMethod.objects.get_or_create(
                customer_id=customer.id,
                payment_method_name=PartnerConstant.GOSEL,
                payment_method_code='0000', is_shown=True)

            payback_transaction = PaybackTransaction.objects.create(
                is_processed=False,
                customer=customer,
                payback_service='manual',
                status_desc='manual process by agent',
                transaction_id=str(uuid.uuid4()),
                transaction_date=local_timezone.localize(
                    datetime.strptime(repayment_date_file_upload, '%d-%m-%Y')),
                amount=actual_repayment_amount,
                account=account_payment.account,
                payment_method=payment_method[0]
            )

            logger.info(
                {
                    'action': 'gojektsel_product_financing_loan_repayment',
                    'loan_id': payment.loan_id,
                    'account_id': account_payment.account_id,
                    'payback_transaction_id': payback_transaction.id,
                    'total_paid_amount': total_paid_amount,
                    'total_repayment_file_upload': total_repayment_file_upload,
                    'actual_repayment_amount': actual_repayment_amount,
                    'total_due_amount': total_due_amount,
                }
            )

            # process repayment transaction
            process_repayment_trx(
                payback_transaction, note=note
            )

            logger.info(
                {
                    'action': 'gojektsel_product_financing_loan_repayment',
                    'message': 'Finish process repayment transaction',
                }
            )

    except Exception as e:
        logger.error({"action": "product_financing_loan_repayment", "errors": e})
        raise JuloException(e)

    return True, "Repayment Sukses dengan loan_id: {}".format(payment.loan_id)
