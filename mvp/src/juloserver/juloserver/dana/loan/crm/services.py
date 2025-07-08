import csv
import io
import json
import logging
import math
import os
import re
from collections import namedtuple, defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from babel.dates import format_datetime
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.template import Context, Template
from django_bulk_update.helper import bulk_update
from django.utils import timezone

from juloserver.account.models import (
    AccountLimit,
    AccountTransaction,
)
from juloserver.dana.constants import (
    DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL,
    DanaInstallmentType,
    DanaLoanDuration,
    PaymentReferenceStatus,
    PaymentConsultErrorStatus,
    RepaymentReferenceStatus,
    DanaProductType,
)
from juloserver.dana.loan.crm.serializers import DanaLoanSettlementSerializer
from juloserver.dana.loan.serializers import DanaPaymentSerializer
from juloserver.dana.loan.services import (
    create_or_update_account_payments,
    create_payments_from_bill_detail,
    dana_generate_hashed_loan_xid,
    lender_matchmaking_for_dana,
    proceed_dana_payment,
    resume_dana_create_loan,
    update_available_limit_dana,
    update_commited_amount_for_lender,
)
from juloserver.dana.loan.utils import get_dana_loan_agreement_url
from juloserver.dana.models import (
    DanaCustomerData,
    DanaLoanReference,
    DanaPaymentBill,
    DanaRepaymentReference,
    DanaLoanReferenceStatus,
    DanaRepaymentReferenceStatus,
)
from juloserver.dana.tasks import generate_dana_loan_agreement
from juloserver.fdc.files import TempDir
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Loan,
    Payment,
    ProductLine,
    StatusLookup,
    UploadAsyncState,
    LoanHistory,
    FeatureSetting,
    ApplicationFieldChange,
    CustomerFieldChange,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import update_is_proven_julo_one
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import upload_file_to_oss, execute_after_transaction_safely
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.partnership.constants import PartnershipLoanStatusChangeReason
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.pusdafil.tasks import bunch_of_loan_creation_tasks
from juloserver.pusdafil.services import validate_pusdafil_customer_data
from juloserver.pusdafil.constants import (
    gender,
    job__job_industries,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

DANA_LOAN_SETTLEMENT_HEADER = [
    "is_inserted",
    "is_valid",
    "is_changed",
    "customerId",
    "partnerId",
    "lenderProductId",
    "partnerReferenceNo",
    "txnType",
    "amount",
    "billId",
    "dueDate",
    "periodNo",
    "creditUsageMutation",
    "principalAmount",
    "interestFeeAmount",
    "lateFeeAmount",
    "totalAmount",
    "originalOrderAmount",
    "transTime",
    "status",
    "failCode",
    "note",
]

DANA_UPDATE_PUSDAFIL_DATA_HEADER = [
    "account_id",
    "nik",
    "gender",
    "city",
    "province",
    "postal_code",
    "occupation",
    "income",
    "result",
]

logger = logging.getLogger(__name__)


def process_dana_update_pusdafil_data(upload_async_state: UploadAsyncState):
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

    is_success_all = True
    map_csv = {}
    map_validation = {}
    error_msg = []
    applications = []

    try:
        csv_header = set(reader.fieldnames)
        missing_columns = []
        for column in DANA_UPDATE_PUSDAFIL_DATA_HEADER:
            if column not in csv_header and column != 'result':
                missing_columns.append(column)

        if len(missing_columns) > 0:
            raise Exception(
                'invalid csv header, missing column {}'.format(', '.join(missing_columns))
            )

        for line in reader:
            # map with dana_customer_identifier id
            map_csv[line['account_id']] = line

        dana_customer_datas = DanaCustomerData.objects.select_related(
            'application',
        ).filter(dana_customer_identifier__in=map_csv.keys())

        update_dana_customers = []
        customers = []
        create_application_field_changes = []
        create_customer_field_changes = []

        with transaction.atomic():
            for dana_customer in dana_customer_datas.iterator():
                """
                for city and province, will be inputed as it is,
                for job_type and job_industry, map value will be inputed
                null value will be inputted for all cases in case map cannot be found
                """
                gender_data = map_csv[dana_customer.dana_customer_identifier]['gender']
                income_data = map_csv[dana_customer.dana_customer_identifier]['income']
                city_data = map_csv[dana_customer.dana_customer_identifier]['city']
                province_data = map_csv[dana_customer.dana_customer_identifier]['province']
                job_position_data = map_csv[dana_customer.dana_customer_identifier]['occupation']
                post_code_data = map_csv[dana_customer.dana_customer_identifier]['postal_code']

                result_msg = ''
                invalid_fields = []

                # If data not exist on key mapping, update field to null
                city_value = None
                province_value = None

                dana_province_city_feature = FeatureSetting.objects.get_or_none(
                    feature_name=FeatureNameConst.DANA_PROVINCE_AND_CITY
                )

                if dana_province_city_feature:
                    uppercase_province = province_data.upper()
                    uppercase_city = city_data.upper()

                    dana_province = dana_province_city_feature.parameters['province']
                    if dana_province.get(uppercase_province):
                        province_value = dana_province.get(uppercase_province)

                    dana_city = dana_province_city_feature.parameters['city']
                    if dana_city.get(uppercase_city):
                        city_value = dana_city.get(uppercase_city)

                # Mapping dana job format to julos job format
                occupation_value = None
                occupation_industry_value = None

                dana_occupation_feature_setting = FeatureSetting.objects.get_or_none(
                    feature_name=FeatureNameConst.DANA_JOB
                )
                if dana_occupation_feature_setting:
                    dana_occupation = dana_occupation_feature_setting.parameters['job']
                    if dana_occupation.get(job_position_data.upper()):
                        occupation_value = dana_occupation.get(job_position_data.upper())
                        occupation_industry_value = job__job_industries.get(
                            occupation_value.upper()
                        )

                if not gender.get(gender_data.upper()):
                    invalid_fields.append('gender')
                if not city_value:
                    invalid_fields.append('city')
                if not province_value:
                    invalid_fields.append('province')
                if not dana_occupation.get(job_position_data.upper()):
                    invalid_fields.append('occupation')

                pattern = r'^\d{5}$'
                if not re.match(pattern, post_code_data):
                    invalid_fields.append('postal_code')
                    post_code_data = None

                if len(invalid_fields) == 0:
                    result_msg = 'Success'
                elif len(invalid_fields) < 6:
                    is_success_all = False
                    result_msg = (
                        ', '.join(invalid_fields)
                        + ' not uploaded could be due to invalid data format'
                    )
                elif len(invalid_fields) == 6:
                    is_success_all = False
                    result_msg = 'Failed to upload'

                monthly_income_feature_setting = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.DANA_MONTHLY_INCOME,
                    is_active=True,
                ).last()
                validate_feature_setting = (
                    monthly_income_feature_setting
                    and monthly_income_feature_setting.parameters
                    and income_data
                )
                if validate_feature_setting:
                    income_range = income_data.replace(" ", "").lower()
                    if not monthly_income_feature_setting.parameters.get(income_range):
                        is_success_all = False
                        result_msg = 'failed to update income,  invalid map income please adjust it'
                elif (
                    not isinstance(income_data, int)
                    and isinstance(income_data, str)
                    and not income_data.isdigit()
                ):
                    is_success_all = False
                    result_msg = 'failed to update income, income is invalid'

                map_validation[dana_customer.dana_customer_identifier] = result_msg

                dana_customer.application.gender = gender.get(gender_data.upper())
                dana_customer.application.job_type = occupation_value
                dana_customer.application.job_industry = occupation_industry_value

                udate = timezone.localtime(timezone.now())

                # Need to update monthly income if the value is null
                if not dana_customer.application.monthly_income:
                    income = income_data
                    if validate_feature_setting:
                        income = monthly_income_feature_setting.parameters.get(income_range)

                    old_income = dana_customer.application.monthly_income
                    dana_customer.application.monthly_income = income
                    create_application_field_changes.append(
                        ApplicationFieldChange(
                            application=dana_customer.application,
                            field_name="monthly_income",
                            old_value=old_income,
                            new_value=dana_customer.application.monthly_income,
                        )
                    )

                    dana_customer.customer.monthly_income = income
                    dana_customer.customer.udate = udate
                    customers.append(dana_customer.customer)
                    create_customer_field_changes.append(
                        CustomerFieldChange(
                            application_id=dana_customer.application_id,
                            customer=dana_customer.customer,
                            field_name="monthly_income",
                            old_value=old_income,
                            new_value=dana_customer.customer.monthly_income,
                        )
                    )

                    dana_customer.income = income_data
                    dana_customer.udate = udate
                    update_dana_customers.append(dana_customer)

                dana_customer.application.address_provinsi = province_value
                dana_customer.application.address_kabupaten = city_value
                dana_customer.application.address_kodepos = post_code_data
                dana_customer.application.udate = udate

                applications.append(dana_customer.application)

        bulk_update(
            applications,
            update_fields=[
                'gender',
                'job_type',
                'job_industry',
                'address_provinsi',
                'address_kabupaten',
                'address_kodepos',
                'udate',
                'monthly_income',
            ],
            batch_size=100,
        )
        bulk_update(
            update_dana_customers,
            update_fields=['udate', 'income'],
            batch_size=100,
        )
        bulk_update(
            customers,
            update_fields=['udate', 'monthly_income'],
            batch_size=100,
        )
        CustomerFieldChange.objects.bulk_create(create_customer_field_changes, batch_size=100)
        ApplicationFieldChange.objects.bulk_create(create_application_field_changes, batch_size=100)

        # send applications to pusdafil
        # comment it because pusdafil 1.0 will turn off
        # based on this slack discussion
        # https://julofinance.slack.com/archives/C048NPDLJG1/p1731976570883209
        # 19 November 2024
        # send_application_to_pusdafil(applications)

    except Exception as error:
        logger.error(
            {
                'action': 'process_dana_update_pusdafil_data',
                'load_async_state_id': upload_async_state.id,
                'error': error,
            }
        )
        is_success_all = False
        error_msg.append(error)

    local_file_path = upload_async_state.file.path
    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            if len(error_msg) > 0:
                write.writerow(error_msg)
            else:
                write.writerow(DANA_UPDATE_PUSDAFIL_DATA_HEADER)

                for account_id, csv_row in map_csv.items():
                    message = 'account_id not found'

                    if map_validation.get(account_id):
                        message = map_validation.get(account_id)

                    csv_row['result'] = message
                    result_list = list(csv_row.values())
                    write.writerow(result_list)

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    return is_success_all


