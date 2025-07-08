import re
import csv
import io
import logging
import math
from typing import Tuple, Union

from zipfile import ZipFile

from django.contrib import messages
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import (
    Max,
    Case,
    When,
    F,
    Q,
)
from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpRequest
from django.shortcuts import redirect
from django.utils import timezone

from juloserver.julocore.python2.utils import py2round
from juloserver.channeling_loan.services.permata_services import (
    construct_permata_early_payoff_request_file_content,
)

from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.constants import TransactionMethodCode

from juloserver.channeling_loan.tasks import (
    encrypt_data_and_upload_to_fama_sftp_server,
    encrypt_data_and_upload_to_permata_sftp_server,
    process_upload_smf_disbursement_file_task,
)
from juloserver.channeling_loan.services.general_services import (
    process_loan_for_channeling,
    get_channeling_loan_configuration,
    get_channeling_outstanding_amount,
    create_channeling_loan_send_file_tracking,
    get_next_filename_counter_suffix,
    get_process_approval_response_time_delay_in_minutes,
    get_latest_approval_file_object,
    execute_new_approval_response_process,
    get_response_approval_file,
    get_interest_rate_config,
    get_channeling_days_in_year,
    send_notification_to_slack,
    get_fama_channeling_admin_fee,
    upload_channeling_file_to_oss_and_slack,
)
from juloserver.channeling_loan.services.loan_tagging_services import (
    update_lender_osp_balance,
)
from juloserver.channeling_loan.services.bss_services import (  # noqa
    change_city_to_dati_code,
    get_bss_refno_manual,
    construct_bss_schedule_data,
    get_bss_education_mapping,
)
from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
    LenderOspTransaction,
)
from juloserver.channeling_loan.constants.smf_constants import (
    SMFChannelingConst,
)
from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    BJBDocumentHeaderConst,
    FAMAChannelingConst,
    FAMADocumentHeaderConst,
    FAMAOccupationMappingConst,
    ChannelingConst,
    ChannelingLenderLoanLedgerConst,
    ChannelingActionTypeConst,
    ChannelingLoanApprovalFileConst,
    PermataChannelingConst,
    CONTENT_MIME_TYPE_CSV,
    CONTENT_MIME_TYPE_ZIP,
    CONTENT_MIME_TYPE_TXT,
    BSSChannelingConst,
)

from juloserver.channeling_loan.constants import BSSMaritalStatusConst  # noqa

from juloserver.channeling_loan.constants.bss_constants import BSSDocumentHeaderConst

from juloserver.channeling_loan.forms import (
    RepaymentFileForm,
    ReconciliationFileForm,
)
from juloserver.channeling_loan.utils import (  # noqa
    bjb_format_day,
    bjb_format_datetime,
    get_bjb_education_code,
    get_bjb_gender_code,
    get_bjb_marital_status_code,
    get_bjb_expenses_code,
    get_bjb_income_code,
    get_random_blood_type,
    convert_str_as_time,
    convert_str_as_list,
    convert_str_as_boolean,
    convert_str_as_int_or_none,
    convert_str_as_float_or_none,
    extract_date,
    get_fama_marital_status_code,
    get_fama_education_code,
    format_two_digit,
    format_phone,
    check_loan_duration,
    check_flag_periode,
    get_fama_title_code,
    get_fama_gender,
    get_collectability,
    response_file,
    switch_to_month_if_days,
    bss_format_date,
)
from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.julo.models import (
    Loan,
    Document,
    Payment,
)
from juloserver.channeling_loan.tasks import (
    execute_withdraw_batch_process,
    execute_repayment_process,
)
from juloserver.julo_starter.services.services import determine_application_for_credit_info
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.sdk.services import xls_to_dict

from juloserver.apiv2.models import PdBscoreModelResult
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_account_id_with_prefix(loan_xid):
    return FAMAChannelingConst.PARTNER_CODE + str(loan_xid)


def construct_bjb_response(current_ts, _filter):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    headers = BJBDocumentHeaderConst.LIST
    writer.writerow(headers)

    channeling_loan_statuses = ChannelingLoanStatus.objects.filter(**_filter).order_by('-cdate')
    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        application = determine_application_for_credit_info(loan.account.customer)  # noqa
        loan_product = loan.product  # noqa
        payments = loan.payment_set.order_by('payment_number')
        first_payment = payments.first()  # noqa
        last_payment = payments.last()  # noqa
        random_blood_type = get_random_blood_type()  # noqa
        if channeling_loan_status.channeling_status == ChannelingStatusConst.PENDING:
            status, _ = process_loan_for_channeling(loan)
            if status == "failed":
                continue
        data = []
        default_values = BJBDocumentHeaderConst.DEFAULT_VALUE
        function_mapping = BJBDocumentHeaderConst.FUNCTION_MAPPING
        field_mapping = BJBDocumentHeaderConst.FIELD_MAPPING
        for header in headers:
            value = ""
            if header in default_values.keys():
                value = default_values[header]
            else:
                value = eval(field_mapping[header])

            if header in function_mapping.keys():
                value = eval(function_mapping[header])(value)
            data.append(str(value or ""))
        writer.writerow(data)

    return response_file(
        content_type=CONTENT_MIME_TYPE_CSV,
        content=buffer.getvalue().encode('utf-8'),
        filename="{}_channeling_{}.csv".format(
            ChannelingConst.BJB, current_ts.strftime("%Y%m%d%H%M")
        ),
    )


