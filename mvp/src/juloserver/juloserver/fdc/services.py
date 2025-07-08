import csv
import logging
import os
import re
from builtins import str
from datetime import datetime, date
import time
import io
from typing import Dict
from datetime import timedelta
from operator import itemgetter

import requests
from celery import task
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.ana_api.models import FDCInquiryPrioritizationReason2
from juloserver.fdc.clients import get_julo_fdc_client, get_julo_fdc_ftp_client
from juloserver.fdc.constants import (
    FDCConstant,
    FDCFailureReason,
    FDCTaskConst,
    RUN_FDC_INQUIRY_HEADERS,
)
from juloserver.fdc.exceptions import RabbitMQExporterException
from juloserver.fdc.files import (
    TempDir,
    parse_fdc_delivery_statistic,
    parse_fdc_error_data,
    store_loans_today_into_zipfile,
    yield_outdated_loans_data_from_file,
    get_list_files,
)
from juloserver.ana_api.models import FDCLoanDataUpload
from juloserver.fdc.models import (
    FDCDeliveryStatistic,
    FDCOutdatedLoan,
    InitialFDCInquiryLoanData,
)
from juloserver.fdc.utils import run_fdc_inquiry_format_data
from juloserver.fdc.constants import (
    FDCLoanStatus,
    FDCReasonConst,
    FDCStatus,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    Customer,
    FDCDelivery,
    FDCDeliveryTemp,
    FDCInquiry,
    FDCInquiryLoan,
    FDCValidationError,
    FeatureSetting,
    Loan,
    UploadAsyncState,
)
from juloserver.ana_api.utils import check_app_cs_v20b
from juloserver.apiv2.models import (
    PdWebModelResult,
    PdCreditModelResult,
)
from juloserver.monitors.notifications import notify_failure
from juloserver.fdc.serializers import RunFdcInquirySerializer
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.fdc.constants import FDCFileSIKConst

logger = logging.getLogger(__name__)


class FDCFileNotFound(JuloException):
    pass


@task(name='download_outdated_loans_from_fdc')
def download_outdated_loans_from_fdc(
    current_retry_count=0,
    max_retry_count=FDCTaskConst.MAX_RETRY_COUNT,
    retry_interval=FDCTaskConst.RETRY_INTERVAL,
):

    fdc_ftp_client = get_julo_fdc_ftp_client()
    if not fdc_ftp_client.is_outdated_loans_file_exist():

        if current_retry_count > max_retry_count:
            raise FDCFileNotFound("FDC file reporting outdated loans")

        current_retry_count += 1
        download_outdated_loans_from_fdc.apply_async(
            (current_retry_count,), countdown=retry_interval
        )

    with TempDir() as tempdir:
        local_filepath = fdc_ftp_client.get_outdated_loans_file(tempdir.path)

        outdated_loans_to_save = []
        not_found_count = 0
        for row in yield_outdated_loans_data_from_file(local_filepath):
            customer_id = row['id_borrower']
            id_pinjaman = row['id_pinjaman']
            report_date = row['tgl_pelaporan_data']
            reported_status = row['status_pinjaman']

            application = (
                Application.objects.select_related('customer')
                .filter(customer_id=customer_id, application_xid=id_pinjaman)
                .last()
            )

            if application:
                loan = Loan.objects.filter(customer_id=customer_id, application=application).last()
                customer = application.customer

            else:
                loan = (
                    Loan.objects.select_related('customer')
                    .filter(customer_id=customer_id, loan_xid=id_pinjaman)
                    .last()
                )
                if loan:
                    application = loan.account.application_set.last()
                    customer = loan.customer

            if not loan and not application:
                logger.error(
                    {
                        "action": "download_outdated_loans_from_fdc",
                        "message": "data not found on fdc",
                        "id_pinjaman": id_pinjaman,
                        "id_borrower": customer_id,
                    }
                )
                not_found_count += 1
                continue

            if application and loan and customer:
                fdc_outdated_loan = FDCOutdatedLoan(
                    customer_id=customer.id,
                    application_id=application.id,
                    report_date=report_date,
                    reported_status=str(reported_status),
                    loan=loan.id,
                )
                outdated_loans_to_save.append(fdc_outdated_loan)

        FDCOutdatedLoan.objects.bulk_create(outdated_loans_to_save)

        if not_found_count > 0:
            msg = "Reported data on FDC not found in DB: {}, ".format(not_found_count)
            notify_failure(msg, channel='#fdc', label_env=True)


@task(name='download_statistic_data_from_fdc')
def download_statistic_data_from_fdc(
    current_retry_count=0,
    max_retry_count=FDCTaskConst.MAX_RETRY_COUNT,
    retry_interval=FDCTaskConst.RETRY_INTERVAL,
):

    fdc_ftp_client = get_julo_fdc_ftp_client()
    if (
        not fdc_ftp_client.is_statistic_json_file_exists()
        and not fdc_ftp_client.is_statistic_loan_json_file_exists()
    ):

        if current_retry_count > max_retry_count:
            raise FDCFileNotFound("FDC file statistic data")

        current_retry_count += 1
        download_statistic_data_from_fdc.apply_async(
            (current_retry_count,), countdown=retry_interval
        )

    with TempDir() as tempdir:
        file_filepath = fdc_ftp_client.get_statistic_fdc_file(tempdir.path)
        loan_filepath = fdc_ftp_client.get_statistic_loan_fdc_file(tempdir.path)

        fdc_statistic_report_file = parse_fdc_delivery_statistic(file_filepath, loan_filepath)
        fdc_delivery_statistic = FDCDeliveryStatistic(**fdc_statistic_report_file)
        fdc_delivery_statistic.save()

        percentage_updated = fdc_delivery_statistic.status_loan[0].get('percentage')
        float_percentage_updated = float(percentage_updated[:-1]) / 100

        threshold = fdc_delivery_statistic.status_loan[0].get('threshold')
        if threshold is None:
            # typo from fdc response
            threshold = fdc_delivery_statistic.status_loan[0].get('tresshold')
        float_threshold = float(threshold[:-1]) / 100

        max_percentage = float_threshold + FDCTaskConst.MAX_PERCENTAGE

        if float_percentage_updated < max_percentage:
            msg = (
                "Data updated on FDC currently {}%, (below {}% threshold), "
                "please check table fdc_outdated_loan".format(
                    int(float_percentage_updated * 100),
                    max_percentage,
                )
            )
            notify_failure(msg, channel='#fdc', label_env=True)


