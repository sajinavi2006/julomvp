import os
import shutil
import tempfile
from builtins import str
from datetime import datetime, timedelta

import mock
import pytz
from django.conf import settings
import json
from django.test import TestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from faker import Faker
from mock import MagicMock, patch
from juloserver.julo.models import FDCInquiryLoan
from juloserver.ana_api.models import FDCLoanDataUpload
from requests.models import Response
from django.forms.models import model_to_dict

from juloserver.fdc.clients import get_julo_fdc_ftp_client
from juloserver.fdc.files import (
    parse_fdc_delivery_report,
    parse_fdc_error_data,
    parse_fdc_delivery_statistic,
)
from juloserver.fdc.models import FDCDeliveryReport, FDCOutdatedLoan, FDCInquiry
from juloserver.fdc.services import (
    FDCFileNotFound,
    download_outdated_loans_from_fdc,
    download_result_from_fdc,
    download_statistic_data_from_fdc,
    store_to_temporary_table,
    upload_loans_data_to_fdc,
    get_info_active_loan_from_platforms,
    get_or_non_fdc_inquiry_not_out_date,
    get_and_call_certain_status,
    get_fdc_status,
)
from juloserver.fdc.utils import create_fdc_filename
from juloserver.julo.models import (
    FDCDelivery,
    FDCDeliveryTemp,
    FDCValidationError,
    StatusLookup,
    FDCRiskyHistory,
    FDCDataAsViewV5,
    FDCDelivery,
    UploadAsyncState,
    FDCInquiry,
)

