import csv
import io
import datetime
import re
import logging
from typing import Tuple, Optional, Dict, List

from django.conf import settings
from django.utils import timezone
from pyexcel_xls import get_data as get_data_xls

from zipfile import ZipFile

from juloserver.channeling_loan.clients import get_permata_sftp_client
from juloserver.channeling_loan.constants import (
    PermataDocumentHeaderConst,
    PermataChannelingConst,
    ChannelingStatusConst,
    ChannelingConst,
    ChannelingActionTypeConst,
    CONTENT_MIME_TYPE_ZIP,
    PermataEarlyPayoffConst,
)
from juloserver.channeling_loan.exceptions import PermataApprovalFileInvalidFormat
from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
    PermataDisbursementAgun,
    PermataDisbursementCif,
    PermataDisbursementFin,
    PermataDisbursementSipd,
    PermataDisbursementSlik,
    PermataPayment,
    PermataReconciliation,
    ChannelingLoanAddress,
)
from juloserver.channeling_loan.services.general_services import (
    process_loan_for_channeling,
    get_next_filename_counter_suffix,
    create_channeling_loan_send_file_tracking,
    decrypt_data,
    SFTPProcess,
)
from juloserver.channeling_loan.tasks import encrypt_data_and_upload_to_permata_sftp_server
from juloserver.channeling_loan.utils import (
    response_file,
    convert_datetime_string_to_other_format,
    replace_gpg_encrypted_file_name,
    padding_words,
)
from juloserver.julo.models import PaymentEvent

logger = logging.getLogger(__name__)


def get_channeling_loan_address(loan):
    # unused for now, will use when decision whether to use ana/ops data
    application = loan.get_application
    if not application:
        return None

    channeling_loan_address = ChannelingLoanAddress.objects.filter(application_id=application.id)

    return channeling_loan_address


def construct_permata_response(current_ts, _filter, user_id, file_type):
    """
    will be construction txt.gpg file to upload,
    hanlding case for disbursement, repayment, and reconciliation separately.
    """
    channeling_type = ChannelingConst.PERMATA
    byteIo = io.BytesIO()
    zf = ZipFile(byteIo, "w")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Application_XID", "disetujui"])

    all_data = []
    if file_type == ChannelingActionTypeConst.DISBURSEMENT:
        all_data = construct_permata_response_disbursement(_filter, channeling_type)
    elif file_type == ChannelingActionTypeConst.REPAYMENT:
        all_data = construct_permata_response_repayment(_filter, channeling_type)
    elif file_type == ChannelingActionTypeConst.RECONCILIATION:
        all_data = construct_permata_response_reconciliation()

    action_type = ChannelingActionTypeConst.DISBURSEMENT
    filename_counter_suffix = get_next_filename_counter_suffix(
        channeling_type=channeling_type,
        action_type=action_type,
        current_ts=current_ts,
    )

    for field, value in all_data.items():
        txt_content = "\n".join(all_data[field])
        if field == PermataDocumentHeaderConst.RECONCILIATION_CHANNELING:
            # recon have different name
            filename = "{}_{}_{}{}.txt".format(
                PermataChannelingConst.PARTNER_RECONCILIATION_CODE,
                PermataChannelingConst.PARTNER_CODE,
                field,
                current_ts.strftime("%m%Y"),
            )
        else:
            filename = "{}_{}_{}{}.txt".format(
                PermataChannelingConst.PARTNER_NAME,
                field,
                current_ts.strftime("%d%m%Y"),
                filename_counter_suffix,
            )
        zf.writestr(filename, txt_content)

        encrypt_data_and_upload_to_permata_sftp_server.delay(
            content=txt_content,
            filename="{}.gpg".format(filename),
        )

    zf.close()

    create_channeling_loan_send_file_tracking(
        channeling_type=channeling_type,
        action_type=action_type,
        user_id=user_id,
    )

    return response_file(
        content_type=CONTENT_MIME_TYPE_ZIP,
        content=byteIo.getvalue(),
        filename='{}_channeling_{}{}.zip'.format(
            channeling_type, current_ts.strftime("%Y%m%d%H%M"), filename_counter_suffix
        ),
    )