def construct_fama_response(current_ts, _filter, user_id, upload=False, counter=0):
    base_logger_data = {
        "action": "construct_fama_response",
        "_filter": _filter,
        "user_id": user_id,
        "upload": upload,
        "counter": counter,
    }
    logger.info(
        {
            **base_logger_data,
            "message": "Start constructing FAMA response",
        }
    )
    if counter >= FAMAChannelingConst.MAX_CONSTRUCT_DISBURSEMENT_TIMES:
        logger.info(
            {
                **base_logger_data,
                "message": "Max construct disbursement times reached",
            }
        )
        return None

    datefile = current_ts.strftime("%Y%m%d")

    byteIo = io.BytesIO()
    zf = ZipFile(byteIo, 'w')

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Application_XID", "disetujui"])

    all_data = {}
    sum_amount = {}
    for doc_type in FAMADocumentHeaderConst.LIST:
        all_data[doc_type] = []
        sum_amount[doc_type] = 0

    account_ids = []
    is_has_duplicated_nik = False
    channeling_loan_statuses = (
        ChannelingLoanStatus.objects.filter(**_filter)
        .exclude(channeling_status=ChannelingStatusConst.PREFUND)
        .order_by("-cdate")
    )

    if not channeling_loan_statuses:
        send_notification_to_slack(
            """
            Here's your FAMA disbursement file creation info:
            No file was sent to FAMA because no loan successfully constructed.
            """,
            settings.FAMA_SLACK_NOTIFICATION_CHANNEL,
        )
        return

    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        last_loan_xid = ""  # noqa
        last_loan_transfer_ts = ""  # noqa
        last_loan = loan.account.loan_set.filter(
            lender__lender_name="fama_channeling", loan_status__gte=LoanStatusCodes.CURRENT
        ).last()
        if last_loan:
            last_loan_xid = last_loan.loan_xid  # noqa
            last_loan_transfer_ts = timezone.localtime(last_loan.fund_transfer_ts)  # noqa

        if upload:
            """
            replace fund transfer ts date with today since the data is send today
            will set on loan object directly, since we dont save/update_safely the object
            """
            loan.fund_transfer_ts = (
                timezone.localtime(loan.fund_transfer_ts).replace(
                    day=current_ts.day, month=current_ts.month, year=current_ts.year
                )
                if loan.fund_transfer_ts
                else loan.fund_transfer_ts
            )

        transaction_method = extract_transaction_detail()  # noqa
        application = loan.get_application  # noqa
        application_190 = application.applicationhistory_set.filter(status_new=190).last()  # noqa
        loan_product = loan.product  # noqa
        payments = loan.payment_set.order_by('payment_number')
        first_payment = payments.first()  # noqa
        last_payment = payments.last()  # noqa
        loan_total_days, flag_periode = switch_to_month_if_days(payments, loan)
        outstanding_amount = get_channeling_outstanding_amount(loan, ChannelingConst.FAMA)
        outstanding_amount_line = format_two_digit(outstanding_amount)  # noqa
        interest_amount_line = format_two_digit(  # noqa
            channeling_loan_status.channeling_interest_amount
        )
        partner_principal_balance = loan.loan_amount  # noqa

        if loan_total_days < 0:
            continue

        # validate duplicate nik except success
        if loan.account.id in account_ids:
            if channeling_loan_status.channeling_status == ChannelingStatusConst.SUCCESS:
                continue

            # channeling loan status stuck at PENDING, will be sent to FAMA in the next batch
            is_has_duplicated_nik = True
            continue

        function_mapping = FAMADocumentHeaderConst.FUNCTION_MAPPING
        if channeling_loan_status.channeling_status == ChannelingStatusConst.PENDING:
            status, _ = process_loan_for_channeling(loan)
            if status == "failed":
                continue

        account_ids.append(loan.account.id)
        loans = Loan.objects.filter(
            customer=loan.customer, loan_status__gte=LoanStatusCodes.CURRENT
        ).exclude(pk=loan.id)

        is_ftc = not loans.exists()
        ftc_detail = FAMAChannelingConst.FTC_NEW if is_ftc else FAMAChannelingConst.FTC_REPEATED
        bscore_model_result = (
            PdBscoreModelResult.objects.filter(
                customer_id=loan.customer_id, pgood__isnull=False
            )
            .order_by("cdate")
            .last()
        )
        b_score = None
        if bscore_model_result and bscore_model_result.pgood is not None:
            b_score = math.floor(bscore_model_result.pgood * 100) / 100  # noqa

        if b_score is None:
            continue

        for doc_type in FAMADocumentHeaderConst.LIST:
            new_payments = payments
            if doc_type != FAMADocumentHeaderConst.PAYMENT:
                new_payments = [first_payment]
                sum_amount[doc_type] += outstanding_amount
            for payment in new_payments:
                channeling_payment = payment.channelingloanpayment_set.last()  # noqa
                if not channeling_payment:
                    continue
                if doc_type == FAMADocumentHeaderConst.PAYMENT:
                    new_due_amount = channeling_payment.original_outstanding_amount
                    interest_amount = format_two_digit(channeling_payment.interest_amount)  # noqa
                    principal_amount = format_two_digit(channeling_payment.principal_amount)  # noqa
                    instalment_amount = format_two_digit(new_due_amount)  # noqa
                    sum_amount[doc_type] += new_due_amount

                detail = []
                dpd = 0  # noqa
                for field, value in eval('FAMADocumentHeaderConst.%s_FIELD' % doc_type).items():
                    try:
                        if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
                            value = eval(value)
                            if field in FAMADocumentHeaderConst.DATE_FORMAT_FIELD:
                                value = extract_date(value)
                            elif field in FAMADocumentHeaderConst.DATI_FIELD:
                                value = change_city_to_dati_code(value)
                            elif field in function_mapping.keys():
                                value = eval(function_mapping[field])(value)
                            elif value and field in FAMADocumentHeaderConst.SANITIZE_FIELD:
                                value = ' '.join(
                                    re.sub(r'[^a-zA-Z0-9]', ' ', value.strip()).split()
                                )
                        if field == 'Occupation_Code':
                            value = get_occupation_code(
                                application.job_industry, application.job_description
                            )
                        if field == 'Company_Name' and not value:
                            value = 'NA'
                    except Exception as e:
                        value = str(value)

                        sentry_client.captureException()

                        logger.error(
                            {
                                **base_logger_data,
                                "message": "error parsing value on construct_fama_response",
                                "error": repr(e),
                            }
                        )

                    detail.append(str(value))

                # need to add NU field in spare_field 1 to Loan Contract
                spare_number = FAMADocumentHeaderConst.SPAREFIELD_NUMBER
                if doc_type == FAMADocumentHeaderConst.LOAN:
                    spare_number -= 3
                    detail += ["NU"]
                    detail += [str(channeling_loan_status.admin_fee)]
                    detail += [ftc_detail]

                detail += ["" for x in range(spare_number)]
                all_data[doc_type].append("|".join(detail))
        writer.writerow([loan.loan_xid, "y/n"])

    channeling_type = ChannelingConst.FAMA
    action_type = ChannelingActionTypeConst.DISBURSEMENT

    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )
    filename = "{}_{}_{}{}.csv".format(
        FAMAChannelingConst.PARTNER_CODE, "Approval", datefile, filename_counter_suffix
    )
    csv_content = buffer.getvalue().encode('utf-8')
    zf.writestr(filename, csv_content)
    encrypt_data_and_upload_to_fama_sftp_server.delay(csv_content, filename + '.gpg')

    for doc_type in FAMADocumentHeaderConst.LIST:
        headers = []
        record_number = len(all_data[doc_type])  # noqa

        list_headers = FAMADocumentHeaderConst.PRODUCT_HEADER
        if doc_type != FAMADocumentHeaderConst.PRODUCT:
            list_headers = FAMADocumentHeaderConst.NON_PRODUCT_HEADER
        for field, value in list_headers.items():
            if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
                value = eval(value)
            if (
                FAMADocumentHeaderConst.APPLICATION == doc_type
                and field == FAMADocumentHeaderConst.SUM_AMOUNT
            ):
                value = 0
            elif field == FAMADocumentHeaderConst.SUM_AMOUNT:
                value = format_two_digit(sum_amount[doc_type])
            headers.append(str(value))
        all_data[doc_type] = ["|".join(headers)] + all_data[doc_type]

        txt_content = "\n".join(all_data[doc_type])
        filename = "{}_{}_{}{}.txt".format(
            FAMAChannelingConst.PARTNER_CODE,
            FAMADocumentHeaderConst.FILENAME_MAP[doc_type],
            datefile,
            filename_counter_suffix,
        )
        encrypt_data_and_upload_to_fama_sftp_server.delay(txt_content, filename + '.gpg')
        zf.writestr(filename, txt_content)
    zf.close()

    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
        user_id=user_id,
    )

    # upload zip result to OSS
    filename_zip = '{}_channeling_{}{}.zip'.format(
        channeling_type, current_ts.strftime("%Y%m%d%H%M"), filename_counter_suffix
    )
    result_file = response_file(
        content_type=CONTENT_MIME_TYPE_ZIP,
        content=byteIo.getvalue(),
        filename=filename_zip,
    )
    document_id = None
    if upload:
        lender = LenderCurrent.objects.get_or_none(lender_name=ChannelingConst.LENDER_FAMA)
        document_remote_filepath = "channeling_loan/lender_{}/{}".format(lender.id, filename_zip)

        document_id = upload_channeling_file_to_oss_and_slack(
            content=byteIo.getvalue(),
            document_remote_filepath=document_remote_filepath,
            lender_id=lender.id,
            filename=filename,
            document_type=ChannelingLoanApprovalFileConst.DOCUMENT_TYPE,
            channeling_type=channeling_type,
            channeling_action_type=FAMAChannelingConst.DISBURSEMENT,
            slack_channel=settings.FAMA_SLACK_NOTIFICATION_CHANNEL,
        )

    if is_has_duplicated_nik:
        # send a new dedicated batch to FAMA that contains some loans got duplicated NIK
        # recurse the function until there is no duplicated NIK (is_has_duplicated_nik = False)
        construct_fama_response(current_ts, _filter, user_id, upload=upload, counter=counter + 1)

    logger.info(
        {
            **base_logger_data,
            "message": "FAMA response constructed successfully",
            "filename": filename_zip,
            "document_id": document_id,
        }
    )
    return result_file