from juloserver.fdc.files import TempDir, parse_fdc_error_data, store_loans_today_into_zipfile
from juloserver.fdc.services import run_fdc_inquiry
from juloserver.fdc.tasks import (
    trigger_download_outdated_loans_from_fdc,
    trigger_download_result_fdc,
    trigger_download_statistic_from_fdc,
    trigger_upload_loans_data_to_fdc,
    j1_record_fdc_risky_history,
    process_run_fdc_inquiry,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.services2 import get_customer_service
from juloserver.julo.tests.factories import (
    FDCInquiryFactory,
    ApplicationFactory,
    FDCInquiryLoanFactory,
    LoanFactory,
    WorkflowFactory,
    FDCLoanDataUploadFactory,
    FDCInquiryFactory,
)
from juloserver.fdc.services import (
    get_and_save_fdc_data,
    determine_inquiry_reason,
)
from juloserver.fdc.clients import (
    FDCClient,
)
from juloserver.fdc.constants import (
    FDCFileSIKConst,
    FDCLoanStatus,
    FDCReasonConst,
    FDCFailureReason,
    FDCStatus,
)

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    GroupFactory,
    FDCInquiryFactory,
    PartnerFactory,
    LoanFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes
import json
from rest_framework import status
from rest_framework.test import APIClient
from juloserver.julovers.tests.factories import UploadAsyncStateFactory
from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory, PdWebModelResultFactory

fake = Faker()


def set_response_inquiry(nik, inquiry_reason, status):

    structure_response = {
        'noIdentitas': nik,
        'noHp': '',
        'mail': '',
        'userId': '810069@afpi.or.id',
        'userName': 'Julo',
        'inquiryReason': inquiry_reason,
        'memberId': '810069',
        'memberName': 'JULO',
        'refferenceId': None,
        'inquiryDate': '2023-08-03',
        'status': status,
        'pinjaman': [
            {
                'id_penyelenggara': '1',
                'jenis_pengguna': 1,
                'nama_borrower': 'MCH',
                'no_identitas': nik,
                'no_npwp': '',
                'no_hp': None,
                'email': None,
                'tgl_perjanjian_borrower': '2023-03-02',
                'tgl_penyaluran_dana': '2023-03-02',
                'nilai_pendanaan': 1150000.0,
                'tgl_pelaporan_data': '2023-04-11',
                'sisa_pinjaman_berjalan': 958330.0,
                'tgl_jatuh_tempo_pinjaman': '2023-09-01',
                'kualitas_pinjaman': '1',
                'dpd_terakhir': 2,
                'dpd_max': 7,
                'status_pinjaman': 'O',
                'jenis_pengguna_ket': 'Individual',
                'kualitas_pinjaman_ket': 'Lancar',
                'status_pinjaman_ket': 'Outstanding',
                'penyelesaian_w_oleh': 'Default',
                'pendanaan_syariah': False,
                'tipe_pinjaman': 'Multiguna',
                'sub_tipe_pinjaman': 'Onetime Loan / Cash Loan',
                'reference': '',
                'id': '5ca24c2898c4548390feffe2c3d27be7',
                'agunan': 'Tidak Memiliki Agunan',
                'tgl_agunan': '2016-09-30',
                'nama_penjamin': '',
                'no_agunan': '',
                'pendapatan': 1100000.0,
            }
        ],
        'historyInquiry': {
            'statistic': {
                '3_hari': 0,
                '7_hari': 0,
                '30_hari': 0,
                '90_hari': 0,
                '180_hari': 0,
                '360_hari': 0,
                '>360_hari': 0,
            },
            'last3DaysInquiry': [
                {'tgl_inquiry': '2023-08-03 10:59:47', 'jml_data': 5, 'hit_by': 'JULO'}
            ],
        },
    }

    return structure_response


def mock_response_fdc_inquiry(*args, **kwargs):

    nik = '3524242400000000'
    structure_response = set_response_inquiry(
        nik,
        FDCFailureReason.REASON_FILTER[1],
        FDCStatus.PLEASE_USE_REASON_2,
    )

    class MockResponseFDCInquiry:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        @staticmethod
        def ok():
            return True

    endpoint = '/api/v5.2/Inquiry?id={}&'.format(nik)
    if '{}reason=1'.format(endpoint) in args[0]:
        return MockResponseFDCInquiry(
            structure_response,
            200,
        )
    elif '{}reason=2'.format(endpoint) in args[0]:

        structure_response.update(
            {
                'status': 'found',
                'inquiryReason': FDCFailureReason.REASON_FILTER[2],
            }
        )
        return MockResponseFDCInquiry(
            structure_response,
            200,
        )


def mock_response_fdc_inquiry_no_identitas(*args, **kwargs):

    nik = '3524242400000000'
    structure_response = set_response_inquiry(
        nik,
        FDCFailureReason.REASON_FILTER[2],
        FDCStatus.NO_IDENTITAS_REPORTED,
    )

    class MockResponseFDCInquiry:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        @staticmethod
        def ok():
            return True

    endpoint = '/api/v5.2/Inquiry?id={}&'.format(nik)
    if '{}reason=1'.format(endpoint) in args[0]:
        structure_response.update(
            {
                'status': 'found',
                'inquiryReason': FDCFailureReason.REASON_FILTER[1],
            }
        )
        return MockResponseFDCInquiry(
            structure_response,
            200,
        )
    elif '{}reason=2'.format(endpoint) in args[0]:

        return MockResponseFDCInquiry(
            structure_response,
            200,
        )


def mock_response_fdc_inquiry_reason_2(*args, **kwargs):

    nik = '3524242400000000'
    structure_response = set_response_inquiry(
        nik,
        FDCFailureReason.REASON_FILTER[2],
        'sukses',
    )

    class MockResponseFDCInquiry:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            return self.json_data

        @staticmethod
        def ok():
            return True

    endpoint = '/api/v5.2/Inquiry?id={}&'.format(nik)
    if '{}reason=2'.format(endpoint) in args[0]:

        return MockResponseFDCInquiry(
            structure_response,
            200,
        )


class TestFDCFiles(TestCase):
    def setUp(self):
        self.statistic_filename = 'statistic_810069.json'
        self.statistic_filename_case_1 = 'statistic_810069_case_1.json'
        self.outdated_filename = '81006920191124SIK03.zip.out'
        self.dirname = os.path.abspath(os.path.dirname(__file__))
        self.parent_dir = os.path.join(self.dirname, 'test_data')
        self.statistic_filepath = os.path.join(self.parent_dir, self.statistic_filename)
        self.statistic_filepath_case_1 = os.path.join(
            self.parent_dir, self.statistic_filename_case_1
        )
        self.outdated_filepath = os.path.join(self.parent_dir, self.outdated_filename)
        self.fdc_result_filename = '81006920191124SIK03'

    def test_parse_fdc_delivery_report(self):
        fdc_delivery_report = parse_fdc_delivery_report(self.statistic_filepath)
        assert fdc_delivery_report == {
            'access_status': 'False',
            'generated_at': '2020-08-13 16:01:28',
            'last_reporting_loan': '2020-05-19',
            'last_uploaded_file_name': None,
            'last_uploaded_sik': None,
            'percentage_updated': 0.4,
            'threshold': 0.2,
            'total_outstanding': 172,
            'total_outstanding_outdated': 172,
            'total_paid_off': 1,
            'total_written_off': 0,
        }

    def test_parse_fdc_delivery_report_case_1(self):
        fdc_delivery_report = parse_fdc_delivery_report(self.statistic_filepath_case_1)
        assert fdc_delivery_report == {
            'access_status': 'False',
            'generated_at': '2020-08-13 16:01:28',
            'last_reporting_loan': '2020-05-19',
            'last_uploaded_file_name': None,
            'last_uploaded_sik': '2020-08-06 09:08:26',
            'percentage_updated': 0.0,
            'threshold': 0.9,
            'total_outstanding': 172,
            'total_outstanding_outdated': 172,
            'total_paid_off': 1,
            'total_written_off': 0,
        }

    def test_parse_fdc_error_data(self):
        fdc_validation_error = parse_fdc_error_data(
            self.fdc_result_filename, self.outdated_filepath
        )
        assert fdc_validation_error == [
            {
                'error': 'status_pinjaman harus diisi; ',
                'filename': '81006920191124SIK03',
                'id_borrower': '1000012650',
                'id_pinjaman': '4176601050',
                'row_number': '185',
            }
        ]

    def test_parse_fdc_delivery_report_case_2(self):
        """
        Check for function reformat generated time with correct value
        """

        statistic_file = os.path.join(self.parent_dir, 'statistic_file_810069_case_2.json')
        statistic_loan = os.path.join(self.parent_dir, 'statistic_loan_810069_case_2.json')
        fdc_delivery_report = parse_fdc_delivery_statistic(
            file_filepath=statistic_loan,
            loan_filepath=statistic_file,
        )
        self.assertEqual(fdc_delivery_report['statistic_file_generated_at'], '2024-11-25 06:00')
        self.assertEqual(fdc_delivery_report['statistic_loan_generated_at'], '2024-11-25 15:12')


class TestFDCUtils(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now()).date()

    def test_define_filename(self):
        new_version_number = 1
        filename = create_fdc_filename(new_version_number)
        assert filename == '810069%sV5-SIK%02d' % (
            (self.today - timedelta(days=1)).strftime("%Y%m%d"),
            new_version_number,
        )


class TestFDCServices(TestCase):
    def setUp(self):
        self.maxDiff = 100000
        self.statistic_filename = 'statistic_810069.json'
        self.result_filename = 'outdated_data_810069_testing.zip'
        self.outdated_filename = '81006920191124SIK03.zip.out'
        self.dirname = os.path.abspath(os.path.dirname(__file__))
        self.parent_dir = os.path.join(self.dirname, 'test_data')
        self.statistic_filepath = os.path.join(self.parent_dir, self.statistic_filename)
        self.temp_directory = tempfile.mkdtemp(dir=self.parent_dir)
        self.fdc_data = [
            {
                'sisa_pinjaman_berjalan': 666670,
                'nama_borrower': 'prod only',
                'no_identitas': '1578990506029122',
                'id_borrower': 1000013363,
                'tgl_pelaporan_data': '20201221',
                'tgl_penyaluran_dana': '20200124',
                'kualitas_pinjaman': 3,
                'no_npwp': 121212,
                'dpd_max': 146,
                'tgl_perjanjian_borrower': '20200124',
                'dpd_terakhir': 146,
                'id_pinjaman': 1673212621,
                'status_pinjaman': 'O',
                'tgl_jatuh_tempo_pinjaman': '20200729',
                'nilai_pendanaan': 4000000,
                'id_penyelenggara': 810069,
                'jenis_pengguna': 1,
                'no_hp': '898912831231',
                'email': 'emailtesting@gmail.com',
                'agunan': '8',
                'tgl_agunan': '20230909',
                'nama_penjamin': 'Mr. Testing',
                'no_agunan': None,
                'pendapatan': 4000000,
            }
        ]
        self.fdc_error_data = [
            {
                'error': 'status_pinjaman harus diisi; ',
                'filename': '81006920191124SIK03',
                'id_borrower': '1000012650',
                'id_pinjaman': '4176601050',
                'row_number': '185',
            }
        ]
        self.fdc_delivery_statistic = {
            'statistic_file_generated_at': '2023-08-07 05:00',
            'status_file': [
                {
                    'total_error': '1 row',
                    'detail_error': '81006920230804V5-SIK02.zip.out',
                    'failed_filename': '81006920230804V5-SIK02.zip',
                    'success_filename': None,
                    'last_uploaded_sik': '2023-08-05 | 11:11',
                    'success_processed_sik': '2023-08-05 | 11:11',
                },
                {
                    'total_error': '1624 row',
                    'detail_error': '81006920230804V5-SIK03.zip.out',
                    'failed_filename': None,
                    'success_filename': '81006920230804V5-SIK03.zip',
                    'last_uploaded_sik': '2023-08-05 | 11:22',
                    'success_processed_sik': '2023-08-05 | 11:22',
                },
                {
                    'total_error': '1624 row',
                    'detail_error': '81006920230804V5-SIK04.zip.out',
                    'failed_filename': None,
                    'success_filename': '81006920230804V5-SIK04.zip',
                    'last_uploaded_sik': '2023-08-05 | 11:27',
                    'success_processed_sik': '2023-08-05 | 11:28',
                },
                {
                    'total_error': '1 row',
                    'detail_error': '81006920230804SIK01.zip.out',
                    'failed_filename': '81006920230804SIK01.zip',
                    'success_filename': None,
                    'last_uploaded_sik': '2023-08-05 | 10:58',
                    'success_processed_sik': '2023-08-05 | 10:58',
                },
            ],
            'statistic_loan_generated_at': '2023-08-06 14:04',
            'status_loan': [
                {
                    'tresshold': '90%',
                    'percentage': '0.00%',
                    'tot_nominal': 112531931834,
                    'tot_status_f': None,
                    'tot_status_l': 11111,
                    'tot_status_o': 20560,
                    'tot_status_r': 0,
                    'tot_status_s': None,
                    'tot_status_w': 11683,
                    'access_status': 'False',
                    'not_updated_o': 20560,
                    'not_updated_list': 'outdated_data_810069.zip',
                }
            ],
            'quality_loan': [
                {
                    'lancar (0)': 15772,
                    'macet (>90)': 86,
                    'diragukan (61-90)': 0,
                    'kurang_lancar (31-60)': 10173,
                    'perhatian_khusus (1-30)': 17323,
                }
            ],
        }

    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_outdated_loans_from_fdc(self, mock_get_fdc_ftp_connection):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection

        download_result_from_fdc()
        fdc_outdated_loan = FDCOutdatedLoan.objects.all()
        assert fdc_outdated_loan.count() == 0

    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_result_from_fdc(self, mock_get_fdc_ftp_connection):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection
        download_result_from_fdc()
        fdc_delivery_report = FDCValidationError.objects.all()
        assert fdc_delivery_report.count() == 0

    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_upload_loans_data_to_fdc(self, mock_get_fdc_ftp_connection):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection
        upload_loans_data_to_fdc()

    def test_store_to_temporary_table(self):
        store_to_temporary_table(self.fdc_data)
        fdc_delivery_temp = FDCDeliveryTemp.objects.last()
        self.assertIsNotNone(fdc_delivery_temp)
        self.assertEqual(fdc_delivery_temp.no_hp, '898912831231')
        self.assertEqual(fdc_delivery_temp.kualitas_pinjaman, 3)
        self.assertEqual(fdc_delivery_temp.email, 'emailtesting@gmail.com')
        self.assertEqual(fdc_delivery_temp.agunan, '8')
        self.assertEqual(fdc_delivery_temp.tgl_agunan, '20230909')
        self.assertEqual(fdc_delivery_temp.nama_penjamin, 'Mr. Testing')
        self.assertEqual(fdc_delivery_temp.dpd_max, 146)
        self.assertEqual(fdc_delivery_temp.dpd_terakhir, 146)

    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_statistic_data_from_fdc_case_1(self, mock_connection):
        mock_connection.return_value.is_statistic_json_file_exists.return_value = False
        with self.assertRaises(IOError) as context:
            download_statistic_data_from_fdc()
        self.assertTrue('No such file' in str(context.exception))

    def test_download_outdated_loans_from_fdc_case_1(self):
        with patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection') as connection:
            connection.return_value.isfile.return_value = False
            with self.assertRaises(IOError) as context:
                download_outdated_loans_from_fdc()
            self.assertTrue('No such file' in str(context.exception))

    @patch('juloserver.fdc.services.parse_fdc_error_data')
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_result_from_fdc_case_1(
        self, mock_get_fdc_ftp_connection, mock_parse_fdc_data
    ):
        mock_get_fdc_ftp_connection.return_value.is_fdc_result_exists.return_value = True
        download_result_from_fdc()
        assert not mock_parse_fdc_data.called

    @patch('juloserver.fdc.services.notify_failure')
    @patch('juloserver.fdc.services.parse_fdc_error_data')
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_result_from_fdc_case_2(
        self, mock_get_fdc_ftp_connection, mock_parse_fdc_data, mock_notify_failure
    ):
        mock_get_fdc_ftp_connection.return_value.is_fdc_result_exists.return_value = True
        mock_parse_fdc_data.return_value = self.fdc_error_data
        download_result_from_fdc()
        assert not mock_notify_failure.called

    @patch('juloserver.fdc.services.notify_failure')
    @patch('juloserver.fdc.services.parse_fdc_delivery_statistic')
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_statistic_data_from_fdc_case_2(
        self, mock_get_fdc_ftp_connection, mock_parse_fdc_delivery_statistic, mock_notify_failure
    ):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection
        mock_parse_fdc_delivery_statistic.return_value = self.fdc_delivery_statistic
        download_statistic_data_from_fdc()
        assert mock_parse_fdc_delivery_statistic.called
        assert mock_notify_failure.called

    @patch('juloserver.fdc.services.yield_outdated_loans_data_from_file')
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_outdated_loans_from_fdc_case_2(
        self, mock_get_fdc_ftp_connection, mock_yield_outdated_loans_data_from_file
    ):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection

        download_outdated_loans_from_fdc()
        assert mock_yield_outdated_loans_data_from_file.called

    @patch('juloserver.fdc.services.notify_failure')
    @patch('juloserver.fdc.services.parse_fdc_error_data')
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_download_result_from_fdc_case_3(
        self, mock_get_fdc_ftp_connection, mock_parse_fdc_error_data, mock_notify_failure
    ):
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection = mock_connection
        fdc_deliveries_today = FDCDelivery.objects.create(status='completed')
        mock_parse_fdc_error_data.return_value = self.fdc_error_data
        download_result_from_fdc()
        assert mock_notify_failure.called

    def test_j1_is_risky(self):
        account = AccountFactory()
        workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        application = ApplicationFactory(account=account, workflow=workflow)
        inquiry_190 = FDCInquiryFactory(
            inquiry_status='success',
            inquiry_reason='2 - Monitor Outstanding Borrower',
            application_status_code=190,
            application_id=application.id,
            customer_id=application.customer.id,
        )
        inquiry_100 = FDCInquiryFactory(
            inquiry_status='success',
            inquiry_reason='1 - Applying loan via Platform',
            application_status_code=100,
            application_id=application.id,
            customer_id=application.customer.id,
        )
        AccountPaymentFactory(account=account)
        FDCInquiryLoanFactory(
            fdc_inquiry_id=inquiry_190.id, is_julo_loan=False, status_pinjaman='Outstanding'
        )
        LoanFactory(account=account, application=application)
        is_risky = get_customer_service().j1_check_risky_customer(application.id)
        self.assertTrue(is_risky)
        j1_record_fdc_risky_history(application_id=application.id, is_fdc_risky=is_risky)
        self.assertTrue(FDCRiskyHistory.objects.filter(application_id=application.id).exists())

    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch.object(FDCClient, 'get_fdc_inquiry_data')
    def test_inquiry_for_version_5_fdc(self, mock_response_fdc_inquiry, mock_store_initial):

        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)

        structure_response = {
            'noIdentitas': nik,
            'noHp': '',
            'mail': '',
            'userId': '810069@afpi.or.id',
            'userName': 'Julo',
            'inquiryReason': '1 - Applying loan via Platform',
            'memberId': '810069',
            'memberName': 'JULO',
            'refferenceId': None,
            'inquiryDate': '2023-08-03',
            'status': 'Found',
            'pinjaman': [
                {
                    'id_penyelenggara': '1',
                    'jenis_pengguna': 1,
                    'nama_borrower': 'MCH',
                    'no_identitas': '3524242400000000',
                    'no_npwp': '',
                    'no_hp': None,
                    'email': None,
                    'tgl_perjanjian_borrower': '2023-03-02',
                    'tgl_penyaluran_dana': '2023-03-02',
                    'nilai_pendanaan': 1150000.0,
                    'tgl_pelaporan_data': '2023-04-11',
                    'sisa_pinjaman_berjalan': 958330.0,
                    'tgl_jatuh_tempo_pinjaman': '2023-09-01',
                    'kualitas_pinjaman': '1',
                    'dpd_terakhir': 2,
                    'dpd_max': 7,
                    'status_pinjaman': 'O',
                    'jenis_pengguna_ket': 'Individual',
                    'kualitas_pinjaman_ket': 'Lancar',
                    'status_pinjaman_ket': 'Outstanding',
                    'penyelesaian_w_oleh': 'Default',
                    'pendanaan_syariah': False,
                    'tipe_pinjaman': 'Multiguna',
                    'sub_tipe_pinjaman': 'Onetime Loan / Cash Loan',
                    'reference': '',
                    'id': '5ca24c2898c4548390feffe2c3d27be7',
                    'agunan': 'Tidak Memiliki Agunan',
                    'tgl_agunan': '2016-09-30',
                    'nama_penjamin': '',
                    'no_agunan': '',
                    'pendapatan': 1100000.0,
                }
            ],
            'historyInquiry': {
                'statistic': {
                    '3_hari': 0,
                    '7_hari': 0,
                    '30_hari': 0,
                    '90_hari': 0,
                    '180_hari': 0,
                    '360_hari': 0,
                    '>360_hari': 0,
                },
                'last3DaysInquiry': [
                    {'tgl_inquiry': '2023-08-03 10:59:47', 'jml_data': 5, 'hit_by': 'JULO'}
                ],
            },
        }

        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')

        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}
        mock_response_fdc_inquiry.return_value = mock_response
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)
        self.fdc_inquiry.refresh_from_db()
        all_loan_inquiry = list(FDCInquiryLoan.objects.filter(no_identitas=nik))
        total_loan_inquiry = len(all_loan_inquiry)
        loan_inquiry = all_loan_inquiry[-1]
        self.assertEqual(loan_inquiry.no_identitas, nik)
        self.assertEqual(loan_inquiry.nama_borrower, 'MCH')
        self.assertEqual(loan_inquiry.jenis_pengguna, 'Individual')
        self.assertEqual(loan_inquiry.pendapatan, 1100000)

        # test clone data
        new_fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        new_fdc_inquiry.customer_id = self.fdc_inquiry.customer_id
        new_fdc_inquiry.save()
        fdc_inquiry_data = {'id': new_fdc_inquiry.id, 'nik': new_fdc_inquiry.nik}
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)
        new_fdc_inquiry.refresh_from_db()
        self.assertTrue(new_fdc_inquiry.status == self.fdc_inquiry.status == 'Found')
        all_loan_inquiry = list(FDCInquiryLoan.objects.filter(no_identitas=nik))
        self.assertEqual(len(all_loan_inquiry), total_loan_inquiry * 2)
        new_loan_inquiry = FDCInquiryLoan.objects.filter(fdc_inquiry=new_fdc_inquiry).last()
        new_fdc_inquiry_dict = model_to_dict(
            new_fdc_inquiry, exclude=['id', 'cdate', 'udate', 'application']
        )
        new_loan_inquiry_dict = model_to_dict(
            new_loan_inquiry, exclude=['id', 'cdate', 'udate', 'fdc_inquiry']
        )
        loan_inquiry_dict = model_to_dict(
            loan_inquiry, exclude=['id', 'cdate', 'udate', 'fdc_inquiry']
        )
        fdc_inquiry_dict = model_to_dict(
            self.fdc_inquiry, exclude=['id', 'cdate', 'udate', 'application']
        )
        self.assertEqual(new_fdc_inquiry_dict, fdc_inquiry_dict)
        self.assertEqual(new_loan_inquiry_dict, loan_inquiry_dict)

    @patch('juloserver.fdc.constants.FDCFileSIKConst.ROW_LIMIT', 500)
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_upload_loans_data_to_fdc_with_split_file(self, mock_get_fdc_ftp_connection):

        # create the data
        target_source = 1549
        for index in range(target_source):
            FDCLoanDataUploadFactory(
                fdc_loan_data_upload_id=index,
                id_penyelenggara=810069,
                id_borrower=1000008110,
                jenis_pengguna=1,
                nama_borrower='Mr. Testing',
                no_identitas='1590750506020993',
                id_pinjaman=1000001697,
                tgl_perjanjian_borrower='20200529',
                tgl_penyaluran_dana='20200529',
                nilai_pendanaan=1000000,
                tgl_pelaporan_data='20230807',
                sisa_pinjaman_berjalan=1000000,
                tgl_jatuh_tempo_pinjaman=20200929,
                kualitas_pinjaman=5,
                dpd_terakhir=1043,
                dpd_max=1135,
                status_pinjaman='W',
                penyelesaian_w_oleh='0',
                syariah='0',
                tipe_pinjaman=2,
                sub_tipe_pinjaman=20,
                reference=None,
                no_hp='6286634613699',
                email='testing@gmail.com',
                agunan='8',
                pendapatan=12000001,
            )

        count_source_data = FDCLoanDataUpload.objects.count()
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection
        upload_loans_data_to_fdc()

        data_delivery = FDCDelivery.objects.filter(status='completed')
        self.assertEqual(count_source_data, target_source)
        self.assertIsNotNone(data_delivery)
        all_data_delivery = FDCDelivery.objects.count()
        self.assertEqual(all_data_delivery, 4)

    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch.object(FDCClient, 'get_fdc_inquiry_data')
    def test_inquiry_for_version_5_2_fdc(self, mock_response_fdc_inquiry, mock_store_initial):

        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)

        structure_response = {
            'noIdentitas': nik,
            'noHp': '',
            'mail': '',
            'userId': '810069@afpi.or.id',
            'userName': 'Julo',
            'inquiryReason': '1 - Applying loan via Platform',
            'memberId': '810069',
            'memberName': 'JULO',
            'refferenceId': None,
            'inquiryDate': '2023-08-03',
            'status': 'Found',
            'pinjaman': [
                {
                    'id_penyelenggara': '1',
                    'jenis_pengguna': 1,
                    'nama_borrower': 'MCH',
                    'no_identitas': '3524242400000000',
                    'no_npwp': '',
                    'no_hp': None,
                    'email': None,
                    'tgl_perjanjian_borrower': '2023-03-02',
                    'tgl_penyaluran_dana': '2023-03-02',
                    'nilai_pendanaan': 1150000.0,
                    'tgl_pelaporan_data': '2023-04-11',
                    'sisa_pinjaman_berjalan': 958330.0,
                    'tgl_jatuh_tempo_pinjaman': '2023-09-01',
                    'kualitas_pinjaman': '1',
                    'dpd_terakhir': 2,
                    'dpd_max': 7,
                    'status_pinjaman': 'O',
                    'jenis_pengguna_ket': 'Individual',
                    'kualitas_pinjaman_ket': 'Lancar',
                    'status_pinjaman_ket': 'Outstanding',
                    'penyelesaian_w_oleh': 'Default',
                    'pendanaan_syariah': False,
                    'tipe_pinjaman': 'Multiguna',
                    'sub_tipe_pinjaman': 'Onetime Loan / Cash Loan',
                    'reference': '',
                    'id': '5ca24c2898c4548390feffe2c3d27be7',
                    'agunan': 'Tidak Memiliki Agunan',
                    'tgl_agunan': '2016-09-30',
                    'nama_penjamin': '',
                    'no_agunan': '',
                    'pendapatan': 1100000.0,
                }
            ],
            'historyInquiry': {
                'statistic': {
                    '3_hari': 0,
                    '7_hari': 0,
                    '30_hari': 0,
                    '90_hari': 0,
                    '180_hari': 0,
                    '360_hari': 0,
                    '>360_hari': 0,
                },
                'last3DaysInquiry': [
                    {'tgl_inquiry': '2023-08-03 10:59:47', 'jml_data': 5, 'hit_by': 'JULO'}
                ],
            },
        }

        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')

        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}
        mock_response_fdc_inquiry.return_value = mock_response
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)
        loan_inquiry = FDCInquiryLoan.objects.filter(no_identitas=nik).last()
        self.assertEqual(loan_inquiry.no_identitas, nik)
        self.assertEqual(loan_inquiry.nama_borrower, 'MCH')
        self.assertEqual(loan_inquiry.jenis_pengguna, 'Individual')
        self.assertEqual(loan_inquiry.pendapatan, 1100000)

    @patch('juloserver.fdc.constants.FDCFileSIKConst.ROW_LIMIT', 500)
    @patch('juloserver.fdc.clients.FDCFTPClient.get_fdc_ftp_connection')
    def test_upload_loans_data_to_fdc_with_split_file(self, mock_get_fdc_ftp_connection):

        # create the data
        target_source = 1549
        for index in range(target_source):
            FDCLoanDataUploadFactory(
                fdc_loan_data_upload_id=index,
                id_penyelenggara=810069,
                id_borrower=1000008110,
                jenis_pengguna=1,
                nama_borrower='Mr. Testing',
                no_identitas='1590750506020993',
                id_pinjaman=1000001697,
                tgl_perjanjian_borrower='20200529',
                tgl_penyaluran_dana='20200529',
                nilai_pendanaan=1000000,
                tgl_pelaporan_data='20230807',
                sisa_pinjaman_berjalan=1000000,
                tgl_jatuh_tempo_pinjaman=20200929,
                kualitas_pinjaman=5,
                dpd_terakhir=1043,
                dpd_max=1135,
                status_pinjaman='W',
                penyelesaian_w_oleh='0',
                syariah='0',
                tipe_pinjaman=2,
                sub_tipe_pinjaman=20,
                reference=None,
                no_hp='6286634613699',
                email='testing@gmail.com',
                agunan='8',
                pendapatan=12000001,
            )

        count_source_data = FDCLoanDataUpload.objects.count()
        mock_connection = MagicMock()
        mock_get_fdc_ftp_connection.return_value = mock_connection
        upload_loans_data_to_fdc()

        data_delivery = FDCDelivery.objects.filter(status='completed')
        self.assertEqual(count_source_data, target_source)
        self.assertIsNotNone(data_delivery)
        all_data_delivery = FDCDelivery.objects.count()
        self.assertEqual(all_data_delivery, 4)

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(2, True))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry)
    def test_inquiry_with_please_reason_2(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):

        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)
        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, 'found')
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[2])

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(2, False))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry)
    def test_inquiry_with_changed_but_the_variable_keep_false(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):

        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)
        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, 'found')
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[2])

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(2, True))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry_no_identitas)
    def test_inquiry_with_no_identitas_reported(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):
        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}

        # call fdc start with reason 1
        # and mock_determine_reason will change it to reason 2
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)

        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, 'found')
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[1])

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(1, False))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry)
    def test_inquiry_with_case_reason_1_changed_false(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):
        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}

        # call fdc start with reason 1
        # and mock_determine_reason will change it to reason 2
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)

        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, 'found')
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[2])

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(2, True))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry)
    def test_inquiry_with_case_reason_2_changed_true(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):
        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}

        # call fdc start with reason 1
        # and mock_determine_reason will change it to reason 2
        get_and_save_fdc_data(fdc_inquiry_data, reason=1, retry=0)

        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, FDCStatus.FOUND)
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[2])

    @patch('juloserver.fdc.services.determine_inquiry_reason', return_value=(2, False))
    @patch('juloserver.fdc.services.store_initial_fdc_inquiry_loan_data')
    @patch('requests.get', side_effect=mock_response_fdc_inquiry_reason_2)
    def test_inquiry_with_case_reason_2_changed_false(
        self, mock_response, mock_store_initial, mock_determine_reason
    ):
        nik = '3524242400000000'
        self.fdc_inquiry = FDCInquiryFactory(nik=nik, status=None)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.fdc_inquiry.nik}

        # call fdc start with reason 1
        # and mock_determine_reason will change it to reason 2
        get_and_save_fdc_data(fdc_inquiry_data, reason=2, retry=0)

        data_inquiry = FDCInquiry.objects.filter(nik=nik)
        self.assertEqual(data_inquiry.count(), 1)
        self.assertEqual(data_inquiry.last().status, 'sukses')
        self.assertEqual(data_inquiry.last().inquiry_reason, FDCFailureReason.REASON_FILTER[2])