@task(name='download_result_from_fdc')
def download_result_from_fdc(
    current_retry_count=0,
    max_retry_count=FDCTaskConst.MAX_RETRY_COUNT,
    retry_interval=FDCTaskConst.RETRY_INTERVAL,
):

    today = timezone.localtime(timezone.now()).date()
    fdc_deliveries_today = FDCDelivery.objects.filter(cdate__date=today, status='completed')
    count_today = fdc_deliveries_today.count()

    if count_today == 0:
        return

    for fdc_delivery in fdc_deliveries_today:
        output_filename = fdc_delivery.generated_filename + '.out'
        fdc_ftp_client = get_julo_fdc_ftp_client()
        if not fdc_ftp_client.is_fdc_result_exists(output_filename):
            if current_retry_count > max_retry_count:
                raise FDCFileNotFound("FDC file result")

            current_retry_count += 1
            download_result_from_fdc.apply_async((current_retry_count,), countdown=retry_interval)

        with TempDir() as tempdir:
            local_filepath = fdc_ftp_client.get_upload_errors_file(tempdir.path, output_filename)

            if local_filepath == '':
                return

            fdc_error_data = parse_fdc_error_data(fdc_delivery.generated_filename, local_filepath)

            for data in fdc_error_data:
                fdc_validation_error = FDCValidationError(**data)
                fdc_validation_error.save()

    fdc_error_data = FDCValidationError.objects.filter(cdate__date=today)
    if fdc_error_data:
        count_error_data = fdc_error_data.count()
        fdc_delivery_ids = FDCDelivery.objects.filter(
            cdate__date=today, status='completed'
        ).values_list('id', flat=True)
        msg = (
            "{} errors reported from fdc_delivery_ids = {}, "
            "check table fdc_validation_error for details"
        ).format(count_error_data, fdc_delivery_ids)
        notify_failure(msg, channel='#fdc', label_env=True)


@task(name='upload_loans_data_to_fdc', queue='lower')
def upload_loans_data_to_fdc():
    qs = FDCLoanDataUpload.objects.all()
    field_names = (
        'id_penyelenggara',
        'id_borrower',
        'jenis_pengguna',
        'nama_borrower',
        'no_identitas',
        'no_npwp',
        'id_pinjaman',
        'tgl_perjanjian_borrower',
        'tgl_penyaluran_dana',
        'nilai_pendanaan',
        'tgl_pelaporan_data',
        'sisa_pinjaman_berjalan',
        'tgl_jatuh_tempo_pinjaman',
        'kualitas_pinjaman',
        'dpd_terakhir',
        'dpd_max',
        'status_pinjaman',
        'penyelesaian_w_oleh',
        'syariah',
        'tipe_pinjaman',
        'sub_tipe_pinjaman',
        'reference',
        'no_hp',
        'email',
        'agunan',
        'tgl_agunan',
        'nama_penjamin',
        'no_agunan',
        'pendapatan',
    )

    data_dict = qs.values(*field_names)

    count_of_record = data_dict.count()
    data_dict = data_dict.iterator()

    today = timezone.localtime(timezone.now()).date()
    fdc_deliveries_today = FDCDelivery.objects.filter(cdate__date=today, status='completed')
    count_today = fdc_deliveries_today.count()
    config = get_config_fdc_upload_file_sik()

    with TempDir() as tempdir:

        zip_password = settings.FDC_ZIP_PASSWORD
        list_of_zip = []
        store_loans_today_into_zipfile(
            tempdir.path,
            field_names,
            data_dict,
            zip_password,
            count_today,
            count_of_record=count_of_record,
            list_of_zip=list_of_zip,
            tempdir=tempdir,
            config=config,
        )

        list_files = get_list_files_details(tempdir.path)
        upload_files_sik_to_fdc_server(
            config=config,
            list_file_uploads=list_files,
            count_of_record=count_of_record,
            retry_count=0,
            last_count=0,
            count_today=count_today,
        )

        logger.info(
            {
                'message': 'try to store temporary table',
                'count_today': count_today,
                'count_of_record': count_of_record,
            }
        )

    store_to_temporary_table(data_dict)


def store_to_temporary_table(data):
    """temporary store fdc data for matching purpose"""
    fdc_temporary_data = []
    runner = 0
    block_size = 100
    for item in data:
        temp_record = FDCDeliveryTemp(
            dpd_max=item['dpd_max'],
            dpd_terakhir=item['dpd_terakhir'],
            id_penyelenggara=item['id_penyelenggara'],
            jenis_pengguna=item['jenis_pengguna'],
            kualitas_pinjaman=item['kualitas_pinjaman'],
            nama_borrower=item['nama_borrower'],
            nilai_pendanaan=item['nilai_pendanaan'],
            no_identitas=item['no_identitas'],
            no_npwp=item['no_npwp'],
            sisa_pinjaman_berjalan=item['sisa_pinjaman_berjalan'],
            status_pinjaman=item['status_pinjaman'],
            tgl_jatuh_tempo_pinjaman=item['tgl_jatuh_tempo_pinjaman'],
            tgl_pelaporan_data=item['tgl_pelaporan_data'],
            tgl_penyaluran_dana=item['tgl_penyaluran_dana'],
            tgl_perjanjian_borrower=item['tgl_perjanjian_borrower'],
            no_hp=item['no_hp'],
            email=item['email'],
            agunan=item['agunan'],
            tgl_agunan=item['tgl_agunan'],
            nama_penjamin=item['nama_penjamin'],
            no_agunan=item['no_agunan'],
            pendapatan=item['pendapatan'],
        )
        fdc_temporary_data.append(temp_record)
        runner += 1
        if runner == block_size:
            FDCDeliveryTemp.objects.bulk_create(fdc_temporary_data)
            runner = 0
            fdc_temporary_data = []

    if fdc_temporary_data:
        FDCDeliveryTemp.objects.bulk_create(fdc_temporary_data)

    logger.info({"action": "store to temporary table", "status": "Done"})