def send_application_to_pusdafil(applications):
    validated_applications = validate_pusdafil_customer_data(applications)

    for application in validated_applications:
        loan = Loan.objects.filter(application=application).order_by("cdate").last()

        if not loan:
            loan = Loan.objects.filter(account=application.account).order_by("cdate").last()

        if loan:
            bunch_of_loan_creation_tasks.delay(
                application.customer.user_id, application.customer_id, application.id, loan.id
            )


def process_dana_loan_settlement_file(upload_async_state: UploadAsyncState, product_type: str):
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path
    payment_consult_errors = PaymentConsultErrorStatus()

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)

        mapping_count_bill_id = defaultdict(int)
        for bill_list in reader:
            mapping_count_bill_id[bill_list['partnerReferenceNo']] += 1

        freader.seek(0)
        reader.__init__(freader, delimiter=',')

        with open(file_path, "w", encoding='utf-8-sig') as f:
            """
            There are some variable that need to be explain:
                - loop: Boolean to checked the position of the pointer.
                    if True, then the pointer is back to the top of the file
                - checked_bill_ids: a set to save bill_id that already been checked before
                    when looking for the same partnerReferenceId for create a new Loan.
                    To remove posibility duplicate check and looping until EOF.
                    Because we only stop the loop if the bill data already 4
            """
            write = csv.writer(f)
            write.writerow(DANA_LOAN_SETTLEMENT_HEADER)
            reader_len = len(list(reader))
            match_data_note = "No need update data, the data is already match"
            no_match_data_note = "Several data is not match, need to re-calculate"
            success_note = "Success with reference_no: {} and document url: {}"
            idx = 0
            loop = False
            checked_bill_ids = set()
            bill_notes = {}
            freader.seek(idx)
            reader.__init__(freader, delimiter=',')
            while idx < reader_len:
                if loop:
                    loop = False
                    for _ in range(idx + 1):
                        next(reader)
                else:
                    row = next(reader)

                if row["txnType"] != 'PAYMENT':
                    row["note"] = "txnType is not PAYMENT"
                    write.writerow(write_row_result(row, False, False))
                    idx += 1
                    continue

                if row["lenderProductId"] != product_type:
                    row["note"] = "Invalid product type, expected product {} but got {}.".format(
                        product_type, row["lenderProductId"]
                    )
                    write.writerow(write_row_result(row, False, False))
                    idx += 1
                    continue

                # Do cancellation processing
                if row['status'] == 'FAILED':
                    if row['failCode'] in payment_consult_errors.is_need_to_cancel:
                        process_payment_cancel = process_payment_as_cancel(
                            row['partnerReferenceNo']
                        )
                        row["note"] = process_payment_cancel.notes
                        is_inserted = False
                        write.writerow(
                            write_row_result(
                                row,
                                is_inserted,
                                process_payment_cancel.is_valid,
                                process_payment_cancel.is_changed,
                            )
                        )
                    else:
                        row[
                            "note"
                        ] = 'No need to cancel since on this status, loan not created in julo side'
                        is_inserted = False
                        is_valid = False
                        is_changed = False
                        write.writerow(write_row_result(row, is_inserted, is_valid, is_changed))

                    idx += 1
                    continue

                # Do Success Process need to check this all rules
                # Cannot compare anything without billId
                if not row["billId"]:
                    row["note"] = "no billId provided"
                    write.writerow(write_row_result(row, False, False))
                    idx += 1
                    continue

                if row["failCode"] and row["failCode"] != 'null':
                    row["note"] = "have failCode: {} but status not failed".format(row["failCode"])
                    write.writerow(write_row_result(row, False, False))
                    idx += 1
                    continue

                if row["billId"] in checked_bill_ids:
                    row["note"] = bill_notes[row["billId"]]["note"]
                    is_inserted = bill_notes[row["billId"]]["is_inserted"]
                    is_valid = bill_notes[row["billId"]]["is_valid"]
                    write.writerow(write_row_result(row, is_inserted, is_valid))
                    idx += 1
                    continue

                serializer = DanaLoanSettlementSerializer(data=row)
                if serializer.is_valid():
                    validated_data = serializer.validated_data
                    bill_id = validated_data["billId"]
                    dana_payment_bill = DanaPaymentBill.objects.filter(bill_id=bill_id).last()
                    if not dana_payment_bill:
                        bill_data = []
                        bill_data.append(validated_data)
                        checked_bill_ids.add(validated_data["billId"])
                        is_one_bill = mapping_count_bill_id[row['partnerReferenceNo']] == 1
                        if is_one_bill and len(bill_data) == 1:
                            payload = format_bills_into_loan_creation_payload(
                                bill_data, product_type
                            )
                            try:
                                url, ref_no = create_or_update_dana_loan(payload)
                            except Exception as e:
                                # Write error to csv
                                # If found error go to next row directly
                                try:
                                    error_message = str(e)
                                except TypeError:
                                    error_message = str(e.detail["additionalInfo"])
                                note = "{}: {}".format(error_message, json.dumps(payload))
                                is_inserted = False
                                is_valid = False
                                is_success_all = False
                            else:
                                # Write success to csv
                                note = success_note.format(ref_no, url)
                                is_inserted = True
                                is_valid = True

                            row["note"] = note
                            write.writerow(write_row_result(row, is_inserted, is_valid))
                            idx += 1
                            continue

                        while True:
                            try:
                                sec_row = next(reader)
                                # TODO: normalize this condition
                                if not sec_row["billId"]:
                                    continue

                                if (
                                    validated_data["partnerReferenceNo"]
                                    != sec_row["partnerReferenceNo"]
                                ):
                                    continue

                                logger.info(
                                    {
                                        'action': 'process_create_dana_loan_settlement_file',
                                        'partner_reference_no': sec_row["partnerReferenceNo"],
                                    }
                                )

                                checked_bill_ids.add(sec_row["billId"])
                                sec_serializer = DanaLoanSettlementSerializer(data=sec_row)
                                if not sec_serializer.is_valid():
                                    # Write error to csv and go to next row directly
                                    logger.error(
                                        {
                                            'action': 'process_dana_loan_settlement_file',
                                            'error': serializer.errors,
                                        }
                                    )
                                    is_success_all = False
                                    msg = "Row with same partnerReferenceNo is not valid. billId: "
                                    row["note"] = msg + sec_row["billId"]

                                    write.writerow(write_row_result(row, False, False))
                                    idx += 1
                                    loop = True
                                    freader.seek(0)
                                    reader.__init__(freader, delimiter=',')
                                    break

                                dana_payment_bill_2 = DanaPaymentBill.objects.filter(
                                    bill_id=sec_row["billId"]
                                ).last()
                                if dana_payment_bill_2:
                                    is_same_principal = (
                                        dana_payment_bill_2.principal_amount
                                        == float(validated_data["principalAmount"])
                                    )
                                    is_same_interest = (
                                        dana_payment_bill_2.interest_fee_amount
                                        == float(validated_data["interestFeeAmount"])
                                    )
                                    if is_same_principal and is_same_interest:
                                        bill_notes[sec_row["billId"]] = {
                                            "note": match_data_note,
                                            "is_inserted": False,
                                            "is_valid": True,
                                        }
                                        continue
                                    else:
                                        is_success_all = False
                                        bill_notes[sec_row["billId"]] = {
                                            "note": no_match_data_note,
                                            "is_inserted": False,
                                            "is_valid": False,
                                        }
                                        # TODO: Update value of the payment, loan, etc
                                        continue

                                bill_data.append(sec_serializer.validated_data)
                                total_bill_ids = mapping_count_bill_id[row['partnerReferenceNo']]
                                if len(bill_data) == total_bill_ids:
                                    # Create new Loan
                                    payload = format_bills_into_loan_creation_payload(
                                        bill_data, product_type
                                    )

                                    try:
                                        url, ref_no = create_or_update_dana_loan(payload)
                                    except Exception as e:
                                        # Write error to csv
                                        # If found error go to next row directly
                                        try:
                                            error_message = str(e)
                                        except TypeError:
                                            error_message = str(e.detail["additionalInfo"])
                                        note = "{}: {}".format(error_message, json.dumps(payload))
                                        is_inserted = False
                                        is_valid = False
                                        is_success_all = False
                                    else:
                                        # Write success to csv
                                        note = success_note.format(ref_no, url)
                                        is_inserted = True
                                        is_valid = True

                                    for bill in bill_data:
                                        bill_notes[bill["billId"]] = {
                                            "note": note,
                                            "is_inserted": is_inserted,
                                            "is_valid": is_valid,
                                        }

                                    idx -= 1
                                    loop = True
                                    freader.seek(0)
                                    reader.__init__(freader, delimiter=',')
                                    break
                            except KeyError:
                                note = "cannot find partnerReferenceNo {} in csv data".format(
                                    row['partnerReferenceNo']
                                )
                                for bill in bill_data:
                                    bill_notes[bill["billId"]] = {
                                        "note": note,
                                        "is_inserted": False,
                                        "is_valid": False,
                                    }
                                is_success_all = False
                                loop = True
                                idx -= 1
                                freader.seek(0)
                                reader.__init__(freader, delimiter=',')
                                break

                            except StopIteration:
                                note = (
                                    "Number of bill with same partnerReferenceNo,"
                                    "not same bill_data = {}, csv = {}".format(
                                        len(bill_data),
                                        mapping_count_bill_id[row['partnerReferenceNo']],
                                    )
                                )

                                for bill in bill_data:
                                    bill_notes[bill["billId"]] = {
                                        "note": note,
                                        "is_inserted": False,
                                        "is_valid": False,
                                    }
                                is_success_all = False
                                loop = True
                                idx -= 1
                                freader.seek(0)
                                reader.__init__(freader, delimiter=',')
                                break
                    else:
                        """
                        Compare principal and interest from database with csv
                        If same, then continue to the next row
                        else update the value in database from the csv
                        """
                        is_same_principal = dana_payment_bill.principal_amount == float(
                            validated_data["principalAmount"]
                        )
                        is_same_interest = dana_payment_bill.interest_fee_amount == float(
                            validated_data["interestFeeAmount"]
                        )
                        if is_same_principal and is_same_interest:
                            row["note"] = match_data_note
                            write.writerow(write_row_result(row, False, True))
                        else:
                            is_success_all = False
                            row["note"] = no_match_data_note
                            write.writerow(write_row_result(row, False, False))
                            # TODO: Update value of the payment, loan, etc
                else:
                    logger.error(
                        {
                            'action': 'process_dana_loan_settlement_file',
                            'error': serializer.errors,
                        }
                    )
                    row["note"] = serializer.errors
                    write.writerow(write_row_result(row, False, False))
                    is_success_all = False

                idx += 1

        upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def process_dana_update_loan_fund_transfer_ts(
    upload_async_state: UploadAsyncState, product_type: str
):
    fn_name = "process_dana_update_loan_fund_transfer_ts"
    logger.info(
        {
            "action": fn_name,
            "upload_async_state_id": upload_async_state.id,
            "product_type": product_type,
            "status": "STARTED",
        }
    )
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

    is_success_all = True
    local_file_path = upload_async_state.file.path
    is_dana_cash_loan_product_type = product_type == DanaProductType.CASH_LOAN
    is_dana_cicil_product_type = product_type == DanaProductType.CICIL
    header_csv_result = None

    if is_dana_cash_loan_product_type:
        header_csv_result = [
            "REQUEST_ID",
            "FUND_AMOUNT",
            "FUND_AMOUNT_CURRENCY",
            "CHARGE_AMOUNT",
            "FEE",
            "WHT",
            "VAT",
            "PAID_TOTAL_AMOUNT",
            "PAYER_ROLE_ID",
            "DEPOSIT_ACCOUNT_NO",
            "MERCHANT_NAME",
            "TRANSACTION_DATE",
            "SOURCE",
            "REPORT_DATE",
            "DIVISION_ID",
            "EXTERNAL_DIVISION_ID",
            "note",
        ]
    elif is_dana_cicil_product_type:
        header_csv_result = [
            "loan_id",
            "note",
        ]

    def _write_row_result(row: Dict, note: str) -> List:
        if is_dana_cash_loan_product_type:
            return [
                row.get('REQUEST_ID'),
                row.get('FUND_AMOUNT'),
                row.get('FUND_AMOUNT_CURRENCY'),
                row.get('CHARGE_AMOUNT'),
                row.get('FEE'),
                row.get('WHT'),
                row.get('VAT'),
                row.get('PAID_TOTAL_AMOUNT'),
                row.get('PAYER_ROLE_ID'),
                row.get('DEPOSIT_ACCOUNT_NO'),
                row.get('MERCHANT_NAME'),
                row.get('TRANSACTION_DATE'),
                row.get('SOURCE'),
                row.get('REPORT_DATE'),
                row.get('DIVISION_ID'),
                row.get('EXTERNAL_DIVISION_ID'),
                note,
            ]
        elif is_dana_cicil_product_type:
            return [
                row.get('loan_id'),
                note,
            ]

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        transaction_date = None
        loan_ids = set()

        if is_dana_cash_loan_product_type:
            partner_references_no = dict()
            for row in reader:
                if row['REQUEST_ID']:
                    string_transaction_date = row['TRANSACTION_DATE']
                    date_format = '%Y%m%d %H:%M:%S'
                    try:
                        convert_transaction_date = datetime.strptime(
                            string_transaction_date, date_format
                        )
                    except ValueError:
                        convert_transaction_date = None

                    partner_references_no[row['REQUEST_ID']] = {
                        "transaction_date": convert_transaction_date
                    }

            dana_loan_references = DanaLoanReference.objects.filter(
                partner_reference_no__in=partner_references_no.keys()
            )
            for dana_loan_reference in dana_loan_references.iterator():
                loan_ids.add(dana_loan_reference.loan_id)
                if partner_references_no.get(dana_loan_reference.partner_reference_no):
                    partner_references_no[dana_loan_reference.partner_reference_no].update(
                        {'loan_id': dana_loan_reference.loan_id}
                    )
        elif is_dana_cicil_product_type:
            for row in reader:
                if row['loan_id'] and row['loan_id'].isnumeric():
                    loan_ids.add(row["loan_id"])
            transaction_date = timezone.now()

        loans = (
            Loan.objects.filter(
                id__in=loan_ids,
                account__account_lookup__name='DANA',
                loan_status__gte=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                loan_status__lte=LoanStatusCodes.PAID_OFF,
            )
            .only(
                "id",
                "fund_transfer_ts",
                "application_id2",
                "disbursement_id",
                "loan_amount",
                "account",
                "danaloanreference",
            )
            .select_related("account")
        )
        loan_dicts = dict()
        for loan in loans.iterator():
            loan_dicts[loan.id] = loan

        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(header_csv_result)

            freader.seek(0)
            reader.__init__(freader, delimiter=',')
            for _, row in enumerate(reader, start=2):
                loan = None
                if is_dana_cicil_product_type:
                    if not row['loan_id'].isnumeric():
                        write.writerow(_write_row_result(row, "loan_id not a valid integer"))
                        is_success_all = False
                        continue

                    loan = loan_dicts.get(int(row["loan_id"]))

                if is_dana_cash_loan_product_type:
                    if not partner_references_no.get(row['REQUEST_ID']):
                        write.writerow(_write_row_result(row, "REQUEST_ID is required"))
                        is_success_all = False
                        continue

                    transaction_date = partner_references_no[row['REQUEST_ID']].get(
                        'transaction_date'
                    )
                    if not transaction_date:
                        write.writerow(_write_row_result(row, "transaction_date not found"))
                        is_success_all = False
                        continue

                    loan_id = partner_references_no[row['REQUEST_ID']].get('loan_id')
                    loan = loan_dicts.get(loan_id)

                if not loan:
                    write.writerow(_write_row_result(row, "loan not found"))
                    is_success_all = False
                    continue

                if not hasattr(loan, 'danaloanreference'):
                    write.writerow(_write_row_result(row, "danaloanreference not found"))
                    is_success_all = False
                    continue

                loan_product_type = loan.account.dana_customer_data.lender_product_id
                if loan_product_type != product_type:
                    write.writerow(
                        _write_row_result(
                            row,
                            "product type is {} cannot be updated because different "
                            "choosen product type = {} please choose correct product type".format(
                                loan_product_type, product_type
                            ),
                        )
                    )
                    is_success_all = False
                    continue

                if not loan.fund_transfer_ts or is_dana_cash_loan_product_type:
                    loan.fund_transfer_ts = transaction_date
                    loan.save(update_fields=['fund_transfer_ts'])
                    partner_loan = loan.partnerloanrequest_set.only("loan_amount").last()
                    transaction_amount = partner_loan.loan_amount * -1
                    AccountTransaction.objects.create(
                        account=loan.account,
                        payback_transaction=None,
                        disbursement_id=loan.disbursement_id,
                        transaction_date=transaction_date,
                        transaction_amount=transaction_amount,
                        transaction_type="disbursement",
                        towards_principal=transaction_amount,
                        towards_interest=0,
                        towards_latefee=0,
                        spend_transaction=None,
                    )
                    write.writerow(_write_row_result(row, "success update fund_transfer_ts"))
                else:
                    write.writerow(_write_row_result(row, "already have fund_transfer_ts"))
                    is_success_all = False
        upload_csv_data_to_oss(upload_async_state, file_path=file_path)

    logger.info(
        {
            "action": fn_name,
            "upload_async_state_id": upload_async_state.id,
            "product_type": product_type,
            "status": "FINISHED",
        }
    )
    return is_success_all