def construct_permata_response_disbursement(_filter, channeling_type):
    # disbursement process, do for all
    disbursement_data = {}
    for doc_type in PermataDocumentHeaderConst.PERMATA_CHANNELING_DISBURSEMENT:
        disbursement_data[doc_type] = []

    channeling_loan_statuses = ChannelingLoanStatus.objects.filter(**_filter).order_by("-cdate")
    # function mapping meaning its a function (with or without parameters)
    function_mapping = PermataDocumentHeaderConst.FUNCTION_MAPPING

    for channeling_loan_status in channeling_loan_statuses:
        # all value is necessary for eval process
        loan = channeling_loan_status.loan
        permata_disbursement_agun = PermataDisbursementAgun.objects.filter(
            no_pin=loan.loan_xid
        ).last()
        permata_disbursement_cif = PermataDisbursementCif.objects.filter(
            loan_id=loan.loan_xid
        ).last()
        permata_disbursement_fin = PermataDisbursementFin.objects.filter(
            no_pin=loan.loan_xid
        ).last()
        permata_disbursement_sipd = PermataDisbursementSipd.objects.filter(
            no_pin=loan.loan_xid
        ).last()
        permata_disbursement_slik = PermataDisbursementSlik.objects.filter(
            loan_id=loan.loan_xid
        ).last()

        # save empty value, and then skip (not create new row)
        skip_process = set()
        if not permata_disbursement_agun:
            skip_process.add(PermataDocumentHeaderConst.DISBURSEMENT_AGUN)

        if not permata_disbursement_cif:
            skip_process.add(PermataDocumentHeaderConst.DISBURSEMENT_CIF)

        if not permata_disbursement_fin:
            skip_process.add(PermataDocumentHeaderConst.DISBURSEMENT_FIN)

        if not permata_disbursement_sipd:
            skip_process.add(PermataDocumentHeaderConst.DISBURSEMENT_SIPD)

        if not permata_disbursement_slik:
            skip_process.add(PermataDocumentHeaderConst.DISBURSEMENT_SLIK)

        channeling_payment_due_amount = 0  # noqa
        payment = channeling_loan_status.loan.payment_set.first()
        if payment:
            channeling_loan_payment = payment.channelingloanpayment_set.filter(
                channeling_type=channeling_type
            ).last()
            if channeling_loan_payment:
                channeling_payment_due_amount = channeling_loan_payment.due_amount  # noqa

        # skip process if failed
        if channeling_loan_status.channeling_status == ChannelingStatusConst.PENDING:
            status, _ = process_loan_for_channeling(loan)
            if status == "failed":
                continue

        for (
            field,
            collection,
        ) in PermataDocumentHeaderConst.PERMATA_DISBURSEMENT_CHANNELING.items():
            if field in skip_process:
                # data from ana is empty, thus the process is skipped
                continue

            detail = []
            for key, value in collection.items():
                if value and key not in PermataDocumentHeaderConst.SKIP_CHECKER:
                    # only do eval for non-empty value and skip field that skipped
                    value = eval(value)
                    if key in function_mapping.keys():
                        value = eval(function_mapping[key])(value)

                # convert to string
                value = str(value) if value is not None else ""
                if value and key in PermataDocumentHeaderConst.DATE_FORMAT_FIELD:
                    # convert date to dd/mm/yyyy
                    value = value.split(" ")[0]
                    value = datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")

                length = PermataDocumentHeaderConst.PERMATA_CHANNELING_LENGTH[field][key]
                value = padding_words(value, length)

                detail.append(value)

            # create detail
            disbursement_data[field].append("".join(detail))

    return disbursement_data


def construct_permata_response_repayment(_filter, channeling_type):
    # repayment process
    repayment_data = {}
    repayment_data[PermataDocumentHeaderConst.PAYMENT_CHANNELING] = []

    # function mapping meaning its a function (with or without parameters)
    function_mapping = PermataDocumentHeaderConst.FUNCTION_MAPPING
    date_range = _filter.get('cdate__range', None)
    if not date_range:
        current_ts = timezone.localtime(timezone.now())
        startdate = current_ts.replace(hour=0, minute=0, second=0)
        enddate = startdate + datetime.timedelta(days=1)
        date_range = [startdate, enddate]

    permata_payments = get_permata_channeling_repayment(date_range)
    for permata_payment in permata_payments:
        payment_event = PaymentEvent.objects.filter(pk=permata_payment.payment_event_id).last()
        if not payment_event:
            continue

        detail = []
        for key, value in PermataDocumentHeaderConst.PERMATA_CHANNELING[
            PermataDocumentHeaderConst.PAYMENT_CHANNELING
        ].items():
            if value and key not in PermataDocumentHeaderConst.SKIP_CHECKER:
                # only do eval for non-empty value and skip field that skipped
                value = eval(value)
                if key in function_mapping.keys():
                    value = eval(function_mapping[key])(value)

            # convert to string
            value = str(value) if value is not None else ""
            if value and key in PermataDocumentHeaderConst.DATE_FORMAT_FIELD:
                # convert date to dd/mm/yyyy
                value = value.split(" ")[0]
                value = datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")

            length = PermataDocumentHeaderConst.PERMATA_CHANNELING_LENGTH[
                PermataDocumentHeaderConst.PAYMENT_CHANNELING
            ][key]
            value = padding_words(value, length)

            detail.append(value)

        # create detail
        repayment_data[PermataDocumentHeaderConst.PAYMENT_CHANNELING].append("".join(detail))

    return repayment_data