def store_initial_fdc_inquiry_loan_data(initial_fdc_inquiry):
    non_julo_outstanding_loans = initial_fdc_inquiry.fdcinquiryloan_set.filter(
        status_pinjaman='Outstanding'
    ).exclude(is_julo_loan=True)
    initial_fdc_loan_count = non_julo_outstanding_loans.count()
    initial_outstanding_loan_amount = non_julo_outstanding_loans.aggregate(
        Sum('sisa_pinjaman_berjalan')
    ).get('sisa_pinjaman_berjalan__sum')
    InitialFDCInquiryLoanData.objects.update_or_create(
        fdc_inquiry=initial_fdc_inquiry,
        defaults={
            'initial_outstanding_loan_count_x100': initial_fdc_loan_count,
            'initial_outstanding_loan_amount_x100': initial_outstanding_loan_amount,
        },
    )
    return initial_fdc_loan_count, initial_outstanding_loan_amount


def get_clone_fdc_data(fdc_inquiry):

    detokenized_fdc_inquiry = detokenize_for_model_object(
        PiiSource.FDC_INQUIRY,
        [{'object': fdc_inquiry}],
        pii_data_type=PiiVaultDataType.KEY_VALUE,
        force_get_local_data=True,
    )

    fdc_inquiry = detokenized_fdc_inquiry[0]

    data = {
        'inquiryReason': fdc_inquiry.inquiry_reason,
        'refferenceId': fdc_inquiry.reference_id,
        'status': fdc_inquiry.status,
        'inquiryDate': fdc_inquiry.inquiry_date,
    }
    if fdc_inquiry.inquiry_status == 'success':
        data['status'] = "Found"
    elif fdc_inquiry.inquiry_status == 'inquiry_disabled':
        data['status'] = "Inquiry Function is Disabled"

    data['noHp'] = fdc_inquiry.mobile_phone
    data['mail'] = fdc_inquiry.email
    data['historyInquiry'] = fdc_inquiry.inquiry_history
    data['pinjaman'] = []

    fdc_time_format = "%Y-%m-%d"
    fdc_inquiry_loans = FDCInquiryLoan.objects.filter(fdc_inquiry=fdc_inquiry)
    for fdc_inquiry_loan in fdc_inquiry_loans:

        detokenized_fdc_inquiry_loan = detokenize_for_model_object(
            PiiSource.FDC_INQUIRY_LOAN,
            [{'object': fdc_inquiry_loan}],
            pii_data_type=PiiVaultDataType.KEY_VALUE,
            force_get_local_data=True,
        )

        fdc_inquiry_loan = detokenized_fdc_inquiry_loan[0]

        loan_data = {}
        tgl_agunan = None
        if fdc_inquiry_loan.tgl_agunan:
            tgl_agunan = fdc_inquiry_loan.tgl_agunan.strftime(fdc_time_format)
        loan_data.update(
            {
                'dpd_max': fdc_inquiry_loan.dpd_max,
                'dpd_terakhir': fdc_inquiry_loan.dpd_terakhir,
                'id_penyelenggara': fdc_inquiry_loan.id_penyelenggara,
                'jenis_pengguna_ket': fdc_inquiry_loan.jenis_pengguna,
                'kualitas_pinjaman_ket': fdc_inquiry_loan.kualitas_pinjaman,
                'nama_borrower': fdc_inquiry_loan.nama_borrower,
                'nilai_pendanaan': fdc_inquiry_loan.nilai_pendanaan,
                'no_identitas': fdc_inquiry_loan.no_identitas,
                'no_npwp': fdc_inquiry_loan.no_npwp,
                'sisa_pinjaman_berjalan': fdc_inquiry_loan.sisa_pinjaman_berjalan,
                'status_pinjaman_ket': fdc_inquiry_loan.status_pinjaman,
                'penyelesaian_w_oleh': fdc_inquiry_loan.penyelesaian_w_oleh,
                'pendanaan_syariah': fdc_inquiry_loan.pendanaan_syariah,
                'tipe_pinjaman': fdc_inquiry_loan.tipe_pinjaman,
                'sub_tipe_pinjaman': fdc_inquiry_loan.sub_tipe_pinjaman,
                'id': fdc_inquiry_loan.fdc_id,
                'reference': fdc_inquiry_loan.reference,
                'tgl_jatuh_tempo_pinjaman': fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman.strftime(
                    fdc_time_format
                ),
                'tgl_pelaporan_data': fdc_inquiry_loan.tgl_pelaporan_data.strftime(fdc_time_format),
                'tgl_penyaluran_dana': fdc_inquiry_loan.tgl_penyaluran_dana.strftime(
                    fdc_time_format
                ),
                'tgl_perjanjian_borrower': fdc_inquiry_loan.tgl_perjanjian_borrower.strftime(
                    fdc_time_format
                ),
                'no_hp': fdc_inquiry_loan.no_hp,
                'email': fdc_inquiry_loan.email,
                'agunan': fdc_inquiry_loan.agunan,
                'tgl_agunan': tgl_agunan,
                'nama_penjamin': fdc_inquiry_loan.nama_penjamin,
                'no_agunan': fdc_inquiry_loan.no_agunan,
                'pendapatan': fdc_inquiry_loan.pendapatan,
            }
        )

        if fdc_inquiry_loan.is_julo_loan is True:
            loan_data['id_penyelenggara'] = '1'

        data['pinjaman'].append(loan_data)

    return data