def create_new_loan_from_settlement_data(data: Dict) -> Tuple[str, str]:
    """
    This Funtion is DEPRECATED
    """
    serializer = DanaPaymentSerializer(data=data)
    if not serializer.is_valid():
        raise Exception(serializer.errors)
    validated_data = serializer.validated_data
    additional_data = validated_data["additionalInfo"]
    dana_customer_data = (
        DanaCustomerData.objects.filter(
            dana_customer_identifier=additional_data["customerId"],
            lender_product_id=additional_data["lenderProductId"],
        )
        .select_related("account", "customer")
        .last()
    )
    if not dana_customer_data:
        raise Exception("customerId doesn't exists")

    detokenize_dana_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.DANA_CUSTOMER_DATA,
        dana_customer_data,
        dana_customer_data.customer.customer_xid,
        ['mobile_number', 'nik', 'full_name'],
    )
    account = dana_customer_data.account
    account_limit = account.accountlimit_set.first()
    if not account_limit:
        raise Exception("User not have account limit, please check internally")

    loan_amount = float(validated_data["additionalInfo"]["creditUsageMutation"]["value"])
    if account_limit.available_limit < loan_amount:
        raise Exception("Loan amount exceeded available limit")

    dana_product_line = ProductLine.objects.get(pk=ProductLineCodes.DANA)
    application = (
        account.application_set.filter(
            product_line=dana_product_line,
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )
        .select_related("partner")
        .last()
    )
    # Since product lookup for Dana only 1 for now, then we can use .first()
    product_lookup = application.product_line.productlookup_set.first()
    loan_disbursement_amount = float(validated_data["amount"]["value"])
    bill_detail = additional_data["billDetailList"]
    installment_amount = float(bill_detail[0]["totalAmount"]["value"])
    transaction_time = additional_data["transTime"]
    original_order_amount = float(additional_data["originalOrderAmount"]["value"])
    try:
        with transaction.atomic(using='default'):
            loan = Loan.objects.create(
                customer=application.customer,
                loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
                product=product_lookup,
                loan_amount=loan_disbursement_amount,
                loan_duration=DanaLoanDuration.FOUR,
                first_installment_amount=installment_amount,
                installment_amount=installment_amount,
                bank_account_destination=None,
                name_bank_validation_id=application.name_bank_validation.id,
                account=application.account,
                application_id2=application.id,
                loan_disbursement_amount=loan_disbursement_amount,
                transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana
            )
            loan.cdate = transaction_time
            loan.save()
            partner_loan_request = PartnerLoanRequest.objects.create(
                loan=loan,
                partner=application.partner,
                loan_amount=loan_amount,
                loan_disbursement_amount=loan.loan_disbursement_amount,
                loan_original_amount=loan_amount,
            )

            # Get value from django admin feature setting dana_late_fee
            feature_dana_late_fee = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.DANA_LATE_FEE,
            ).last()
            late_fee_rate = feature_dana_late_fee.parameters.get('late_fee') * 100

            dana_loan_reference = DanaLoanReference.objects.create(
                partner_reference_no=validated_data.get('partnerReferenceNo'),
                loan=loan,
                original_order_amount=original_order_amount,
                merchant_id=validated_data.get('merchantId'),
                amount=float(validated_data.get('amount').get('value')),
                order_info=additional_data.get('orderInfo'),
                customer_id=additional_data.get('customerId'),
                trans_time=additional_data.get('transTime'),
                lender_product_id=additional_data.get('lenderProductId'),
                credit_usage_mutation=float(
                    additional_data.get('creditUsageMutation').get('value')
                ),
                late_fee_rate=late_fee_rate,
            )
            dana_loan_reference.cdate = transaction_time
            dana_loan_reference.save()

            update_available_limit_dana(loan, partner_loan_request)
            payments = create_payments_from_bill_detail(bill_detail, loan)
            lender, disbursement = lender_matchmaking_for_dana(loan, application)
            update_commited_amount_for_lender(loan, lender, disbursement)
            loan.refresh_from_db()
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.CURRENT,
                change_reason=PartnershipLoanStatusChangeReason.ACTIVATED,
            )
            create_or_update_account_payments(payments, loan.account)
    except Exception as e:
        raise Exception(str(e))

    agreement_info = validated_data["additionalInfo"]["agreementInfo"]
    provision_amount = format_rupiahs(
        str(agreement_info["provisionFeeAmount"]["value"]), "no_currency"
    )

    partner_email = agreement_info.get("partnerEmail")
    partner = application.partner
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    if not partner_email:
        partner_email = detokenize_partner.email
    partner_tnc = agreement_info.get("partnerTnc")
    if not partner_tnc:
        partner_tnc = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL
    partner_privacy_rule = agreement_info.get("partnerPrivacyRule")
    if not partner_privacy_rule:
        partner_privacy_rule = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL

    sorted_bills = dict()
    total_interest_amount = 0
    for bill in bill_detail:
        sorted_bills[str(bill["periodNo"])] = bill
        due_date_datetime = datetime.strptime(bill["dueDate"], "%Y%m%d")
        sorted_bills[str(bill["periodNo"])]["due_date"] = due_date_datetime
        total_interest_amount += float(bill["interestFeeAmount"]["value"])

    sorted_bills = dict(sorted(sorted_bills.items(), key=lambda x: int(x[0])))

    # update this logic below when Dana have sent installmentType on SF file loan upload :
    # noted on (5 Feb 2025)
    payment_list = Payment.objects.filter(id__in=payments)

    # last installment due_date from payments
    last_installment_due_date = (
        payment_list.order_by('-due_date').values_list('due_date', flat=True).first()
    )
    loan_created_date = loan.cdate

    installment_type = None
    installment_count = 0
    dana_installment_count = 0
    dana_installment_type = ""
    if dana_loan_reference.installment_config:
        dana_installment_count = dana_loan_reference.installment_config.get('installmentCount', 0)
        dana_installment_type = dana_loan_reference.installment_config.get('installmentType')
        installment_count = int(dana_installment_count)

    if not installment_count:
        last_installment_due_date = datetime.combine(
            last_installment_due_date, datetime.min.time(), tzinfo=loan_created_date.tzinfo
        )
        day_difference = (last_installment_due_date.date() - loan_created_date.date()).days
        installment_count = math.ceil(day_difference / 7)

    if dana_installment_type == DanaInstallmentType.WEEKLY:
        installment_type = "Minggu"
    elif dana_installment_type == DanaInstallmentType.BIWEEKLY:
        installment_type = "Minggu"
        installment_count = int(dana_installment_count) * 2
    elif dana_installment_type == DanaInstallmentType.MONTHLY:
        installment_type = "Bulan"

    content = {
        "date_today": format_datetime(transaction_time, "d MMMM yyyy", locale='id_ID'),
        "customer_name": detokenize_dana_customer_data.full_name,
        "dob": format_datetime(dana_customer_data.dob, "d MMMM yyyy", locale='id_ID'),
        "customer_nik": detokenize_dana_customer_data.nik,
        "customer_phone": detokenize_dana_customer_data.mobile_number,
        "full_address": dana_customer_data.address,
        "partner_email": partner_email,
        "partner_tnc": partner_tnc,
        "partner_privacy_rule": partner_privacy_rule,
        "loan_amount": format_rupiahs(loan_disbursement_amount, "no_currency"),
        "provision_fee_amount": provision_amount,
        "interest_amount": format_rupiahs(total_interest_amount, "no_currency"),
        "late_fee_rate": agreement_info["lateFeeRate"],
        "maximum_late_fee_amount": format_rupiahs(loan_disbursement_amount, "no_currency"),
        "installment_count": installment_count,
        "installment_type": installment_type,
    }

    # this one for dana cashloan with dinamic installment table
    installment_table_template = (
        '<table style="width:100%;">'
        '<tbody>'
        '<tr>'
        '<td style="text-align:center"><strong>Cicilan</strong></td>'
        '<td><p><strong>Jumlah</strong></p></td>'
        '<td><p><strong>Jatuh Tempo</strong></p></td>'
        '</tr>'
        '{% for payment_number, payment_data in sorted_bills.items %}'
        '<tr>'
        '<td><p style="text-align:center">{{ payment_number }}</p></td>'
        '<td><p>{{ payment_data.payment_amount }}</p></td>'
        '<td><p>{{ payment_data.due_date }}</p></td>'
        '</tr>'
        '{% endfor %}'
        '</tbody>'
        '</table>'
    )

    installment_table_template = Template(installment_table_template)
    installment_table = installment_table_template.render(Context({'sorted_bills': sorted_bills}))

    content.update({"installment_table": installment_table})

    generate_dana_loan_agreement.delay(application.id, loan.id, content)

    hashed_loan_xid = dana_generate_hashed_loan_xid(loan.loan_xid)
    loan_agreement_url = "{}/{}/{}".format(
        settings.BASE_URL, "v1.0/agreement/content", hashed_loan_xid
    )
    return loan_agreement_url, dana_loan_reference.reference_no