def extract_transaction_detail():
    transaction_method = TransactionMethod.objects.filter(id=TransactionMethodCode.SELF.code).last()

    return {
        'comodity_code': 'Cash',
        'producer': transaction_method.fe_display_name,
        'goods_type': transaction_method.fe_display_name,
        'type_loan': 'P11',
    }


def get_occupation_code(job_industry, job_description):
    return FAMAOccupationMappingConst.LIST.get(
        "{},{}".format(job_industry, job_description),
        FAMAOccupationMappingConst.LIST["DEFAULT_VALUE"]
    )


def construct_fama_repayment_response(request, channeling_type, current_ts, user_id):
    if channeling_type != ChannelingConst.FAMA:
        return False, "Wrong channeling type"

    upload_form = RepaymentFileForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        return False, "Invalid form"

    file_ = upload_form.cleaned_data['repayment_file_field']
    extension = file_.name.split('.')[-1]

    if extension not in ChannelingConst.FILE_UPLOAD_EXTENSIONS:
        return False, "Please upload correct file excel"

    try:
        excel_datas = xls_to_dict(file_)
        all_data = []
        logs = "FAILED"
        error_counts = 0
        for sheet in excel_datas:
            sum_amount = 0
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                logs += "\nRow: %d   |   " % (idx_rpw + 2)
                data = []
                if 'payment_amount' not in row:
                    logs += "Error: key payment_amount not found\n"
                    error_counts += 1
                    continue
                sum_amount += int(row['payment_amount'])
                key_errors = []
                for field in FAMADocumentHeaderConst.REPAYMENT_FIELD.keys():
                    if field.lower() not in row:
                        key_errors.append(field.lower())
                        continue
                    data.append(row[field.lower()])
                if key_errors:
                    logs += "Error: key errors %s" % (', '.join(key_errors))
                    error_counts += 1
                    continue
                data += ["" for x in range(FAMADocumentHeaderConst.SPAREFIELD_NUMBER)]
                all_data.append("|".join(data))

        if error_counts:
            return False, logs

        headers = []
        record_number = len(all_data)  # noqa
        datefile = current_ts.strftime(FAMAChannelingConst.FILENAME_DATE_FORMAT)
        list_headers = FAMADocumentHeaderConst.NON_PRODUCT_HEADER
        for field, value in list_headers.items():
            if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
                value = eval(value)
            headers.append(str(value))
        all_data = ["|".join(headers)] + all_data

        txt_content = "\n".join(all_data)

        action_type = ChannelingActionTypeConst.REPAYMENT

        filename_counter_suffix = get_next_filename_counter_suffix(
            channeling_type=channeling_type,
            action_type=action_type,
            current_ts=current_ts,
        )
        filename = "{}_{}_{}{}.txt".format(
            FAMAChannelingConst.PARTNER_CODE,
            FAMADocumentHeaderConst.FILENAME_MAP[FAMADocumentHeaderConst.REPAYMENT],
            datefile,
            filename_counter_suffix,
        )

        encrypt_data_and_upload_to_fama_sftp_server.delay(txt_content, filename + '.gpg')

        create_channeling_loan_send_file_tracking(
            channeling_type=channeling_type,
            action_type=action_type,
            user_id=user_id,
        )

        return True, txt_content

    except Exception as error:
        return False, str(error)