def get_direct_data(fdc_inquiry_data, reason, is_changed):
    try:
        # add log
        logger.info(
            {
                'message': 'FDCInquiry: start request inquiry',
                'nik': fdc_inquiry_data['nik'],
                'reason': reason,
            }
        )

        fdc_client = get_julo_fdc_client()
        response = fdc_client.get_fdc_inquiry_data(fdc_inquiry_data['nik'], reason)
        response, reason = get_and_call_certain_status(
            response, fdc_inquiry_data['nik'], reason, is_changed
        )

    except Exception as error:
        # add logger from this requirement (https://github.com/julofinance/mvp/pull/6508)
        logger.error(
            {
                "action": "run_fdc_request",
                "id": fdc_inquiry_data['id'],
                "nik": fdc_inquiry_data['nik'],
                "error": str(error),
            }
        )
        raise error

    if not response.ok:
        error = {"status_code": response.status_code, "response": response.text}
        raise JuloException(
            "Can not access FDC with response: %(response)s" % {'response': response}, error
        )

    return response.json()


def get_and_save_fdc_data(fdc_inquiry_data, reason, retry):
    # verify reason number when inquiry
    reason, is_changed = determine_inquiry_reason(fdc_inquiry_data, reason)
    fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])

    today = timezone.localtime(timezone.now()).date()
    is_need_direct_data = True
    if reason == 1:
        last_fdc_inquiry = (
            FDCInquiry.objects.filter(nik=fdc_inquiry_data['nik'])
            .exclude(pk=fdc_inquiry_data['id'])
            .last()
        )
        if (
            last_fdc_inquiry
            and last_fdc_inquiry.status
            and last_fdc_inquiry.status.lower() == 'found'
            and last_fdc_inquiry.cdate.date() == today
            and str(last_fdc_inquiry.inquiry_reason).lower()
            == str(FDCFailureReason.REASON_FILTER[1]).lower()
        ):
            is_need_direct_data = False

    try:
        if is_need_direct_data:
            data = get_direct_data(fdc_inquiry_data, reason, is_changed)
        else:
            data = get_clone_fdc_data(last_fdc_inquiry)
    except JuloException as error:
        (err, message) = error.args
        fdc_inquiry.update_safely(
            inquiry_status='error',
            error=str(message),
            inquiry_reason=FDCFailureReason.REASON_FILTER[reason],
        )
        raise JuloException(err)
    except Exception as error:
        fdc_inquiry.update_safely(
            inquiry_status='error',
            error=str(error),
            inquiry_reason=FDCFailureReason.REASON_FILTER[reason],
        )
        raise error

    # This field was documented to be in the response but later on removed
    # add logic if it's passed
    reference_id = data['refferenceId'] if 'refferenceId' in data else None

    with transaction.atomic(using='bureau_db'):
        fdc_inquiry = FDCInquiry.objects.select_for_update().get(id=fdc_inquiry_data['id'])
        # Prevent overwrite data for a same FDC inquiry result by a concurrent task
        if fdc_inquiry.status:
            return data

        if fdc_inquiry.retry_count is None:
            fdc_inquiry.retry_count = 0
        else:
            fdc_inquiry.retry_count += 1

        fdc_inquiry.inquiry_reason = data['inquiryReason']
        fdc_inquiry.reference_id = reference_id
        fdc_inquiry.status = data['status']
        fdc_inquiry.inquiry_date = data['inquiryDate']
        if "found" == data['status'].lower():
            fdc_inquiry.inquiry_status = 'success'
        elif "inquiry function is disabled" == data['status'].lower():
            fdc_inquiry.inquiry_status = 'inquiry_disabled'
        elif "not found" == data['status'].lower():
            fdc_inquiry.inquiry_status = 'success'
        fdc_inquiry.mobile_phone = data['noHp']
        fdc_inquiry.email = data['mail']
        fdc_inquiry.inquiry_history = data['historyInquiry']
        fdc_inquiry.save()

        if data['pinjaman'] is None:
            return data

        fdc_time_format = "%Y-%m-%d"
        for loan_data in data['pinjaman']:

            tgl_agunan = None
            if 'tgl_agunan' in loan_data and loan_data['tgl_agunan']:
                tgl_agunan = datetime.strptime(loan_data['tgl_agunan'], fdc_time_format)

            pendapatan = loan_data['pendapatan'] if 'pendapatan' in loan_data else None

            inquiry_loan_record = {
                'fdc_inquiry': fdc_inquiry,
                'dpd_max': loan_data['dpd_max'],
                'dpd_terakhir': loan_data['dpd_terakhir'],
                'id_penyelenggara': loan_data['id_penyelenggara'],
                'jenis_pengguna': loan_data['jenis_pengguna_ket'],
                'kualitas_pinjaman': loan_data['kualitas_pinjaman_ket'],
                'nama_borrower': loan_data['nama_borrower'].strip('\x00')[:100],
                'nilai_pendanaan': loan_data['nilai_pendanaan'],
                'no_identitas': loan_data['no_identitas'],
                'no_npwp': loan_data['no_npwp'],
                'sisa_pinjaman_berjalan': loan_data['sisa_pinjaman_berjalan'],
                'status_pinjaman': loan_data['status_pinjaman_ket'],
                'penyelesaian_w_oleh': loan_data['penyelesaian_w_oleh'],
                'pendanaan_syariah': loan_data['pendanaan_syariah'],
                'tipe_pinjaman': loan_data['tipe_pinjaman'],
                'sub_tipe_pinjaman': loan_data['sub_tipe_pinjaman'],
                'fdc_id': loan_data['id'],
                'reference': loan_data['reference'],
                'tgl_jatuh_tempo_pinjaman': datetime.strptime(
                    loan_data['tgl_jatuh_tempo_pinjaman'], fdc_time_format
                ),
                'tgl_pelaporan_data': datetime.strptime(
                    loan_data['tgl_pelaporan_data'], fdc_time_format
                ),
                'tgl_penyaluran_dana': datetime.strptime(
                    loan_data['tgl_penyaluran_dana'], fdc_time_format
                ),
                'tgl_perjanjian_borrower': datetime.strptime(
                    loan_data['tgl_perjanjian_borrower'], fdc_time_format
                ),
                'no_hp': loan_data['no_hp'],
                'email': loan_data['email'],
                'agunan': loan_data['agunan'],
                'tgl_agunan': tgl_agunan,
                'nama_penjamin': loan_data['nama_penjamin'].strip('\x00')[:100],
                'no_agunan': loan_data['no_agunan'],
                'pendapatan': pendapatan,
            }
            fdc_inquiry_loan = FDCInquiryLoan(**inquiry_loan_record)

            if loan_data['id_penyelenggara'] == 'AFDC150':
                logger.info(
                    {
                        'message': 'FDCInquiry: is_julo_loan is True',
                        'id_penyelenggara': 'AFDC150',
                        'fdc_inquiry_id': fdc_inquiry_data['id'],
                    }
                )
                fdc_inquiry_loan.is_julo_loan = True

            fdc_inquiry_loan.save()
    fdc_inquiry.refresh_from_db()
    store_initial_fdc_inquiry_loan_data(fdc_inquiry)

    from juloserver.application_form.tasks.application_task import trigger_generate_good_fdc_x100

    application = Application.objects.get_or_none(id=fdc_inquiry.application_id)
    if (
        application
        and application.is_julo_one()
        and application.application_status_id == ApplicationStatusCodes.FORM_CREATED
    ):
        trigger_generate_good_fdc_x100(application_id=application.id)
    return data