def format_bills_into_loan_creation_payload(
    bills: List, product_type: str = DanaProductType.CICIL
) -> Dict:
    dana_tnc_url = "https://a.m.dana.id/resource/htmls/dana-credit/DANA-cicil-tnc.html"
    payload = {
        "partnerReferenceNo": bills[0]["partnerReferenceNo"],
        "merchantId": "1",
        "amount": {"value": bills[0]["amount"], "currency": "IDR"},
        "additionalInfo": {
            "originalOrderAmount": {"value": bills[0]["originalOrderAmount"], "currency": "IDR"},
            "orderInfo": "{}",
            "customerId": bills[0]["customerId"],
            "transTime": bills[0]["transTime"],
            "lenderProductId": bills[0]["lenderProductId"],
            "creditUsageMutation": {"value": bills[0]["creditUsageMutation"], "currency": "IDR"},
            "agreementInfo": {
                "partnerEmail": "help@dana.id",
                "partnerTnc": dana_tnc_url,
                "partnerPrivacyRule": dana_tnc_url,
                "provisionFeeAmount": {"value": "0.00", "currency": "IDR"},
                "lateFeeRate": "0.15",
                "maxLateFeeDays": "120",
            },
            "billDetailList": [],
            "paymentId": bills[0]["txnId"],
            "repaymentPlanList": [],
            # update this logic below when Dana have sent installmentType on SF file loan upload
            # for now, we set as a default value = "WEKKLY" (5 Feb 2025)
            "installmentConfig": {
                "is_crm": True,
                "installmentType": "WEEKLY",
            },
        },
    }

    for bill in bills:
        bill_detail = {
            "billId": bill["billId"],
            "periodNo": bill["periodNo"],
            "principalAmount": {"value": bill["principalAmount"], "currency": "IDR"},
            "interestFeeAmount": {"value": bill["interestFeeAmount"], "currency": "IDR"},
            "lateFeeAmount": {"value": bill["lateFeeAmount"], "currency": "IDR"},
            "totalAmount": {"value": bill["totalAmount"], "currency": "IDR"},
            "dueDate": bill["dueDate"],
        }
        payload["additionalInfo"]["billDetailList"].append(bill_detail)

        repayment_plan_list = {
            "periodNo": bill["periodNo"],
            "principalAmount": {"value": bill["principalAmount"], "currency": "IDR"},
            "interestFeeAmount": {"value": bill["interestFeeAmount"], "currency": "IDR"},
            "totalAmount": {"value": bill["totalAmount"], "currency": "IDR"},
            "dueDate": bill["dueDate"],
        }
        payload["additionalInfo"]["repaymentPlanList"].append(repayment_plan_list)

    return payload