def construct_fama_reconciliation_response(request, channeling_type, current_ts, user_id):
    if channeling_type != ChannelingConst.FAMA:
        return False, "Wrong channeling type"

    upload_form = ReconciliationFileForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        return False, "Invalid form"

    file_ = upload_form.cleaned_data['reconciliation_file_field']
    extension = file_.name.split('.')[-1]

    if extension not in ChannelingConst.FILE_UPLOAD_EXTENSIONS:
        return False, "Please upload correct file excel"

    try:
        excel_datas = xls_to_dict(file_)
        all_data = []
        logs = "FAILED"
        error_counts = 0
        for sheet in excel_datas:
            sum_amount = 0
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                logs += "\nRow: %d   |   " % (idx_rpw + 2)
                data = []
                sum_amount += int(row['outstanding_amount'])
                key_errors = []
                for field in FAMADocumentHeaderConst.RECONCILIATION_FIELD.keys():
                    if field.lower() not in row:
                        key_errors.append(field.lower())
                        continue
                    data.append(row[field.lower()])
                if key_errors:
                    logs += "Error: key errors %s" % (', '.join(key_errors))
                    error_counts += 1
                    continue
                data += ["" for x in range(FAMADocumentHeaderConst.SPAREFIELD_NUMBER)]
                all_data.append("|".join(data))

        if error_counts:
            return False, logs

        headers = []
        record_number = len(all_data)  # noqa
        datefile = current_ts.strftime("%Y%m%d")
        list_headers = FAMADocumentHeaderConst.NON_PRODUCT_HEADER
        for field, value in list_headers.items():
            if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
                value = eval(value)
            headers.append(str(value))
        all_data = ["|".join(headers)] + all_data

        txt_content = "\n".join(all_data)

        action_type = ChannelingActionTypeConst.RECONCILIATION

        filename_counter_suffix = get_next_filename_counter_suffix(
            channeling_type=channeling_type,
            action_type=action_type,
            current_ts=current_ts,
        )

        datefile = current_ts.strftime("%Y%m%d")
        filename = "{}_{}_{}{}.txt".format(
            FAMAChannelingConst.PARTNER_CODE,
            FAMADocumentHeaderConst.FILENAME_MAP[FAMADocumentHeaderConst.RECONCILIATION],
            datefile,
            filename_counter_suffix,
        )

        encrypt_data_and_upload_to_fama_sftp_server.delay(txt_content, filename + '.gpg')

        create_channeling_loan_send_file_tracking(
            channeling_type=channeling_type,
            action_type=action_type,
            user_id=user_id,
        )

        return True, txt_content

    except Exception as error:
        return False, str(error)