def mock_get_and_save_fdc_data(fdc_inquiry_data):
    import time

    fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])

    fdc_inquiry.retry_count = 0
    fdc_inquiry.save()

    fdc_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FDC_MOCK_RESPONSE_SET,
    )
    time.sleep(fdc_mock_feature.parameters['latency'] / 1000)
    data = fdc_mock_feature.parameters['response_value']

    # This field was documented to be in the response but later on removed
    # add logic if it's passed
    reference_id = data['refferenceId'] if 'refferenceId' in data else None

    with transaction.atomic():
        fdc_inquiry = FDCInquiry.objects.select_for_update().get(id=fdc_inquiry_data['id'])
        fdc_inquiry.inquiry_reason = data['inquiryReason']
        fdc_inquiry.reference_id = reference_id
        fdc_inquiry.status = data['status']
        fdc_inquiry.inquiry_date = data['inquiryDate']
        if "Found" == data['status']:
            fdc_inquiry.inquiry_status = 'success'
        elif "Inquiry Function is Disabled" == data['status']:
            fdc_inquiry.inquiry_status = 'inquiry_disabled'
        elif "Not Found" == data['status']:
            fdc_inquiry.inquiry_status = 'success'
        fdc_inquiry.save()

        if data['pinjaman'] is None:
            return

        fdc_time_format = "%Y-%m-%d"
        for loan_data in data['pinjaman']:
            inquiry_loan_record = {
                'fdc_inquiry': fdc_inquiry,
                'dpd_max': loan_data['dpd_max'],
                'dpd_terakhir': loan_data['dpd_terakhir'],
                'id_penyelenggara': loan_data['id_penyelenggara'],
                'jenis_pengguna': loan_data['jenis_pengguna_ket'],
                'kualitas_pinjaman': loan_data['kualitas_pinjaman_ket'],
                'nama_borrower': loan_data['nama_borrower'].strip('\x00')[:100],
                'nilai_pendanaan': loan_data['nilai_pendanaan'],
                'no_identitas': loan_data['no_identitas'],
                'no_npwp': loan_data['no_npwp'],
                'sisa_pinjaman_berjalan': loan_data['sisa_pinjaman_berjalan'],
                'status_pinjaman': loan_data['status_pinjaman_ket'],
                'penyelesaian_w_oleh': loan_data['penyelesaian_w_oleh'],
                'pendanaan_syariah': loan_data['pendanaan_syariah'],
                'tipe_pinjaman': loan_data['tipe_pinjaman'],
                'sub_tipe_pinjaman': loan_data['sub_tipe_pinjaman'],
                'fdc_id': loan_data['id'],
                'reference': loan_data['reference'],
                'tgl_jatuh_tempo_pinjaman': datetime.strptime(
                    loan_data['tgl_jatuh_tempo_pinjaman'], fdc_time_format
                ),
                'tgl_pelaporan_data': datetime.strptime(
                    loan_data['tgl_pelaporan_data'], fdc_time_format
                ),
                'tgl_penyaluran_dana': datetime.strptime(
                    loan_data['tgl_penyaluran_dana'], fdc_time_format
                ),
                'tgl_perjanjian_borrower': datetime.strptime(
                    loan_data['tgl_perjanjian_borrower'], fdc_time_format
                ),
            }
            fdc_inquiry_loan = FDCInquiryLoan(**inquiry_loan_record)

            if loan_data['id_penyelenggara'] == str(1):
                fdc_inquiry_loan.is_julo_loan = True

            fdc_inquiry_loan.save()
    fdc_inquiry.refresh_from_db()
    store_initial_fdc_inquiry_loan_data(fdc_inquiry)