class TestRunFDCInquiryApi(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory()
        self.fdc_inquiry_data = {'application_xid': 1002931231, 'nik_spouse': '12345678910'}
        self.partner = PartnerFactory(user=self.user)
        self.status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL,
        )
        self.application = ApplicationFactory(
            application_xid=self.fdc_inquiry_data['application_xid'],
            customer=self.customer,
            status=self.status,
            partner=self.partner,
        )
        self.group = GroupFactory(name="fdc_inquiry")
        self.user.groups.add(self.group)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name="fdc_configuration",
            parameters={
                'application_process': {'test': 'test'},
            },
        )
        self.upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.RUN_FDC_INQUIRY_CHECK,
            service='oss',
            file="test.csv",
        )

    @patch('juloserver.fdc.tasks.logger')
    def test_run_fdc_inquiry_api_tasks_with_no_upload_async_state(self, mock_logger) -> None:
        process_run_fdc_inquiry(123123)
        mock_logger.info.assert_called_once_with(
            {
                'action': 'process_run_fdc_inquiry',
                'message': 'File not found',
                'upload_async_state_id': 123123,
            }
        )

    def test_run_fdc_inquiry_api_services_application_does_not_exist(self) -> None:
        self.fdc_inquiry_data['application_xid'] = 0
        is_success, note = run_fdc_inquiry(self.fdc_inquiry_data)
        self.assertEqual(is_success, False)
        self.assertEqual(
            note, 'application not found {}'.format(self.fdc_inquiry_data['application_xid'])
        )

    def test_run_fdc_inquiry_api_services_feature_setting_does_not_exist(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        is_success, note = run_fdc_inquiry(self.fdc_inquiry_data)
        self.assertEqual(is_success, False)
        self.assertEqual(note, 'fdc feature not found None')


class TestFDCActiveLoanChecking(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory()
        self.fdc_inquiry_data = {'application_xid': 1002931231, 'nik_spouse': '12345678910'}
        self.partner = PartnerFactory(user=self.user)
        self.status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL,
        )
        self.application = ApplicationFactory(
            application_xid=self.fdc_inquiry_data['application_xid'],
            customer=self.customer,
            status=self.status,
            partner=self.partner,
        )
        self.inquiry_2 = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.nearest_due_date = datetime(2023, 12, 21).date()
        self.nearest_due_date_2 = datetime(2023, 12, 22).date()
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 30),
        )
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=2,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date_2,
        )
        self.list_fdc_3 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=3,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )

        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=4,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.FULLY_PAID,
            tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 15),
        )

    def test_check_active_loans_with_n_platform_not_is_eligible(self):
        number_platforms = 3
        day_diff = 2
        inquiry = get_or_non_fdc_inquiry_not_out_date(self.application.pk, day_diff)
        (
            nearest_due_date,
            count_platforms,
            count_active_loans,
        ) = get_info_active_loan_from_platforms(inquiry.pk)

        assert count_platforms == 3
        assert count_active_loans == 6
        assert nearest_due_date == self.nearest_due_date

    @patch('juloserver.fdc.services.timezone.now')
    def test_check_active_loans_with_n_platform_with_out_date(self, mock_time_zone):
        day_diff = 2
        mock_time_zone.return_value = self.inquiry_2.cdate + relativedelta(days=day_diff + 1)
        inquiry = get_or_non_fdc_inquiry_not_out_date(self.application.pk, day_diff)
        assert inquiry == None

    def test_check_active_loans_with_n_platform_with_is_eligible(self):
        number_platforms = 3
        day_diff = 2
        list_ids_fdc_3 = [fdc.pk for fdc in self.list_fdc_3]
        FDCInquiryLoan.objects.filter(pk__in=list_ids_fdc_3).update(
            status_pinjaman=FDCLoanStatus.FULLY_PAID
        )
        inquiry = get_or_non_fdc_inquiry_not_out_date(self.application.pk, day_diff)
        (
            nearest_due_date,
            count_platforms,
            count_active_loans,
        ) = get_info_active_loan_from_platforms(inquiry.pk)

        assert count_platforms == 2
        assert count_active_loans == 4
        assert nearest_due_date == self.nearest_due_date_2