def construct_fama_reconciliation(encrypt=True, file_type="txt", current_ts=None):
    channeling_type = ChannelingConst.FAMA
    action_type = ChannelingActionTypeConst.RECONCILIATION
    if not current_ts:
        current_ts = timezone.localtime(timezone.now())

    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    lender_name = (channeling_loan_config.get('general', {})).get('LENDER_NAME', None)
    if not lender_name:
        logger.info(
            {
                "action": "construct_fama_reconciliation_response",
                "message": "Lender name not found",
            }
        )

    loans = (
        Loan.objects.annotate(
            paid_off_cdate=Max(
                Case(
                    When(
                        loanhistory__status_new=LoanStatusCodes.PAID_OFF,
                        then=F('loanhistory__cdate'),
                    )
                )
            )
        )
        .filter(
            lender__lender_name=lender_name,
            loan_status__gte=LoanStatusCodes.CURRENT,
            loan_status__lte=LoanStatusCodes.PAID_OFF,
        )
        .filter(
            Q(paid_off_cdate__isnull=True) | Q(paid_off_cdate__date__month=current_ts.date().month)
        )
        .order_by('-cdate')
    )

    if file_type == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(FAMADocumentHeaderConst.RECONCILIATION_FIELD.keys())

    all_data = []
    sum_amount = 0
    for loan in loans:
        detail = []
        payments = loan.payment_set.normal().order_by('payment_number')
        payment = payments.first()
        function_mapping = FAMADocumentHeaderConst.FUNCTION_MAPPING
        doc_type = FAMADocumentHeaderConst.RECONCILIATION
        if not payment:
            continue

        dpd_payment = payments.exclude(due_amount=0).first()
        date_diff = 0
        if dpd_payment:
            date_diff = (current_ts.date() - dpd_payment.due_date).days

        dpd = date_diff if date_diff > 0 else 0  # noqa
        channeling_payment = payment.channelingloanpayment_set.last()  # noqa
        if not channeling_payment:
            continue

        (
            outstanding_amount,
            principal_due,  # noqa
            interest_due,  # noqa
            outstanding_principal,  # noqa
            outstanding_interest  # noqa
        ) = recon_group_amount(payments)
        if outstanding_amount:
            sum_amount += outstanding_amount
        for field, value in eval('FAMADocumentHeaderConst.%s_FIELD' % doc_type).items():

            if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
                value = eval(value)
                if field in FAMADocumentHeaderConst.DATE_FORMAT_FIELD:
                    value = extract_date(value)
                elif field in function_mapping.keys():
                    value = eval(function_mapping[field])(value)
            detail.append(str(value))

        if file_type == "csv":
            writer.writerow(detail)

        detail += ["" for x in range(FAMADocumentHeaderConst.SPAREFIELD_NUMBER)]
        all_data.append("|".join(detail))

    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )

    datefile = current_ts.strftime("%Y%m%d")
    filename = "{}_{}_{}{}".format(
        FAMAChannelingConst.PARTNER_CODE,
        FAMADocumentHeaderConst.FILENAME_MAP[FAMADocumentHeaderConst.RECONCILIATION],
        datefile,
        filename_counter_suffix,
    )

    headers = []
    record_number = len(all_data)  # noqa
    list_headers = FAMADocumentHeaderConst.NON_PRODUCT_HEADER
    for field, value in list_headers.items():
        if field not in FAMADocumentHeaderConst.SKIP_CHECKER:
            value = eval(value)
        headers.append(str(value))
    all_data = ["|".join(headers)] + all_data

    txt_content = "\n".join(all_data)

    if not encrypt:
        if file_type == "csv":
            csv_content = buffer.getvalue().encode('utf-8')
            upload_file_as_bytes_to_oss.delay(
                settings.FAMA_OSS_SFTP_BUCKET,
                csv_content,
                "{}{}".format(settings.FAMA_OSS_SFTP_BASE_DIR, filename + '.csv')
            )
        else:
            upload_file_as_bytes_to_oss.delay(
                settings.FAMA_OSS_SFTP_BUCKET,
                str(txt_content),
                "{}{}".format(settings.FAMA_OSS_SFTP_BASE_DIR, filename + '.txt')
            )
    else:
        encrypt_data_and_upload_to_fama_sftp_server.delay(txt_content, filename + '.txt.gpg')

    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
    )
    return filename, txt_content