def check_fdc_inquiry(application_id):
    fdc_inquiry_done = FDCInquiry.objects.filter(application_id=application_id).exists()

    return not fdc_inquiry_done


def get_fdc_timeout_config():
    """
    config format ex: {(0, 10): 10, (11, 23): 15}
    """

    fdc_timeout_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FDC_TIMEOUT, is_active=True
    ).last()
    if not fdc_timeout_setting or not fdc_timeout_setting.parameters:
        return FDCConstant.TIME_OUT_MINS_DEFAULT

    current_hour = timezone.localtime(timezone.now()).hour

    try:
        for time_range, timeout_value_mins in fdc_timeout_setting.parameters.items():
            time_range_start, time_range_end = time_range.split('-')
            on_time = int(time_range_start) <= current_hour <= int(time_range_end)
            if on_time:
                return timeout_value_mins
        raise JuloException('FDC Timeout Setting Invalid')
    except Exception:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

    return FDCConstant.TIME_OUT_MINS_DEFAULT


def get_fdc_inquiry_queue_size():
    response = requests.get(settings.RABBITMQ_EXPORTER_METRIC_URL)
    if response.status_code != 200:
        raise RabbitMQExporterException('%s: %s' % (response.status_code, response.content))

    data_list = str(response.content).split('\\n')
    for data in data_list:
        if re.match(FDCConstant.REGEX_QUEUE_CHECK, data):
            queue_size = re.search(r'} (\d*)', data).group().split('} ')[1]
            return int(queue_size)

    logger.warning(
        {
            "task": "juloserver.julo.tasks.run_fdc_api",
            "function": "get_fdc_inquiry_queue_size",
            "message": "queue_messages_ready on fdc_inquiry queue was not found",
        }
    )
    return None


def check_fdc_is_ready_to_refresh(
    fdc_inquiry=None, application_id=None, customer_id=None, nik=None
):
    if not fdc_inquiry:
        if application_id:
            fdc_inquiry = FDCInquiry.objects.filter(application_id=application_id).last()
        else:
            fdc_inquiry = FDCInquiry.objects.filter(customer_id=customer_id, nik=nik).last()

    if not fdc_inquiry:
        return True

    today_date = timezone.localtime(timezone.now()).date()
    if (today_date - fdc_inquiry.cdate.date()).days >= 1 or fdc_inquiry.retry_count is None:
        return True

    return False


def write_row_result(
    row: Dict,
    is_success: bool,
    message: str = None,
):
    return [
        is_success,
        row.get("nik_spouse"),
        row.get("application_xid"),
        message,
    ]


def run_fdc_inquiry_upload(upload_async_state: UploadAsyncState) -> bool:
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')

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
            write.writerow(RUN_FDC_INQUIRY_HEADERS)

            for row in reader:
                is_success = True
                formatted_data = run_fdc_inquiry_format_data(row)
                serializer = RunFdcInquirySerializer(data=formatted_data)

                if serializer.is_valid():
                    errors = {}
                    if not formatted_data['nik_spouse']:
                        msg = 'NIK Harus Diisi'
                        errors['nik_spouse'] = [msg]
                        is_success = False
                    if not formatted_data['application_xid']:
                        msg = 'application_xid Harus Diisi'
                        errors['application_xid'] = [msg]
                        is_success = False

                    if not is_success:
                        is_success_all = False
                        write.writerow(write_row_result(formatted_data, is_success, errors))
                        continue

                    is_success, message = run_fdc_inquiry(customer_data=formatted_data)

                    write.writerow(
                        write_row_result(
                            formatted_data,
                            is_success,
                            message,
                        )
                    )
                    # to delay for 1 seconds every run_fdc_inquiry
                    time.sleep(1)

    return is_success_all


def run_fdc_inquiry(customer_data):
    from juloserver.julo.tasks import trigger_fdc_inquiry

    application_xid = customer_data['application_xid']
    nik = customer_data['nik_spouse']
    logger.info(
        {
            "task": "juloserver.fdc.views.RunFdcInquiry",
            "message": "RunFdcInquiry task is running {}".format(application_xid),
        }
    )
    fdc_feature = FeatureSetting.objects.filter(
        feature_name="fdc_configuration", is_active=True
    ).last()
    if not fdc_feature:
        return False, 'fdc feature not found {}'.format(fdc_feature)

    application = Application.objects.filter(application_xid=application_xid).last()
    if not application:
        return False, 'application not found {}'.format(application_xid)

    fdc_inquiry = FDCInquiry(
        application_id=application.id,
        nik=nik,
        application_status_code=application.status,
        customer_id=application.customer.id,
    )
    fdc_inquiry.save()

    trigger_fdc_inquiry.apply_async((fdc_inquiry.id, nik, application.status))

    return True, "FDC hit success, please wait"


def process_get_fdc_result(application):
    fdc_feature = FeatureSetting.objects.filter(
        feature_name="fdc_configuration", is_active=True
    ).last()
    if not fdc_feature:
        return 'Fdc feature not found {}'.format(fdc_feature)

    fdc_inquiry = FDCInquiry.objects.filter(application_id=application.id).last()

    if not fdc_inquiry or (fdc_inquiry and not fdc_inquiry.status):
        return 'Kinerja pinjaman lainnya di database FDC - PENDING'

    if fdc_inquiry.status.lower() == 'not found':
        return 'Kinerja pinjaman lainnya di database FDC - NOT FOUND'

    today = timezone.localtime(timezone.now()).date()
    underperformed_loans = (
        FDCInquiryLoan.objects.filter(fdc_inquiry=fdc_inquiry)
        .filter(
            (
                Q(kualitas_pinjaman='Tidak Lancar (30 sd 90 hari)')
                | Q(kualitas_pinjaman='Macet (>90)')
            )
            | Q(tgl_jatuh_tempo_pinjaman__lt=today) & Q(sisa_pinjaman_berjalan__gt=0)
        )
        .exists()
    )

    if underperformed_loans:
        return 'Not pass in fdc inquiry kriteria'

    return 'PASSED'