def construct_permata_response_reconciliation():
    # reconciliation process
    reconciliation_data = {}
    reconciliation_data[PermataDocumentHeaderConst.RECONCILIATION_CHANNELING] = []

    # function mapping meaning its a function (with or without parameters)
    function_mapping = PermataDocumentHeaderConst.FUNCTION_MAPPING

    permata_reconciliations = PermataReconciliation.objects.all()
    for permata_reconciliation in permata_reconciliations:
        detail = []
        for key, value in PermataDocumentHeaderConst.PERMATA_CHANNELING[
            PermataDocumentHeaderConst.RECONCILIATION_CHANNELING
        ].items():
            if value and key not in PermataDocumentHeaderConst.SKIP_CHECKER:
                # only do eval for non-empty value and skip field that skipped
                value = eval(value)
                if key in function_mapping.keys():
                    value = eval(function_mapping[key])(value)

            # convert to string
            value = str(value) if value is not None else ""
            if value and key in PermataDocumentHeaderConst.DATE_FORMAT_FIELD:
                # convert date to dd/mm/yyyy
                value = value.split(" ")[0]
                value = datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")

            length = PermataDocumentHeaderConst.PERMATA_CHANNELING_LENGTH[
                PermataDocumentHeaderConst.RECONCILIATION_CHANNELING
            ][key]
            value = padding_words(value, length)
            detail.append(value)

        reconciliation_data[PermataDocumentHeaderConst.RECONCILIATION_CHANNELING].append(
            "".join(detail)
        )

    return reconciliation_data


def construct_permata_early_payoff_request_file_content(dict_rows: List[dict]) -> Tuple[bool, str]:
    errors = []
    result_rows = []
    for index, dict_row in enumerate(dict_rows):
        elements = []
        for field, (csv_mapping_field, length) in PermataEarlyPayoffConst.CSV_MAPPING_FIELD.items():
            # validate the mapping field
            if csv_mapping_field not in dict_row:
                errors.append("Row {}: {} is missing".format(index + 1, field))
                continue

            element = dict_row[csv_mapping_field]

            datetime_in_out_format_mapping = PermataEarlyPayoffConst.DATETIME_IN_OUT_FORMAT_MAPPING
            if field in datetime_in_out_format_mapping.keys():
                input_format, output_format = datetime_in_out_format_mapping[field]
                element = convert_datetime_string_to_other_format(
                    datetime_string=element, input_format=input_format, output_format=output_format
                )

                # validate the input date is valid or not
                if element is None:
                    errors.append("Row {}: {} is not a valid date".format(index + 1, field))
                    continue

            elements.append(padding_words(word=element, length=length))

        result_rows.append(''.join(elements))

    if errors:
        return False, '\n'.join(errors)
    return True, '\n'.join(result_rows)


def get_latest_permata_approval_filename(filenames: List[str], prefix) -> Optional[str]:
    """
    Get the latest filename by matching the prefix with the reverse order of the list.
    There are 2 types of approval files:
    1. Accepted filename has format {prefix}_*_%Y%m%d%H%M%S.txt.gpg
    2. Rejected filename has format {prefix}_*_%Y%m%d%H%M%S.xlsx.gpg
    :param filenames: list of strings, already be sorted
    :param prefix: determine the type of approval file
    :return:
    """
    # access the list in reverse order via index to avoid modify the list
    for index in range(len(filenames) - 1, -1, -1):
        filename = filenames[index]
        if filename.startswith(prefix):
            return filename
    return None