def recon_group_amount(payments):
    principal_due = 0
    interest_due = 0
    outstanding_interest = 0
    outstanding_principal = 0

    for payment in payments:
        channeling_payment_event = payment.channelingpaymentevent_set.last()

        if channeling_payment_event:
            principal_due += channeling_payment_event.outstanding_principal
            interest_due += channeling_payment_event.outstanding_interest
        else:
            principal_due = None
            interest_due = None
            break

    outstanding_principal = principal_due
    outstanding_interest = interest_due

    total = None
    if outstanding_principal is not None and outstanding_interest is not None:
        total = outstanding_principal + outstanding_interest

    return [total, principal_due, interest_due, outstanding_principal, outstanding_interest]


def execute_withdraw_batch_service(form_data):
    # Create lender osp account and do the tagging
    balance_amount = form_data['balance_amount']
    lender_osp_account = form_data['lender_osp_account']
    if not lender_osp_account:
        raise Exception('lender_osp_account with id {} not found'.format(lender_osp_account))
    LenderOspTransaction.objects.create(
        balance_amount=balance_amount,
        lender_osp_account=lender_osp_account,
        transaction_type=ChannelingLenderLoanLedgerConst.WITHDRAWAL,
    )
    update_lender_osp_balance(
        lender_osp_account,
        lender_osp_account.balance_amount + balance_amount,
        lender_osp_account.fund_by_lender,
        lender_osp_account.fund_by_julo,
        reason='initial_tag',
    )
    lender_osp_account.update_safely(
        balance_amount=lender_osp_account.balance_amount + balance_amount,
    )

    execute_withdraw_batch_process.delay(lender_osp_account.id)


def execute_repayment_service(form_data):
    balance_amount = form_data['balance_amount']
    lender_osp_account = form_data['lender_osp_account']
    LenderOspTransaction.objects.create(
        balance_amount=balance_amount,
        lender_osp_account=lender_osp_account,
        transaction_type=ChannelingLenderLoanLedgerConst.REPAYMENT,
    )
    execute_repayment_process.delay(lender_osp_account, balance_amount)


def get_approval_response(
    request: HttpRequest, channeling_type: str, file_type: str
) -> HttpResponse:
    time_delay_in_minutes = get_process_approval_response_time_delay_in_minutes(
        channeling_type=channeling_type
    )
    base_url = reverse('channeling_loan_portal:list', args=[channeling_type])
    approval_file = get_latest_approval_file_object(
        channeling_type=channeling_type,
        file_type=file_type,
        time_delay_in_minutes=time_delay_in_minutes,
    )

    if not approval_file or not approval_file.is_processed:
        if not approval_file:
            execute_new_approval_response_process(
                channeling_type=channeling_type, file_type=file_type
            )

        # show message if file is being processed (newly created or unprocessed)
        messages.info(
            request,
            ChannelingLoanApprovalFileConst.BEING_PROCESSED_MESSAGE.format(time_delay_in_minutes),
        )
        return redirect(base_url)

    if approval_file.is_processed_succeed:
        return get_response_approval_file(approval_file_document_id=approval_file.document_id)

    if approval_file.is_processed_failed:
        messages.error(request, ChannelingLoanApprovalFileConst.ERROR_PROCESSED_MESSAGE)
        return redirect(base_url)