def get_or_non_fdc_inquiry_not_out_date(application_id: int, day_diff: int):
    """
    :params application_id
    :params day_diff: it's from fs. used to check data is out of date or not.
    """
    fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application_id, inquiry_status='success'
    ).last()

    if day_diff:
        day_after_day_diff = timezone.now().date() - relativedelta(days=day_diff)
        if not fdc_inquiry or fdc_inquiry.udate.date() < day_after_day_diff:
            return None

    return fdc_inquiry


def get_info_active_loan_from_platforms(fdc_inquiry_id: int):
    """
    Check data from FDC to know the user has how many active loans from platforms
    :params fdc_inquiry_id: it's from FDCInquiry
    """

    fdc_inquiry_loans = (
        FDCInquiryLoan.objects.filter(fdc_inquiry_id=fdc_inquiry_id, is_julo_loan__isnull=True)
        .filter(status_pinjaman=FDCLoanStatus.OUTSTANDING)
        .values('id_penyelenggara', 'tgl_jatuh_tempo_pinjaman')
        .order_by('tgl_jatuh_tempo_pinjaman')
    )

    count_platforms = len(set([inquiry['id_penyelenggara'] for inquiry in fdc_inquiry_loans]))
    nearest_due_date = (
        fdc_inquiry_loans[0]['tgl_jatuh_tempo_pinjaman'] if fdc_inquiry_loans else None
    )
    count_active_loans = len(fdc_inquiry_loans)

    return nearest_due_date, count_platforms, count_active_loans


def determine_inquiry_reason(fdc_inquiry_data, reason_number):
    """
    This function to prevent error `please reason 2` when got response from FDC Inquiry
    We need to check nik already reported or not to FDC in File SIK.
    So, determine reason number based on:
    - Customer already exist or not in loan table
    (this already reported to FDC) with cut-off -1 day.
    """

    nik = fdc_inquiry_data['nik']
    is_changed = False
    logger.info(
        {
            'message': 'FDCInquiry: start to execute determine_inquiry_reason',
            'nik': nik,
            'reason': reason_number,
        }
    )

    if reason_number != FDCReasonConst.REASON_APPLYING_LOAN:
        logger.info(
            {
                'message': 'FDCInquiry: skip process to change reason',
                'nik': nik,
                'reason': reason_number,
                'is_change': is_changed,
            }
        )
        return reason_number, is_changed

    # check by loan data with cdate <= today - 1
    # to prevent error `noIdentitas has not been reported` every night 1.am nik will be reported.
    customer = Customer.objects.filter(nik=nik).last()
    yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
    has_loan = Loan.objects.filter(
        customer=customer,
        cdate__date__lte=yesterday,
    ).exists()

    # change to reason number 2
    if has_loan:
        is_changed = True
        logger.info(
            {
                'message': 'FDCInquiry: change reason when inquiry',
                'nik': nik,
                'process_name': 'based on loan data',
                'old_reason': reason_number,
                'new_reason': FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER,
                'is_changed': is_changed,
            }
        )
        # Change reason to 2
        return FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER, is_changed

    logger.info(
        {
            'message': 'FDCInquiry: return same reason number',
            'nik': nik,
            'process_name': 'not match based on criteria checking',
            'reason': reason_number,
            'is_changed': is_changed,
        }
    )
    return reason_number, is_changed


def get_and_call_certain_status(response, nik, reason, is_changed):

    # Reject the incoming process if `is_changed` is False and reason number is 2
    if not is_changed and reason == FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER:
        logger.info(
            {
                'message': 'FDCInquiry: return same response and reason',
                'nik': nik,
                'reason': reason,
                'is_changed': is_changed,
            }
        )
        return response, reason

    old_reason = reason
    # original_response = response
    try:
        data = response.json()

        # Only allow for status have problem
        # Please use reason 2 and No identitas response
        if str(data['status']).lower() not in (
            FDCStatus.PLEASE_USE_REASON_2.lower(),
            FDCStatus.NO_IDENTITAS_REPORTED.lower(),
        ):
            logger.info(
                {
                    'message': 'FDCInquiry: skip call certain status',
                    'nik': nik,
                    'reason_skip': 'reason status is not {}'.format(FDCStatus.PLEASE_USE_REASON_2),
                    'reason': old_reason,
                }
            )
            return response, reason

        # handle for please use reason 2
        # For the case
        reason = FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER
        if str(data['status']).lower() == FDCStatus.NO_IDENTITAS_REPORTED.lower():

            # for the case noIdentitas has not been reported
            reason = FDCReasonConst.REASON_APPLYING_LOAN

        logger.info(
            {
                'message': 'FDCInquiry: start call FDC',
                'nik': nik,
                'old_reason': old_reason,
                'new_reason': reason,
                'is_changed': is_changed,
            }
        )

        # "re-hit" process FDC Inquiry
        fdc_client = get_julo_fdc_client()
        max_retries_for_rehit = 3
        for attempt in range(1, max_retries_for_rehit + 1):  # 1,2,3
            try:
                response = fdc_client.get_fdc_inquiry_data(nik, reason)
                return response, reason
            except Exception as error:
                logger.error(
                    {
                        'action': 'error when retry rehit',
                        'message': str(error),
                        'nik': nik,
                        'old_reason': old_reason,
                        'new_reason': reason,
                    }
                )
                if attempt < max_retries_for_rehit:
                    time.sleep(1)
                else:
                    raise error
    except Exception as error:
        logger.error(
            {
                'message': str(error),
                'nik': nik,
                'old_reason': old_reason,
                'new_reason': reason,
            }
        )
        raise error