def download_latest_permata_single_approval_file_from_sftp_server(
    filename_prefix: str,
) -> Tuple[Optional[str], Optional[bytes]]:
    sftp_service = SFTPProcess(sftp_client=get_permata_sftp_client())

    # approval directory contains only files, no need to check any child directories
    filenames = sftp_service.list_dir(
        remote_dir_path=PermataChannelingConst.SFTP_APPROVAL_DIRECTORY_PATH
    )
    if not filenames:
        return None, None

    # filenames already be sorted in Connection.listdir
    latest_filename = get_latest_permata_approval_filename(
        filenames=filenames,
        prefix=filename_prefix,
    )

    if not latest_filename:
        return None, None

    return latest_filename, sftp_service.download(
        remote_path='{}/{}'.format(
            PermataChannelingConst.SFTP_APPROVAL_DIRECTORY_PATH, latest_filename
        )
    )


def download_latest_permata_disbursement_approval_files_from_sftp_server() -> Tuple[
    bool, Optional[Dict]
]:
    """
    Get the latest files by getting the accepted & rejected files in the approval folder.
    The number of files can be increased day by day, but we can't rely on a specific day,
    so let's try with this approach first.
    :return: a tuple of:
    - boolean: success or not
    - dict: value are filename and content for both accepted and rejected files
    """
    sftp_service = SFTPProcess(sftp_client=get_permata_sftp_client())

    # approval directory contains only files, no need to check any child directories
    filenames = sftp_service.list_dir(
        remote_dir_path=PermataChannelingConst.SFTP_APPROVAL_DIRECTORY_PATH
    )
    if not filenames:
        return False, None

    # filenames already be sorted in Connection.listdir
    latest_accepted_filename = get_latest_permata_approval_filename(
        filenames=filenames,
        prefix=PermataChannelingConst.ACCEPTED_DISBURSEMENT_FILENAME_PREFIX,
    )
    latest_rejected_filename = get_latest_permata_approval_filename(
        filenames=filenames,
        prefix=PermataChannelingConst.REJECTED_DISBURSEMENT_FILENAME_PREFIX,
    )

    if not latest_accepted_filename or not latest_rejected_filename:
        return False, None

    result = {
        'accepted_filename': latest_accepted_filename,
        'accepted_encrypted_data': sftp_service.download(
            remote_path='{}/{}'.format(
                PermataChannelingConst.SFTP_APPROVAL_DIRECTORY_PATH, latest_accepted_filename
            )
        ),
        'rejected_filename': latest_rejected_filename,
        'rejected_encrypted_data': sftp_service.download(
            remote_path='{}/{}'.format(
                PermataChannelingConst.SFTP_APPROVAL_DIRECTORY_PATH, latest_rejected_filename
            )
        ),
    }
    return True, result


def parse_permata_disbursement_accepted_loan_xids(txt_accepted_data: str) -> List[str]:
    """Use regular expression to find all NO.PINJAMAN values to get all loan xids"""
    return re.findall(
        pattern=PermataChannelingConst.ACCEPTED_DISBURSEMENT_LOAN_XID_PATTERN,
        string=txt_accepted_data,
    )


def parse_permata_disbursement_rejected_loan_xids(xlsx_rejected_data: bytes) -> List[str]:
    """Get all loan xids from Report Result sheet"""
    try:
        sheets = get_data_xls(io.BytesIO(xlsx_rejected_data))
    except Exception:
        raise PermataApprovalFileInvalidFormat('Rejected loan file is not a valid Excel file')

    if not sheets:
        raise PermataApprovalFileInvalidFormat('Rejected loan file does not have any sheet')

    # sheets is an OrderedDict, so we can pop the first item to get the Report Reject sheet
    # When we pop, we get a tuple of (sheet_name, sheet_value)
    _, rows = sheets.popitem(last=False)

    # In Report Reject sheet, there are some rows are summary data & header, so we need to skip them
    if len(rows) < PermataChannelingConst.REJECTED_DISBURSEMENT_LOAN_ROW_INDEX:
        raise PermataApprovalFileInvalidFormat(
            'Rejected loan file does not have enough rows for summary data & header'
        )

    rejected_loan_xids = []
    for index in range(PermataChannelingConst.REJECTED_DISBURSEMENT_LOAN_ROW_INDEX, len(rows)):
        row = rows[index]

        # Check exist column for loan XID in each loan row,
        if len(row) <= PermataChannelingConst.REJECTED_DISBURSEMENT_LOAN_COLUMN_INDEX:
            raise PermataApprovalFileInvalidFormat(
                'Rejected loan file does not have enough columns for each loan row'
            )
        rejected_loan_xids.append(
            row[PermataChannelingConst.REJECTED_DISBURSEMENT_LOAN_COLUMN_INDEX]
        )

    return rejected_loan_xids