def process_permata_early_payoff_request(
    csv_file: UploadedFile, user_id: int
) -> Tuple[bool, Union[str, HttpResponse]]:
    try:
        dict_rows = list(xls_to_dict(csv_file).values())[0]
    except Exception:
        return False, "Early payoff file has invalid data"

    success, txt_content = construct_permata_early_payoff_request_file_content(dict_rows=dict_rows)
    if not success:
        return False, txt_content

    channeling_type = ChannelingConst.PERMATA
    action_type = ChannelingActionTypeConst.EARLY_PAYOFF
    current_ts = timezone.localtime(timezone.now())

    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )
    filename = "{}_EarlyPayoff_{}{}.txt".format(
        PermataChannelingConst.PARTNER_NAME,
        current_ts.strftime("%d%m%Y"),
        filename_counter_suffix,
    )

    encrypt_data_and_upload_to_permata_sftp_server.delay(
        content=txt_content,
        filename="{}.gpg".format(filename),
    )

    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
        user_id=user_id,
    )

    return True, response_file(
        content_type=CONTENT_MIME_TYPE_TXT,
        content=txt_content,
        filename=filename,
    )


def update_admin_fee_fama(
    procesed_channeling_loan_statuses, current_ts, channeling_loan_config=None
):
    channeling_type = ChannelingConst.FAMA
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)

    if not channeling_loan_config:
        logger.info(
            {
                'method': 'update_admin_fee_fama',
                'message': 'channeling config not found',
            }
        )
        return

    (_, _, total_interest_percentage) = get_interest_rate_config(
        channeling_type, channeling_loan_config, False
    )

    with transaction.atomic():
        for channeling_loan_status in procesed_channeling_loan_statuses:
            loan = channeling_loan_status.loan
            first_payment = loan.payment_set.order_by('payment_number').first()
            start_date = current_ts.date()
            diff_date = (first_payment.due_date - start_date).days + 1
            days_in_year = get_channeling_days_in_year(channeling_type, channeling_loan_config)
            daily_interest_fee = py2round(
                diff_date * total_interest_percentage / days_in_year * loan.loan_amount
            )

            channeling_loan_payment = (
                first_payment.channelingloanpayment_set.filter(channeling_type=channeling_type)
                .order_by('payment_id')
                .first()
            )
            if not channeling_loan_payment:
                continue

            logger.info(
                {
                    'method': 'update_admin_fee_fama',
                    'channeling_loan_payment': channeling_loan_payment,
                    'old_actual_daily_interest': channeling_loan_payment.actual_daily_interest,
                    'new_actual_daily_interest': daily_interest_fee,
                }
            )
            channeling_loan_payment.update_safely(actual_daily_interest=daily_interest_fee)
            admin_fee = get_fama_channeling_admin_fee(
                channeling_loan_status, channeling_loan_config
            )
            channeling_loan_status.update_safely(admin_fee=admin_fee)


def construct_smf_response(current_ts, _filter, user_id):
    channeling_type = ChannelingConst.SMF
    action_type = ChannelingActionTypeConst.DISBURSEMENT

    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )
    filename = "{}_{}_{}{}.xls".format(
        SMFChannelingConst.PARTNER_CODE,
        action_type,
        current_ts.strftime("%Y%m%d"),
        filename_counter_suffix
    )
    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
        user_id=user_id,
    )
    document = Document.objects.create(
        document_source=user_id,
        document_type="smf_disbursement",
        filename=filename,
    )
    process_upload_smf_disbursement_file_task.delay(_filter, document.id, user_id)
    return filename