def upload_csv_data_to_oss(upload_async_state, file_path=None):
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
        row.get('billId', 'null'),
        row.get('dueDate', 'null'),
        row.get('periodNo', 'null'),
        row.get('creditUsageMutation', 'null'),
        row.get('principalAmount', 'null'),
        row.get('interestFeeAmount', 'null'),
        row.get('lateFeeAmount', 'null'),
        row.get('totalAmount', 'null'),
        row.get('originalOrderAmount', 'null'),
        row.get('transTime', 'null'),
        row.get('status', 'null'),
        row.get('failCode', 'null'),
        row.get('note', 'null'),
    ]


def process_payment_as_cancel(partner_reference_no: str) -> Tuple:
    """
    Rules To Reject:
    1. Check if existed partner reference
    2. Check if loan is existed
    3. Early return if loan status is already 216 (Canceled) / not yet completed (211, 212)
    4. Check if loan > 220 (Success) and alread transfer (fund_transfer_ts) Cannot cancel
    5. Check if some bill is paid -> Cannot cancel
    6. in payment consult loan status 210-212 still not deducted the account limit
    no need deduct account limit and reduce from account payment
    """
    from juloserver.dana.repayment.tasks import account_reactivation

    CancelResult = namedtuple('LoanResult', ['is_valid', 'is_changed', 'notes'])
    dana_loan_reference = DanaLoanReference.objects.filter(
        partner_reference_no=partner_reference_no
    ).last()

    is_valid = False
    is_changed = False

    if not dana_loan_reference:
        notes = 'partner_reference_no not found, please help check again'
        return CancelResult(is_valid, is_changed, notes)

    if not dana_loan_reference.loan:
        notes = 'loan not found with the partner_reference_no please check again'
        DanaLoanReferenceStatus.objects.update_or_create(
            dana_loan_reference=dana_loan_reference,
            defaults={'status': PaymentReferenceStatus.FAILED},
        )
        return CancelResult(is_valid, is_changed, notes)

    loan = dana_loan_reference.loan

    if loan.status == LoanStatusCodes.CANCELLED_BY_CUSTOMER:
        notes = 'Cannot cancel the loan, because loan is already canceled Please check'
        return CancelResult(is_valid, is_changed, notes)

    is_inactive_loan = False
    if loan.status <= LoanStatusCodes.LENDER_REJECT:
        is_inactive_loan = True
        notes = 'Inactive loan'

    dana_customer_data = loan.account.dana_customer_data
    if dana_customer_data.lender_product_id == DanaProductType.CICIL:
        if loan.status >= LoanStatusCodes.CURRENT:
            notes = 'Cannot cancel the loan, loan status is greater than or equal to 220'
            return CancelResult(is_valid, is_changed, notes)

        if not dana_loan_reference.is_whitelisted:
            notes = 'Cannot cancel the loan, because loan is payment notify flow'
            return CancelResult(is_valid, is_changed, notes)
    else:
        if loan.status > LoanStatusCodes.CURRENT:
            notes = 'Cannot cancel the loan, loan status is greater than 220'
            return CancelResult(is_valid, is_changed, notes)

    list_payment_updated = []
    account_payment_updated = []

    all_status_codes = StatusLookup.objects.filter(status_code__in=PaymentStatusCodes.all())
    status_mapping = defaultdict(int)
    for all_status_code in all_status_codes:
        status_mapping[all_status_code.status_code] = all_status_code

    mapping_total_used_limit = defaultdict(int)
    with transaction.atomic():
        if not is_inactive_loan:
            payments = Payment.objects.select_related('account_payment').filter(loan=loan)
            payment_ids = payments.values_list('id', flat=True)
            dana_payment_bills = DanaPaymentBill.objects.filter(
                payment_id__in=set(payment_ids)
            ).order_by('payment_id')

            payment_dict = {payment.id: payment for payment in payments}

            if not dana_payment_bills:
                notes = 'Dana payment bill not found for this loan, please check'
                return CancelResult(is_valid, is_changed, notes)

            drr_ids = set()
            bill_ids = dana_payment_bills.values_list('bill_id', flat=True)
            dana_repayment_references = (
                DanaRepaymentReference.objects.filter(bill_id__in=bill_ids)
            )

            for drr in dana_repayment_references:
                drr_ids.add(drr.id)

            not_failed_dana_repayment_reference_ids = (
                DanaRepaymentReferenceStatus.objects.values_list(
                    "dana_repayment_reference_id", flat=True
                )
                .filter(dana_repayment_reference_id__in=drr_ids)
                .exclude(status=RepaymentReferenceStatus.FAILED)
            )

            dana_repayment_references = dana_repayment_references.filter(
                id__in=set(not_failed_dana_repayment_reference_ids)
            ).exists()

            if dana_repayment_references:
                notes = (
                    "Can't cancel loan, there is repayment success/pending founded. Please check"
                )
                return CancelResult(is_valid, is_changed, notes)

            # Process Success Change Bill
            for dana_payment_bill in dana_payment_bills.iterator():
                payment = payment_dict[dana_payment_bill.payment_id]
                acc_payment = payment.account_payment
                update_date = timezone.localtime(timezone.now())

                acc_payment_due_amount_after_void = acc_payment.due_amount - payment.due_amount
                acc_payment.due_amount = acc_payment_due_amount_after_void
                acc_payment.principal_amount = F('principal_amount') - payment.installment_principal
                acc_payment.interest_amount = F('interest_amount') - payment.installment_interest
                acc_payment.paid_interest = F('paid_interest') - payment.paid_interest
                acc_payment.paid_principal = F('paid_principal') - payment.paid_principal
                acc_payment.paid_late_fee = F('paid_late_fee') - payment.paid_late_fee
                acc_payment.late_fee_amount = F('late_fee_amount') - payment.late_fee_amount
                acc_payment.udate = update_date

                if acc_payment_due_amount_after_void == 0:
                    acc_payment.status = status_mapping[PaymentStatusCodes.PAID_ON_TIME]
                else:
                    new_status_code = acc_payment.get_status_based_on_due_date()
                    if acc_payment.status != new_status_code:
                        acc_payment.status = status_mapping[new_status_code]

                payment.account_payment = None
                payment.udate = update_date
                account_payment_updated.append(acc_payment)
                list_payment_updated.append(payment)

                total_used_principal = payment.installment_principal - payment.paid_principal
                total_used_interest = payment.installment_interest - payment.paid_interest
                total_used_amount = total_used_principal + total_used_interest
                mapping_total_used_limit[acc_payment.account_id] += total_used_amount

            bulk_update(
                account_payment_updated,
                update_fields=[
                    'udate',
                    'due_amount',
                    'principal_amount',
                    'interest_amount',
                    'paid_interest',
                    'paid_principal',
                    'paid_late_fee',
                    'late_fee_amount',
                    'status',
                ],
                batch_size=30,
            )

            bulk_update(
                list_payment_updated,
                update_fields=[
                    'udate',
                    'account_payment',
                ],
                batch_size=30,
            )

            """
            Handling if loan stuck (211-212), but status is already success
            If status is successful it's mean limit already deduct
            Payment is created, only account payment not created

            If Loan created with insufficient and still not recalculated
            Skip to replenished limit
            """
            if (
                hasattr(dana_loan_reference, 'dana_loan_status')
                and dana_loan_reference.dana_loan_status.status == PaymentReferenceStatus.SUCCESS
            ):
                account_limit = AccountLimit.objects.select_for_update().get(account=loan.account)

                # Need Handling this, to prevent mismatch calculation
                # If loan is have several payment,
                # because on payment there is calculation to replenish Amount
                if mapping_total_used_limit.get(account_limit.account_id):
                    loan_amount = mapping_total_used_limit.get(account_limit.account_id)
                else:
                    partner_loan_request = loan.partnerloanrequest_set.last()
                    loan_amount = partner_loan_request.loan_amount

                insufficient_created = (
                    hasattr(dana_loan_reference, 'danaloanreferenceinsufficienthistory')
                    and not dana_loan_reference.danaloanreferenceinsufficienthistory.is_recalculated
                )

                if not insufficient_created:
                    # Update limit account
                    new_available_limit = account_limit.available_limit + loan_amount
                    new_used_limit = account_limit.used_limit - loan_amount
                    account_limit.update_safely(
                        available_limit=new_available_limit, used_limit=new_used_limit
                    )

        update_dana_loan_cancel_status_and_loan_history(
            loan.id,
            change_reason=PartnershipLoanStatusChangeReason.SETTLEMENT_CANCELED,
        )

        DanaLoanReferenceStatus.objects.update_or_create(
            dana_loan_reference=dana_loan_reference,
            defaults={'status': PaymentReferenceStatus.FAILED},
        )

    execute_after_transaction_safely(lambda: account_reactivation.delay(loan.account.id))

    dana_loan_reference.refresh_from_db()
    notes = "Succesfully to cancel loan"
    is_valid = True
    is_changed = True
    return CancelResult(is_valid, is_changed, notes)