class TestDetermineFDCInquiryReason(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.nik_dummy = '323232393'
        self.customer = CustomerFactory(user=self.user, nik=self.nik_dummy)
        self.application = ApplicationFactory(
            customer=self.customer,
            ktp=self.nik_dummy,
        )
        self.fdc_data = {
            'nik': self.nik_dummy,
            'id': 1,
        }
        self.account = AccountFactory()

    def test_not_change_reason_inquiry(self):

        # default reason number
        reason_number = FDCReasonConst.REASON_APPLYING_LOAN

        # result checking
        result, is_changed = determine_inquiry_reason(self.fdc_data, reason_number)
        self.assertEqual(result, FDCReasonConst.REASON_APPLYING_LOAN)
        self.assertFalse(is_changed)

    def test_change_reason_based_on_loan_data_today(self):

        # default reason number
        reason_number = FDCReasonConst.REASON_APPLYING_LOAN

        # create loan data
        loan_data = LoanFactory(account=self.account, application=self.application)

        # result checking
        result, is_changed = determine_inquiry_reason(self.fdc_data, reason_number)
        self.assertEqual(result, FDCReasonConst.REASON_APPLYING_LOAN)
        self.assertFalse(is_changed)

    def test_change_reason_based_on_loan_data_yesterday(self):

        # default reason number
        reason_number = FDCReasonConst.REASON_APPLYING_LOAN

        # create loan data
        loan_data = LoanFactory(
            account=self.account,
            customer=self.customer,
        )

        # result checking
        result, is_changed = determine_inquiry_reason(self.fdc_data, reason_number)
        self.assertEqual(result, FDCReasonConst.REASON_APPLYING_LOAN)
        self.assertFalse(is_changed)

        # update cdate to yesterday data
        cdate = timezone.localtime(timezone.now()).date() - timedelta(days=1)
        loan_data.update_safely(cdate=cdate)

        # result checking
        result, is_changed = determine_inquiry_reason(self.fdc_data, reason_number)
        self.assertEqual(result, FDCReasonConst.REASON_MONITOR_OUTSTANDING_BORROWER)
        self.assertTrue(is_changed)


class TestGetFDCStatus(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.nik_dummy = '323232393'
        self.customer = CustomerFactory(user=self.user, nik=self.nik_dummy)
        self.application = ApplicationFactory(
            customer=self.customer,
            ktp=self.nik_dummy,
        )
        self.account = AccountFactory()

    def test_get_fdc_status_no_models(self):
        is_fdc = get_fdc_status(self.application)

        expected_fdc = False
        assert expected_fdc == is_fdc

    @patch("juloserver.fdc.services.check_app_cs_v20b")
    def test_get_fdc_status_with_pd_model(self, mock_check_app_cs):
        mock_check_app_cs.return_value = True
        model = PdCreditModelResultFactory(
            application_id=self.application.id,
            has_fdc=False,
            credit_score_type='B',
        )

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, False)

        # add another model, True fdc
        model.delete()
        mock_check_app_cs.return_value = True
        model = PdCreditModelResultFactory(
            application_id=self.application.id,
            has_fdc=True,
            credit_score_type='B',
        )

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, True)

        #  type A => non result
        mock_check_app_cs.return_value = False

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, False)

    @patch("juloserver.fdc.services.check_app_cs_v20b")
    def test_get_fdc_status_with_web_model(self, mock_check_app_cs):
        mock_check_app_cs.return_value = True
        model = PdWebModelResultFactory(
            application_id=self.application.id,
            has_fdc=False,
        )

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, False)

        # add another model, True fdc
        model.delete()
        mock_check_app_cs.return_value = True
        model = PdWebModelResultFactory(
            application_id=self.application.id,
            has_fdc=True,
        )

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, True)

        #  type A, same result
        mock_check_app_cs.return_value = False

        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, True)

    @patch("juloserver.fdc.services.check_app_cs_v20b")
    def test_get_fdc_status_with_pd_and_web_model(self, mock_check_app_cs):
        # false for credit model, true for web model
        mock_check_app_cs.return_value = True
        PdCreditModelResultFactory(
            application_id=self.application.id,
            has_fdc=False,
            credit_score_type='B',
        )
        PdWebModelResultFactory(
            application_id=self.application.id,
            has_fdc=True,
        )

        # will prioritize credit model, so will be False
        is_fdc = get_fdc_status(self.application)
        self.assertEqual(is_fdc, False)