def construct_bss_response(current_ts, _filter, user_id):
    channeling_type = ChannelingConst.BSS
    action_type = ChannelingActionTypeConst.DISBURSEMENT

    channeling_loan_config = get_channeling_loan_configuration(ChannelingConst.BSS)
    effective_rate = BSSChannelingConst.EFFECTIVERATE
    if channeling_loan_config:
        interest_rate = channeling_loan_config["general"]["INTEREST_PERCENTAGE"]
        risk_premium_rate = channeling_loan_config["general"]["RISK_PREMIUM_PERCENTAGE"]
        effective_rate = interest_rate + risk_premium_rate
    channeling_type_config = channeling_loan_config['general']['CHANNELING_TYPE']
    if channeling_type_config != ChannelingConst.MANUAL_CHANNELING_TYPE:
        logger.error(
            {
                'action': 'juloserver.channeling_loan.services.construct_bss_response',
                'message': 'this function for manual only',
            }
        )
        return

    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )

    channeling_loan_statuses = (
        ChannelingLoanStatus.objects.filter(**_filter)
        .exclude(channeling_status=ChannelingStatusConst.PREFUND)
        .order_by("-cdate")
    )

    all_data_csv = {}
    datefile = current_ts.strftime("%Y%m%d")
    byteIo = io.BytesIO()
    zf = ZipFile(byteIo, 'w')
    error = ''
    total_error = 0

    for doc_type in BSSDocumentHeaderConst.LIST:
        all_data_csv[doc_type] = []

    function_mapping = BSSDocumentHeaderConst.FUNCTION_MAPPING

    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        application = loan.get_application
        last_education = get_bss_education_mapping(is_manual=True).get(
            application.last_education, ""
        )
        if not last_education:
            error += "Loan ID : {} | Doc type : {} | Last education not found ".format(
                loan.id, doc_type
            )
        first_payment = Payment.objects.filter(loan=loan).order_by('due_date').first()
        if not any([application, first_payment, effective_rate]):
            continue
        status, _ = process_loan_for_channeling(loan)
        if status == "failed":
            continue
        for doc_type in BSSDocumentHeaderConst.LIST:
            try:
                data = []
                for field, value in eval('BSSDocumentHeaderConst.%s_FIELD' % doc_type).items():
                    if field not in BSSDocumentHeaderConst.SKIP_CHECKER:
                        value = eval(value)
                        if field in BSSDocumentHeaderConst.DATE_FORMAT_FIELD:
                            value = bss_format_date(value)
                        if field in BSSDocumentHeaderConst.DATI_FIELD:
                            value = change_city_to_dati_code(value)
                        if doc_type == BSSDocumentHeaderConst.SCHEDULE:
                            value = construct_bss_schedule_data(loan, is_manual=True)
                            grouped_data = []
                            last_index = 0
                            i = 0
                            for key, data in value.items():
                                parts = key.split('[')
                                index = int(parts[1][:-1])
                                if index != last_index:
                                    if grouped_data:
                                        convert_to_str = ["|".join(map(str, grouped_data))]
                                        all_data_csv[doc_type].append(convert_to_str)
                                    grouped_data = []
                                grouped_data.append(data)
                                last_index = index
                                i += 1
                                if i == len(value):
                                    convert_to_str = ["|".join(map(str, grouped_data))]
                                    all_data_csv[doc_type].append(convert_to_str)
                            continue
                        if field in function_mapping.keys():
                            value = eval(function_mapping[field])(value)
                    data.append(value)
                if doc_type != BSSDocumentHeaderConst.SCHEDULE:
                    convert_to_str = ["|".join(map(str, data))]
                    all_data_csv[doc_type].append(convert_to_str)
            except Exception as e:
                error += "Loan ID : {} | Doc type : {} | error : {} ".format(
                    loan.id, doc_type, str(e)
                )
                total_error += 1

    for doc_type in BSSDocumentHeaderConst.LIST:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows(all_data_csv[doc_type])
        filename = "{}_{}_{}{}.csv".format(
            channeling_type, doc_type, datefile, filename_counter_suffix
        )
        csv_content = buffer.getvalue().encode('utf-8')
        zf.writestr(filename, csv_content)

    zf.close()
    if len(error):
        logger.error(
            {
                'action': 'juloserver.channeling_loan.services.construct_bss_response',
                'message': error,
            }
        )

    lender = LenderCurrent.objects.get_or_none(lender_name='bss_channeling')
    filename = '{}_channeling_{}{}.zip'.format(
        channeling_type, current_ts.strftime("%Y%m%d%H%M"), filename_counter_suffix
    )
    document_remote_filepath = "channeling_loan/lender_{}/{}".format(lender.id, filename)

    result_file = response_file(
        content_type=CONTENT_MIME_TYPE_ZIP,
        content=byteIo.getvalue(),
        filename=filename,
    )

    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
        user_id=user_id,
    )

    upload_file_as_bytes_to_oss(
        bucket_name=settings.OSS_MEDIA_BUCKET,
        file_bytes=byteIo.getvalue(),
        remote_filepath=document_remote_filepath,
    )

    document = Document.objects.create(
        document_source=user_id,
        document_type="bss_disbursement",
        filename=filename,
        url=document_remote_filepath,
    )
    document.refresh_from_db()
    document_id = document.id

    send_notification_to_slack(
        """
        Here's your BSS disbursement link file {}
        this link expiry time only 2 minutes
        if the link is already expired, please ask engineer to manually download it
        with document_id {}, Total data : {}, Total Loan Error :{}
        """.format(
            document.document_url, document_id, len(channeling_loan_statuses), total_error
        ),
        settings.BSS_SLACK_NOTIFICATION_CHANNEL,
    )
    return result_file