def update_dana_loan_cancel_status_and_loan_history(
    loan_id: int, change_by_id: str = None, change_reason: str = "system triggered"
) -> None:
    from juloserver.loan.services.lender_related import return_lender_balance_amount

    new_status_code = LoanStatusCodes.CANCELLED_BY_CUSTOMER
    status_code = StatusLookup.objects.get_or_none(status_code=new_status_code)
    if not status_code:
        raise JuloException("Status Not Found in status Lookup")

    with transaction.atomic():
        loan = Loan.objects.select_for_update().get(id=loan_id)
        if not loan:
            raise JuloException("Loan Not Found")
        old_status_code = loan.status
        if old_status_code == new_status_code:
            raise JuloException(
                "Can't change Loan Status from %s to %s" % (old_status_code, new_status_code)
            )

        cancelable_loan_status = {
            LoanStatusCodes.INACTIVE,
            LoanStatusCodes.LENDER_APPROVAL,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.CURRENT,
        }

        if old_status_code not in cancelable_loan_status:
            raise JuloException("Current Loan Status not in cancelable_loan_status")

        loan.loan_status = status_code
        loan.save()
        loan_history_data = {
            "loan": loan,
            "status_old": old_status_code,
            "status_new": new_status_code,
            "change_reason": change_reason,
            "change_by_id": change_by_id,
        }
        LoanHistory.objects.create(**loan_history_data)
        loan.refresh_from_db()
        update_is_proven_julo_one(loan)
        return_lender_balance_amount(loan)


def create_or_update_dana_loan(data: Dict) -> Tuple[str, str]:
    dana_loan_reference, _ = proceed_dana_payment(data, is_api=False)
    resume_dana_create_loan(list_dana_loan_references=[dana_loan_reference])
    loan_agreement_url = get_dana_loan_agreement_url(dana_loan_reference)
    return loan_agreement_url, dana_loan_reference.reference_no