def construct_permata_disbursement_approval_csv(
    accepted_loan_xids: List[str], rejected_loan_xids: List[str]
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    # write header
    writer.writerow(["Application_XID", "disetujui"])

    # write content
    writer.writerows([(accepted_loan_xid, "y") for accepted_loan_xid in accepted_loan_xids])
    writer.writerows([(rejected_loan_xid, "n") for rejected_loan_xid in rejected_loan_xids])

    return buffer.getvalue()


def construct_permata_disbursement_approval_file() -> Tuple[Optional[str], Optional[str]]:
    """
    :return: a tuple of: file name and content for the csv file
    """
    is_success, result = download_latest_permata_disbursement_approval_files_from_sftp_server()
    if not is_success:
        return None, None

    txt_accepted_data = decrypt_data(
        filename=result['accepted_filename'],
        content=result['accepted_encrypted_data'],
        passphrase=settings.PERMATA_GPG_DECRYPT_PASSPHRASE,
        gpg_recipient=settings.PERMATA_GPG_DECRYPT_RECIPIENT,
        gpg_key_data=settings.PERMATA_GPG_DECRYPT_KEY_DATA,
    )
    if txt_accepted_data is None:
        return None, None

    xlsx_rejected_data = decrypt_data(
        filename=result['rejected_filename'],
        content=result['rejected_encrypted_data'],
        passphrase=settings.PERMATA_GPG_DECRYPT_PASSPHRASE,
        gpg_recipient=settings.PERMATA_GPG_DECRYPT_RECIPIENT,
        gpg_key_data=settings.PERMATA_GPG_DECRYPT_KEY_DATA,
        return_raw_bytes=True,
    )
    if xlsx_rejected_data is None:
        return None, None

    csv_filename = replace_gpg_encrypted_file_name(
        encrypted_file_name=result['accepted_filename'], new_file_extension='csv'
    )
    csv_content = construct_permata_disbursement_approval_csv(
        accepted_loan_xids=parse_permata_disbursement_accepted_loan_xids(
            txt_accepted_data=txt_accepted_data
        ),
        rejected_loan_xids=parse_permata_disbursement_rejected_loan_xids(
            xlsx_rejected_data=xlsx_rejected_data
        ),
    )

    return csv_filename, csv_content


def construct_permata_single_approval_file(
    filename_prefix: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    :return: a tuple of: file name and content for the txt file
    """
    (
        encrypted_filename,
        encrypted_data,
    ) = download_latest_permata_single_approval_file_from_sftp_server(
        filename_prefix=filename_prefix
    )
    if encrypted_filename is None:
        return None, None

    txt_filename = replace_gpg_encrypted_file_name(encrypted_file_name=encrypted_filename)

    txt_content = decrypt_data(
        filename=encrypted_filename,
        content=encrypted_data,
        passphrase=settings.PERMATA_GPG_DECRYPT_PASSPHRASE,
        gpg_recipient=settings.PERMATA_GPG_DECRYPT_RECIPIENT,
        gpg_key_data=settings.PERMATA_GPG_DECRYPT_KEY_DATA,
    )
    if txt_content is None:
        return None, None

    return txt_filename, txt_content


def get_permata_channeling_repayment(date_range):
    fdc_data = {}
    try:
        raw_query = """
        select
        pcp.permata_channeling_payment_id,
        pcp.loan_id,
        pcp.nama,
        pcp.tgl_bayar_end_user,
        pcp.nilai_angsuran,
        pcp.denda,
        pcp.diskon_denda,
        pcp.tgl_terima_mf
        from ana.permata_channeling_payment pcp
        where TO_DATE(tgl_bayar_end_user, 'YYYY-MM-DD') BETWEEN %s AND %s
        """
        permata_payments = PermataPayment.objects.raw(raw_query, date_range)
        return permata_payments
    except Exception as e:
        logger.error(
            {
                'action': 'channeling_loan.services.permata_services'
                '.get_permata_channeling_repayment',
                'errors': str(e),
            }
        )

    return fdc_data