def check_if_fdc_inquiry_exist_filtered_by_date(
    date: date = timezone.localtime(timezone.now()).date(),
):
    # get fdc inquiry for the day from Inquiry Prioritization Analytic db
    fdc_inquiry = (
        FDCInquiryPrioritizationReason2.objects.filter(serving_date=date)
        .order_by('priority_bin')
        .exists()
    )

    if not fdc_inquiry:
        raise JuloException(
            'FDCInquiryPrioritizationReason2 for %s not found' % date.strftime("%Y-%m-%d")
        )

    return fdc_inquiry


def get_fdc_inquiry_from_ana_filtered_by_date(
    priority_bin: int,
    date: date = timezone.localtime(timezone.now()).date(),
):
    # get fdc inquiry for the day from Inquiry Prioritization Analytic db
    fdc_inquiry = FDCInquiryPrioritizationReason2.objects.filter(
        serving_date=date, priority_bin=priority_bin
    ).order_by('priority_bin')

    return fdc_inquiry


def reformat_generated_datetime_fdc(generated_at):
    """
    Reformat data generated from origin format:
    Example: 2024-11-25 | 03:35
    To this format: 2024-11-25 03:35
    """

    if not generated_at:
        return generated_at

    # Remove characters | and remove for double space
    value = generated_at.replace('|', '')
    new_value = re.sub(' +', ' ', value)

    logger.info(
        {
            'message': 're-format generated_at for FDC',
            'origin_value': generated_at,
            'new_value': new_value,
        }
    )

    return new_value


def get_config_fdc_upload_file_sik():

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FDC_UPLOAD_FILE_SIK
    ).last()
    if not setting or not setting.is_active:
        # return default value if setting is not found or not active
        config = {
            'row_limit': FDCFileSIKConst.ROW_LIMIT,
            'retry_limit': FDCFileSIKConst.RETRY_LIMIT,
            'hour_upload_limit': FDCFileSIKConst.HOUR_UPLOAD_LIMIT,
        }
        return config

    config = setting.parameters
    logger.info(
        {
            'message': 'Config for upload file SIK is active',
            'config': config,
        }
    )

    return config


def upload_files_sik_to_fdc_server(
    config,
    list_file_uploads,
    count_of_record,
    retry_count=0,
    last_count=0,
    count_today=0,
):

    if not list_file_uploads:
        return

    fdc_delivery, zip_filename, zip_file = None, None, None

    # Prepare connection to FDC SFTP
    fdc_ftp_client = get_julo_fdc_ftp_client()
    try:
        # Make sure the list must be ascending
        list_files = sorted(list_file_uploads, key=itemgetter('count_today'))

        for item in list_files:

            # skip process if count already uploaded
            count_today = item['count_today']
            if retry_count != 0 and count_today < last_count:
                continue

            zip_filename = item['zip_filename']
            zip_file = item['zip_file']

            fdc_delivery = FDCDelivery.objects.create(
                generated_filename=zip_filename, count_of_record=count_of_record, status='pending'
            )

            # Uploading...
            fdc_ftp_client.put_fdc_data(zip_file, zip_filename)
            fdc_delivery.update_safely(status='completed')

            logger.info(
                {
                    'message': '[Completed] FDC file SIK uploaded',
                    'zip_file_name': zip_filename,
                    'path_dir': str(zip_file),
                }
            )

    except Exception as error:
        logger.error(
            {
                'action': 'upload_FDC_data_to_SFTP',
                'fdc_delivery_id': fdc_delivery.id if fdc_delivery else None,
            }
        )

        # last record will set as error
        fdc_delivery.update_safely(status='error', error=error)
        retry_limit = config.get('retry_limit')
        hour_limit_upload = config.get('hour_limit_upload')

        # run retry if time still in time uploading
        current_datetime = timezone.localtime(timezone.now())
        target_time = datetime.today()
        target_time = target_time.replace(hour=hour_limit_upload, minute=0, second=0)
        target_time = timezone.localtime(target_time)

        if current_datetime < target_time and retry_count <= retry_limit:
            retry_count = retry_count + 1
            last_count = count_today
            logger.info(
                {
                    'message': 'Retry upload SIK',
                    'zip_file': zip_file,
                    'count_today': count_today,
                    'retry_count': retry_count,
                }
            )

            upload_files_sik_to_fdc_server(
                config,
                list_file_uploads,
                count_of_record,
                retry_count=retry_count,
                last_count=last_count,
                count_today=count_today,
            )

        msg = "We CAN NOT SEND data to fdc: {}".format(error)
        notify_failure(msg, channel='#fdc', label_env=True)


def get_list_files_details(path_dir):

    zip_files, list_files = [], []
    for filename in get_list_files(path_dir):
        if os.path.splitext(filename)[1] == '.zip':
            zip_files.append(filename)

    zip_files.sort()
    number_file = 0
    for file in zip_files:
        number_file = number_file + 1
        files = {
            'count_today': number_file,
            'zip_filename': file,
            'zip_file': os.path.join(path_dir, file),
        }
        list_files.append(files)

    return list_files


def get_fdc_status(app: Application) -> bool:
    """
    Get fdc status of application
    """
    credit_score_type = 'B' if check_app_cs_v20b(app) else 'A'
    model = PdCreditModelResult.objects.filter(
        application_id=app.id, credit_score_type=credit_score_type
    ).last()

    if not model:
        model = PdWebModelResult.objects.filter(application_id=app.id).last()

    is_fdc = bool(model and model.has_fdc)

    return is_fdc
