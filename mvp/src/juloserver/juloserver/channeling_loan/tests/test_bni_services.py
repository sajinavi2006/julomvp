import copy
import unittest
from io import BytesIO
from typing import List, Any
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import RequestFactory

import openpyxl

from juloserver.channeling_loan.exceptions import (
    BNIChannelingLoanSKRTPNotFound,
    BNIChannelingLoanKTPNotFound,
    BNIChannelingLoanSelfieNotFound,
)
from datetime import timedelta, datetime
from unittest import mock
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from juloserver.julocore.python2.utils import py2round

from juloserver.channeling_loan.constants import (
    ChannelingConst,
    ChannelingStatusConst,
    ChannelingApprovalStatusConst,
    ChannelingActionTypeConst,
)
from juloserver.channeling_loan.constants.bni_constants import (
    BNIDisbursementConst,
    BNISupportingDisbursementDocumentConst,
)
from juloserver.channeling_loan.models import ChannelingLoanStatus
from juloserver.channeling_loan.services.bni_services import (
    BNIMappingServices,
    BNIDisbursementServices,
    BNIRepaymentServices,
    construct_bni_xlsx_bytes,
    send_file_for_channeling_to_bni,
)
from juloserver.channeling_loan.services.channeling_services import GeneralChannelingData
from juloserver.channeling_loan.services.interest_services import BNIInterest
from juloserver.channeling_loan.tests.factories import (
    ChannelingEligibilityStatusFactory,
    ChannelingLoanStatusFactory,
)
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.julo.tests.factories import (
    LoanFactory,
    CustomerFactory,
    ImageFactory,
    DocumentFactory,
    FeatureSettingFactory,
    ApplicationFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
)
from juloserver.channeling_loan.constants.bni_constants import BNI_DEFAULT_INTEREST
from juloserver.channeling_loan.models import (
    ChannelingLoanPayment,
)


class TestBNIDisbursementServices(TestCase):
    def setUp(self):
        self.service = BNIDisbursementServices()

    def test_construct_bni_disbursement_data(self):
        bank_account_destination = BankAccountDestinationFactory()
        customer = CustomerFactory(mother_maiden_name='Test Mother Maiden Name')
        loan = LoanFactory(customer=customer, bank_account_destination=bank_account_destination)
        first_payment = loan.payment_set.get(payment_number=1)

        data = self.service.construct_bni_disbursement_data(loan=loan)
        self.assertIsNotNone(data)
        self.assertEqual(data['NO'], 1)
        self.assertEqual(data['ORG'], '')
        self.assertEqual(data['SUB TYPE'], '')
        self.assertEqual(data['APP ID'], str(loan.loan_xid))
        self.assertEqual(data['CUST NUM'], '')
        self.assertEqual(data['CUST NUM CORPORATE'], '')
        self.assertEqual(data['EMPLOYEE REF CODE'], '')
        self.assertEqual(data['SOURCE CODE'], '')
        self.assertTrue(data['NAMA KTP'] in customer.fullname)
        self.assertTrue(len(data['NAMA KTP']) <= 30)
        self.assertTrue(data['NAMA PADA KARTU'] in customer.fullname)
        self.assertTrue(len(data['NAMA PADA KARTU']) <= 20)
        self.assertIsNotNone(data['DOB'])
        self.assertEqual(data['JENIS KELAMIN'], 'P' if customer.gender == 'Pria' else 'W')
        self.assertEqual(data['NO KTP'], customer.nik)
        self.assertTrue(data['NAMA IBU KANDUNG'] in customer.mother_maiden_name)
        self.assertTrue(len(data['NAMA IBU KANDUNG']) <= 20)
        self.assertEqual(data['JABATAN'], customer.job_type)
        self.assertEqual(data['PENGHASILAN GAJI'], str(customer.monthly_income))
        self.assertEqual(data['NO REKENING'], bank_account_destination.account_number)
        self.assertEqual(data['CREDIT LIMIT'], str(loan.loan_amount))
        self.assertEqual(len(data['TANGGAL TAGIHAN']), 2)
        self.assertEqual(int(data['TANGGAL TAGIHAN']), first_payment.due_date.day)
        self.assertTrue(data['ALAMAT RUMAH 1'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT RUMAH 1']) <= 30)
        self.assertTrue(data['ALAMAT RUMAH 2'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT RUMAH 2']) <= 30)
        self.assertTrue(data['ALAMAT RUMAH 3'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT RUMAH 3']) <= 30)
        self.assertTrue(data['ALAMAT RUMAH 4'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT RUMAH 4']) <= 30)
        self.assertEqual(data['KOTA'], customer.address_kabupaten)
        self.assertTrue(data['KODE POS'] in customer.address_kodepos)
        self.assertTrue(len(data['KODE POS']) <= 5)
        self.assertEqual(data['KODE AREA'], '')
        self.assertEqual(data['TELP RUMAH'], customer.phone)
        self.assertTrue(data['ALAMAT KANTOR 1'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT KANTOR 1']) <= 30)
        self.assertTrue(data['ALAMAT KANTOR 2'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT KANTOR 2']) <= 30)
        self.assertTrue(data['ALAMAT KANTOR 3'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT KANTOR 3']) <= 30)
        self.assertTrue(data['ALAMAT KANTOR 4'] in customer.address_street_num)
        self.assertTrue(len(data['ALAMAT KANTOR 4']) <= 30)
        self.assertEqual(data['TELP KANTOR'], customer.phone)
        self.assertEqual(data['HANDPHONE'], customer.phone)
        self.assertEqual(
            data['EMERGENCY CONTACT'], BNIMappingServices.get_emergency_contact(customer=customer)
        )
        self.assertEqual(data['HUBUNGAN'], BNIMappingServices.get_hubungan(customer=customer))
        self.assertEqual(data['KODE TELP EC'], '')
        self.assertEqual(data['TELP EC'], BNIMappingServices.get_telp_ec(customer=customer))
        self.assertEqual(data['PENGIRIMAN BILLING'], '')
        self.assertEqual(data['PENGIRIMAN KARTU'], '')
        self.assertEqual(data['NO KK BANK LAIN'], '')
        self.assertEqual(data['IDENTITAS PADA KARTU'], '')
        self.assertEqual(data['CASH LIMIT'], str(loan.loan_amount))
        self.assertEqual(data['NPWP'], customer.nik)
        self.assertEqual(data['TENOR CICILAN'], str(loan.loan_duration))
        self.assertIsNone(data['POB'])  # customer.birth_place is None in the factory

        # Check original constant is not changed
        self.assertEqual(
            type(BNIDisbursementConst.DISBURSEMENT_DATA_MAPPING['NO']), GeneralChannelingData
        )

    @patch('juloserver.channeling_loan.services.bni_services.download_file_from_oss')
    def test_get_bni_supporting_disbursement_documents(self, mock_download):
        loan = LoanFactory()
        application = loan.get_application

        # TEST SKRTP NOT FOUND
        with self.assertRaises(BNIChannelingLoanSKRTPNotFound):
            self.service.get_bni_supporting_disbursement_documents(
                loan=loan,
                is_skip_download_files=False,
            )

        # TEST KTP NOT FOUND
        DocumentFactory(
            loan_xid=loan.loan_xid,
            document_source=loan.id,
            document_type='skrtp_julo',
            url='skrtp_url',
        )
        with self.assertRaises(BNIChannelingLoanKTPNotFound):
            self.service.get_bni_supporting_disbursement_documents(
                loan=loan,
                is_skip_download_files=False,
            )

        # TEST SELFIE NOT FOUND
        ImageFactory(image_source=application.id, image_type='ktp_self', url='ktp_url')
        with self.assertRaises(BNIChannelingLoanSelfieNotFound):
            self.service.get_bni_supporting_disbursement_documents(
                loan=loan,
                is_skip_download_files=False,
            )

        # TEST SUCCESS CASE
        ImageFactory(image_source=application.id, image_type='selfie', url='selfie_url')
        mock_download.side_effect = [b'skrtp_data', b'ktp_data', b'selfie_data']

        result = self.service.get_bni_supporting_disbursement_documents(
            loan=loan,
            is_skip_download_files=False,
        )
        expected_result = {
            BNISupportingDisbursementDocumentConst.SKRTP: b'skrtp_data',
            BNISupportingDisbursementDocumentConst.KTP: b'ktp_data',
            BNISupportingDisbursementDocumentConst.SELFIE: b'selfie_data',
        }
        self.assertEqual(result, expected_result)

        mock_download.assert_any_call(remote_filepath='skrtp_url')
        mock_download.assert_any_call(remote_filepath='ktp_url')
        mock_download.assert_any_call(remote_filepath='selfie_url')

        # TEST SKIP DOWNLOAD FILES
        mock_download.reset_mock()
        result = self.service.get_bni_supporting_disbursement_documents(
            loan=loan,
            is_skip_download_files=True,
        )
        expected_result = {
            BNISupportingDisbursementDocumentConst.SKRTP: 'skrtp_url',
            BNISupportingDisbursementDocumentConst.KTP: 'ktp_url',
            BNISupportingDisbursementDocumentConst.SELFIE: 'selfie_url',
        }
        self.assertEqual(result, expected_result)
        mock_download.assert_not_called()

    def test_get_list_bni_pending_channeling_loan_status(self):
        current_ts = timezone.localtime(timezone.now())

        eligibility_status = ChannelingEligibilityStatusFactory(
            channeling_type=ChannelingConst.BNI, eligibility_status=ChannelingStatusConst.ELIGIBLE
        )

        # Create some ChannelingLoanStatus objects that should be returned
        valid_statuses = []
        for deduct_hour in range(1, 4):
            valid_status = ChannelingLoanStatusFactory(
                channeling_type=ChannelingConst.BNI,
                channeling_status=ChannelingStatusConst.PENDING,
                channeling_eligibility_status=eligibility_status,
            )
            valid_status.cdate = current_ts - timedelta(hours=deduct_hour)
            valid_status.save()
            valid_statuses.append(valid_status)

        # Create some ChannelingLoanStatus objects that should not be returned
        ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BSS,  # Different channeling type
            channeling_status=ChannelingStatusConst.PENDING,
            channeling_eligibility_status=eligibility_status,
        )
        ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BNI,
            channeling_status=ChannelingStatusConst.PREFUND,  # Different status
            channeling_eligibility_status=eligibility_status,
        )
        future_date_status = ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BNI,
            channeling_status=ChannelingStatusConst.PENDING,
            channeling_eligibility_status=eligibility_status,
        )
        future_date_status.cdate = current_ts + timedelta(hours=2)
        future_date_status.save()

        # TEST NON-EMPTY LIST
        result = self.service.get_list_bni_pending_channeling_loan_status()
        # Check that we got the correct number of results
        self.assertEqual(len(result), 3)
        # Check that all returned objects are the ones we expect
        for status in result:
            self.assertIn(status, valid_statuses)
        # Check that the results are ordered by -pk
        self.assertEqual(list(result), sorted(result, key=lambda x: -x.pk))

        # TEST EMPTY LIST
        # Delete all valid statuses
        ChannelingLoanStatus.objects.all().delete()
        result = self.service.get_list_bni_pending_channeling_loan_status()
        self.assertEqual(len(result), 0)

    def test_get_list_bni_recap_channeling_loan_status(self):
        current_ts = timezone.localtime(timezone.now())

        # Create some ChannelingLoanStatus objects that should be returned
        valid_statuses = []
        for deduct_hour in range(1, 4):
            valid_status = ChannelingLoanStatusFactory(
                channeling_type=ChannelingConst.BNI,
                channeling_status=ChannelingStatusConst.SUCCESS,
            )
            valid_status.cdate = current_ts - timedelta(hours=23)
            valid_status.save()
            valid_statuses.append(valid_status)

        # Create some ChannelingLoanStatus objects that should not be returned
        ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BSS,  # Different channeling type
            channeling_status=ChannelingStatusConst.SUCCESS,
        )
        ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BNI,
            channeling_status=ChannelingStatusConst.PREFUND,  # Different status
        )
        future_date_status = ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BNI,
            channeling_status=ChannelingStatusConst.SUCCESS,
        )
        future_date_status.cdate = current_ts + timedelta(hours=1)
        future_date_status.save()
        past_date_status = ChannelingLoanStatusFactory(
            channeling_type=ChannelingConst.BNI,
            channeling_status=ChannelingStatusConst.SUCCESS,
        )
        past_date_status.cdate = current_ts - timedelta(hours=25)
        past_date_status.save()

        # TEST NON-EMPTY LIST
        result = self.service.get_list_bni_recap_channeling_loan_status()
        # Check that we got the correct number of results
        self.assertEqual(len(list(result)), 3)
        # Check that all returned objects are the ones we expect
        for status in result:
            self.assertIn(status, valid_statuses)
        # Check that the results are ordered by -pk
        self.assertEqual(list(result), sorted(result, key=lambda x: -x.pk))

        # TEST EMPTY LIST
        # Delete all valid statuses
        ChannelingLoanStatus.objects.all().delete()
        result = self.service.get_list_bni_recap_channeling_loan_status()
        self.assertEqual(len(list(result)), 0)

    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'get_bni_supporting_disbursement_documents'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_bni_disbursement_data'
    )
    @patch('juloserver.channeling_loan.services.bni_services.sentry_client')
    @patch('juloserver.channeling_loan.services.bni_services.logger')
    def test_construct_list_bni_disbursement_data_and_supporting_documents(
        self, mock_logger, mock_sentry, mock_construct, mock_supporting
    ):
        loan1 = LoanFactory()
        loan2 = LoanFactory()
        loan3 = LoanFactory()

        channeling_loan_status1 = ChannelingLoanStatusFactory(loan=loan1)
        channeling_loan_status2 = ChannelingLoanStatusFactory(loan=loan2)
        channeling_loan_status3 = ChannelingLoanStatusFactory(loan=loan3)

        channeling_loan_statuses = [
            channeling_loan_status1,
            channeling_loan_status2,
            channeling_loan_status3,
        ]

        mock_construct.side_effect = [
            {'loan_id': loan1.id, 'data': 'test1'},
            {'loan_id': loan2.id, 'data': 'test2'},
            {'loan_id': loan3.id, 'data': 'test3'},
        ]

        mock_supporting.side_effect = [
            {'skrtp': b'skrtp1', 'ktp': b'ktp1', 'selfie': b'selfie1'},
            {'skrtp': b'skrtp2', 'ktp': b'ktp2', 'selfie': b'selfie2'},
            {'skrtp': b'skrtp3', 'ktp': b'ktp3', 'selfie': b'selfie3'},
        ]

        # TEST SUCCESS CASE
        result = self.service.construct_list_bni_disbursement_data_and_supporting_documents(
            channeling_loan_statuses=channeling_loan_statuses
        )
        (
            success_construct_channeling_loan_statuses,
            list_disbursement_data,
            list_supporting_documents,
        ) = result

        # Check that the result contains the expected data
        self.assertEqual(len(success_construct_channeling_loan_statuses), 3)
        self.assertEqual(len(list_disbursement_data), 3)
        self.assertEqual(len(list_supporting_documents), 3)
        self.assertEqual(success_construct_channeling_loan_statuses[0], channeling_loan_status1)
        self.assertEqual(success_construct_channeling_loan_statuses[1], channeling_loan_status2)
        self.assertEqual(success_construct_channeling_loan_statuses[2], channeling_loan_status3)
        self.assertEqual(list_disbursement_data[0]['loan_id'], loan1.id)
        self.assertEqual(list_disbursement_data[1]['loan_id'], loan2.id)
        self.assertEqual(list_disbursement_data[2]['loan_id'], loan3.id)
        self.assertEqual(list_supporting_documents[0]['skrtp'], b'skrtp1')
        self.assertEqual(list_supporting_documents[1]['ktp'], b'ktp2')
        self.assertEqual(list_supporting_documents[2]['selfie'], b'selfie3')

        # Check that construct_bni_disbursement_data was called for each loan
        self.assertEqual(mock_construct.call_count, 3)
        # Check that get_bni_supporting_disbursement_documents was called for each loan
        self.assertEqual(mock_supporting.call_count, 3)

        mock_sentry.captureException.assert_not_called()
        mock_logger.exception.assert_not_called()

        # TEST SUCCESS CASE BUT SKIP DOWNLOAD SUPPORTING DOCUMENTS
        mock_construct.reset_mock()
        mock_construct.side_effect = [
            {'loan_id': loan1.id, 'data': 'test1'},
            {'loan_id': loan2.id, 'data': 'test2'},
            {'loan_id': loan3.id, 'data': 'test3'},
        ]
        mock_supporting.reset_mock()
        mock_supporting.side_effect = [
            {'skrtp': 'skrtp_url1', 'ktp': 'ktp_url1', 'selfie': 'selfie_url1'},
            {'skrtp': 'skrtp_url2', 'ktp': 'ktp_url2', 'selfie': 'selfie_url2'},
            {'skrtp': 'skrtp_url3', 'ktp': 'ktp_url3', 'selfie': 'selfie_url3'},
        ]
        self.service.construct_list_bni_disbursement_data_and_supporting_documents(
            channeling_loan_statuses=channeling_loan_statuses,
            is_skip_download_supporting_docs=True,
        )
        self.assertEqual(mock_construct.call_count, 3)
        self.assertEqual(mock_supporting.call_count, 3)
        expected_calls = [
            unittest.mock.call(loan=loan1, is_skip_download_files=True),
            unittest.mock.call(loan=loan2, is_skip_download_files=True),
            unittest.mock.call(loan=loan3, is_skip_download_files=True),
        ]
        mock_supporting.assert_has_calls(expected_calls, any_order=False)

        # TEST EXCEPTION CASE
        # Mock construct_bni_disbursement_data to raise an exception for the second loan
        mock_construct.side_effect = [
            {'loan_id': loan1.id, 'data': 'test1'},
            Exception("Test exception"),
            {'loan_id': loan3.id, 'data': 'test3'},
        ]
        mock_construct.reset_mock()
        # Mock get_bni_supporting_disbursement_documents to raise an exception for the third loan
        mock_supporting.side_effect = [
            {'skrtp': b'skrtp1', 'ktp': b'ktp1', 'selfie': b'selfie1'},
            Exception("Test exception"),  # mock_construct is already raised -> continue next iter
            Exception("Test exception"),
        ]
        mock_supporting.reset_mock()

        result = self.service.construct_list_bni_disbursement_data_and_supporting_documents(
            channeling_loan_statuses=channeling_loan_statuses
        )
        (
            success_construct_channeling_loan_statuses,
            list_disbursement_data,
            list_supporting_documents,
        ) = result

        # Check that the result contains data only for the successful constructions
        self.assertEqual(len(success_construct_channeling_loan_statuses), 1)
        self.assertEqual(len(list_disbursement_data), 1)
        self.assertEqual(len(list_supporting_documents), 1)
        self.assertEqual(success_construct_channeling_loan_statuses[0], channeling_loan_status1)
        self.assertEqual(list_disbursement_data[0]['loan_id'], loan1.id)

        # Check that construct_bni_disbursement_data was called for each loan
        self.assertEqual(mock_construct.call_count, 3)
        # Check that get_bni_supporting_disbursement_documents was called for 2 loans
        # because don't call in second iter due to exception raised in mock_construct
        self.assertEqual(mock_supporting.call_count, 2)

        self.assertEqual(mock_sentry.captureException.call_count, 2)
        self.assertEqual(mock_logger.exception.call_count, 2)

        logger_call_args = mock_logger.exception.call_args_list
        # Ensure there were exactly two calls because we have 2 exceptions
        self.assertEqual(len(logger_call_args), 2)

        # Check the first call
        first_call_args = logger_call_args[0][0][0]
        self.assertEqual(first_call_args['loan_id'], loan2.id)
        self.assertEqual(
            first_call_args['message'], 'Failed to construct channeling disbursement data for loan'
        )

        # Check the second call
        second_call_args = logger_call_args[1][0][0]
        self.assertEqual(second_call_args['loan_id'], loan3.id)
        self.assertEqual(
            first_call_args['message'], 'Failed to construct channeling disbursement data for loan'
        )

        # TEST EMPTY LIST
        mock_construct.reset_mock()
        mock_sentry.reset_mock()
        mock_logger.reset_mock()
        result = self.service.construct_list_bni_disbursement_data_and_supporting_documents(
            channeling_loan_statuses=[]
        )
        (
            success_construct_channeling_loan_statuses,
            list_disbursement_data,
            list_supporting_documents,
        ) = result
        self.assertEqual(success_construct_channeling_loan_statuses, [])
        self.assertEqual(list_disbursement_data, [])
        mock_construct.assert_not_called()
        mock_sentry.captureException.assert_not_called()
        mock_logger.exception.assert_not_called()

    def test_get_bni_disbursement_xlsx_headers(self):
        headers = self.service.get_bni_disbursement_xlsx_headers()

        # Check that all keys from DISBURSEMENT_DATA_MAPPING are in the headers
        for key in BNIDisbursementConst.DISBURSEMENT_DATA_MAPPING.keys():
            self.assertIn(key, headers)

        # Check duplicated columns
        expected_length = (
            len(BNIDisbursementConst.DISBURSEMENT_DATA_MAPPING) + 3
        )  # +3 for the inserted headers
        self.assertEqual(len(headers), expected_length)
        self.assertEqual(headers.count(BNIDisbursementConst.HEADER_KOTA), 2)
        self.assertEqual(headers.count(BNIDisbursementConst.HEADER_KOTA_POS), 2)
        self.assertEqual(headers.count(BNIDisbursementConst.HEADER_KOTA_AREA), 2)

        # Check the order of the duplicated column headers
        anchor_index = headers.index(BNIDisbursementConst.HEADER_ALAMAT_KANTOR_4)
        self.assertEqual(headers[anchor_index + 1], BNIDisbursementConst.HEADER_KOTA)
        self.assertEqual(headers[anchor_index + 2], BNIDisbursementConst.HEADER_KOTA_POS)
        self.assertEqual(headers[anchor_index + 3], BNIDisbursementConst.HEADER_KOTA_AREA)

    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'get_bni_disbursement_xlsx_headers'
    )
    def test_construct_bni_disbursement_xlsx_bytes(self, mock_get_headers):
        mock_get_headers.return_value = ["NO", 'abc']

        result = self.service.construct_bni_disbursement_xlsx_bytes(list_disbursement_data=[])
        self.assertIsNotNone(result)
        mock_get_headers.assert_called_once()

        mock_get_headers.reset_mock()
        result = self.service.construct_bni_disbursement_xlsx_bytes(
            list_disbursement_data=[{'abc': 'dummy'}]
        )
        self.assertIsNotNone(result)
        mock_get_headers.assert_called_once()

    @patch('juloserver.channeling_loan.services.bni_services.SFTPProcess')
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_bni_disbursement_xlsx_bytes'
    )
    def test_construct_xlsx_file_and_upload_to_sftp_server(self, mock_construct, mock_sftp_process):
        self.service.current_ts = timezone.localtime(timezone.now())
        mock_construct.return_value = b'fake xlsx content'

        mock_sftp_process_instance = MagicMock()
        mock_sftp_process.return_value = mock_sftp_process_instance

        result = self.service.construct_xlsx_file_and_upload_to_sftp_server(
            list_disbursement_data=[{'abc': 'dummy'}], filename_counter_suffix='001', is_recap=False
        )
        expected_filename = BNIDisbursementConst.FILENAME_FORMAT.format(
            self.service.current_ts.strftime("%d_%m_%Y_%H_%M_%S"), '001'
        )
        self.assertEqual(result, expected_filename)
        mock_construct.assert_called_once_with(list_disbursement_data=[{'abc': 'dummy'}])

        mock_sftp_process_instance.upload.assert_called_once_with(
            content=b'fake xlsx content',
            remote_path='{}/{}'.format(BNIDisbursementConst.FOLDER_NAME, expected_filename),
        )

        # TEST RECAP FILENAME
        result = self.service.construct_xlsx_file_and_upload_to_sftp_server(
            list_disbursement_data=[{'abc': 'dummy'}], filename_counter_suffix='001', is_recap=True
        )
        expected_filename = BNIDisbursementConst.FILENAME_FORMAT.format(
            self.service.current_ts.strftime("%d_%m_%Y"), '001'
        )
        self.assertEqual(result, expected_filename)

    def test_construct_bni_supporting_documents_zip_bytes(self):
        result = self.service.construct_bni_supporting_documents_zip_bytes(
            list_supporting_documents=[]
        )
        self.assertIsNotNone(result)

        result = self.service.construct_bni_supporting_documents_zip_bytes(
            list_supporting_documents=[{'skrtp': b'dummy', 'ktp': b'dummy', 'selfie': b'dummy'}]
        )
        self.assertIsNotNone(result)

    @patch('juloserver.channeling_loan.services.bni_services.SFTPProcess')
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_bni_supporting_documents_zip_bytes'
    )
    def test_construct_zip_file_and_upload_to_sftp_server(self, mock_construct, mock_sftp_process):
        mock_construct.return_value = b'fake zip content'

        mock_sftp_process_instance = MagicMock()
        mock_sftp_process.return_value = mock_sftp_process_instance

        result = self.service.construct_zip_file_and_upload_to_sftp_server(
            list_supporting_documents=[{'skrtp': b'dummy', 'ktp': b'dummy', 'selfie': b'dummy'}],
            filename_counter_suffix='001',
            is_recap=False,
        )
        expected_filename = BNISupportingDisbursementDocumentConst.FILENAME_FORMAT.format(
            self.service.current_ts.strftime("%d_%m_%Y_%H_%M_%S"), '001'
        )
        self.assertEqual(result, expected_filename)
        mock_construct.assert_called_once_with(
            list_supporting_documents=[{'skrtp': b'dummy', 'ktp': b'dummy', 'selfie': b'dummy'}]
        )
        mock_sftp_process_instance.upload.assert_called_once_with(
            content=b'fake zip content',
            remote_path='{}/{}'.format(
                BNISupportingDisbursementDocumentConst.FOLDER_NAME, expected_filename
            ),
        )

        # TEST RECAP FILENAME
        result = self.service.construct_zip_file_and_upload_to_sftp_server(
            list_supporting_documents=[{'skrtp': b'dummy', 'ktp': b'dummy', 'selfie': b'dummy'}],
            filename_counter_suffix='001',
            is_recap=True,
        )
        expected_filename = BNISupportingDisbursementDocumentConst.FILENAME_FORMAT.format(
            self.service.current_ts.strftime("%d_%m_%Y"), '001'
        )
        self.assertEqual(result, expected_filename)

    @patch('juloserver.channeling_loan.services.bni_services.get_channeling_loan_configuration')
    def test_is_eligible_to_send_loan_to_bni(self, mock_get_config):
        cutoff_config = {
            'cutoff': {
                'is_active': True,
                'CHANNEL_AFTER_CUTOFF': False,
                'INACTIVE_DAY': ['Saturday', 'Sunday'],
                'INACTIVE_DATE': ['2024/01/31'],
                'OPENING_TIME': {'hour': 8, 'minute': 0, 'second': 0},
                'CUTOFF_TIME': {'hour': 17, 'minute': 0, 'second': 0},
            }
        }

        # returns False when no configuration exists
        mock_get_config.return_value = None
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertFalse(result)

        # returns True when cutoff is not active
        config = copy.deepcopy(cutoff_config)
        config['cutoff']['is_active'] = False
        mock_get_config.return_value = config
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertTrue(result)

        # returns False when current day is in inactive days
        # 2024-10-26 is Saturday
        self.service.current_ts = datetime(2024, 10, 26, 10, 0, 0)
        mock_get_config.return_value = cutoff_config
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertFalse(result)

        # returns False when current date is in inactive dates
        mock_get_config.return_value = cutoff_config
        # 2024-01-31 is current inactive date in cutoff config
        self.service.current_ts = datetime(2024, 1, 31, 10, 0, 0)
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertFalse(result)

        # current ts is not in inactive days or dates, and within range of opening and cutoff time
        self.service.current_ts = datetime(2024, 10, 30, 10, 0, 0)

        # returns True when CHANNEL_AFTER_CUTOFF is True
        config = copy.deepcopy(cutoff_config)
        config['cutoff']['CHANNEL_AFTER_CUTOFF'] = True
        mock_get_config.return_value = config
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertTrue(result)

        # returns True when current time is within opening and cutoff time
        mock_get_config.return_value = cutoff_config
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertTrue(result)

        # returns False when current time is outside opening and cutoff time
        # Set current_ts to 7:00 AM (before opening time)
        self.service.current_ts = datetime(2024, 10, 30, 7, 0, 0)
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertFalse(result)
        # Set current_ts to 18:00 PM (after cutoff time)
        self.service.current_ts = datetime(2024, 10, 30, 18, 0, 0)
        result = self.service.is_eligible_to_send_loan_to_bni()
        self.assertFalse(result)

    def test_approve_channeling_loan_statuses(self):
        loan1 = LoanFactory()
        loan2 = LoanFactory()
        channeling_loan_status1 = ChannelingLoanStatusFactory(loan=loan1)
        channeling_loan_status2 = ChannelingLoanStatusFactory(loan=loan2)

        from juloserver.channeling_loan import tasks as channeling_loan_tasks

        with mock.patch.object(
            channeling_loan_tasks, "approve_loan_for_channeling_task", autospec=True
        ) as mock_approve_task:
            self.service.approve_channeling_loan_statuses(
                channeling_loan_statuses=[channeling_loan_status1, channeling_loan_status2]
            )

        self.assertEqual(mock_approve_task.delay.call_count, 2)
        mock_approve_task.delay.assert_any_call(
            loan_id=loan1.id,
            channeling_type=ChannelingConst.BNI,
            approval_status=ChannelingApprovalStatusConst.YES,
        )
        mock_approve_task.delay.assert_any_call(
            loan_id=loan2.id,
            channeling_type=ChannelingConst.BNI,
            approval_status=ChannelingApprovalStatusConst.YES,
        )

    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'is_eligible_to_send_loan_to_bni'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'get_list_bni_pending_channeling_loan_status'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_list_bni_disbursement_data_and_supporting_documents'
    )
    @patch('juloserver.channeling_loan.services.bni_services.get_next_filename_counter_suffix')
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_xlsx_file_and_upload_to_sftp_server'
    )
    @patch('juloserver.channeling_loan.services.bni_services.bulk_update_channeling_loan_status')
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'approve_channeling_loan_statuses'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.create_channeling_loan_send_file_tracking'
    )
    @patch('juloserver.channeling_loan.services.bni_services.logger')
    def test_send_loan_for_channeling_to_bni(
        self,
        mock_logger,
        mock_create_tracking,
        mock_approve_status,
        mock_bulk_update,
        mock_construct_xlsx_and_upload,
        mock_get_counter_suffix,
        mock_construct_list,
        mock_get_list,
        mock_check_eligible,
    ):
        # TEST FS TURN OFF
        mock_check_eligible.return_value = False
        self.assertIsNone(self.service.send_loan_for_channeling_to_bni())
        mock_logger.info.assert_called_once()
        mock_get_list.assert_not_called()

        # Mock fs turned on
        mock_check_eligible.return_value = True
        mock_check_eligible.reset_mock()
        mock_logger.reset_mock()

        # Mock the get_list_bni_pending_channeling_loan_status method
        loan1 = LoanFactory()
        loan2 = LoanFactory()
        channeling_loan_status1 = ChannelingLoanStatusFactory(loan=loan1)
        channeling_loan_status2 = ChannelingLoanStatusFactory(loan=loan2)
        mock_get_list.return_value = [channeling_loan_status1, channeling_loan_status2]

        # TEST NO LOAN TO SEND
        mock_construct_list.return_value = (
            [],
            [],
            [],
        )
        self.service.send_loan_for_channeling_to_bni()
        mock_get_counter_suffix.assert_not_called()
        mock_construct_xlsx_and_upload.assert_not_called()

        # TEST SUCCESS CASE
        # Mock the construct_list_bni_disbursement_data_and_supporting_documents method
        mock_construct_list.return_value = (
            [channeling_loan_status1, channeling_loan_status2],
            [{'data': 'for loan 1'}, {'data': 'for loan 2'}],
            [
                {'skrtp': b'for loan 1', 'ktp': b'for loan 1', 'selfie': b'for loan 1'},
                {'skrtp': b'for loan 2', 'ktp': b'for loan 2', 'selfie': b'for loan 2'},
            ],
        )
        mock_check_eligible.reset_mock()
        mock_get_list.reset_mock()
        mock_construct_list.reset_mock()
        mock_logger.reset_mock()

        # Mock get_next_filename_counter_suffix function
        mock_get_counter_suffix.return_value = '001'

        # Mock the construct_xlsx_file_and_upload_to_sftp_server method
        mock_construct_xlsx_and_upload.return_value = 'Reimbursement.xlsx'

        # Call the function
        self.service.send_loan_for_channeling_to_bni()

        # Assertions
        mock_check_eligible.assert_called_once()
        mock_get_list.assert_called_once()
        mock_construct_list.assert_called_once_with(
            channeling_loan_statuses=[channeling_loan_status1, channeling_loan_status2],
            is_skip_download_supporting_docs=True,
        )
        mock_get_counter_suffix.assert_called_once()
        mock_construct_xlsx_and_upload.assert_called_once_with(
            list_disbursement_data=[{'data': 'for loan 1'}, {'data': 'for loan 2'}],
            filename_counter_suffix='001',
            is_recap=False,
        )
        mock_bulk_update.assert_called_once_with(
            channeling_loan_status_id=[channeling_loan_status1.id, channeling_loan_status2.id],
            new_status=ChannelingStatusConst.PROCESS,
        )
        mock_approve_status.assert_called_once()
        mock_create_tracking.assert_called_once_with(
            channeling_type=ChannelingConst.BNI,
            action_type=ChannelingActionTypeConst.DISBURSEMENT,
        )
        self.assertEqual(mock_logger.info.call_count, 1)
        log_call_args = mock_logger.info.call_args_list[0][0][0]
        self.assertEqual(log_call_args['number_of_loans'], 2)
        self.assertEqual(log_call_args['xlsx_filename'], 'Reimbursement.xlsx')
        self.assertEqual(log_call_args['message'], 'Send loan for channeling to BNI successfully')

    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'get_list_bni_recap_channeling_loan_status'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_list_bni_disbursement_data_and_supporting_documents'
    )
    @patch('juloserver.channeling_loan.services.bni_services.get_next_filename_counter_suffix')
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_xlsx_file_and_upload_to_sftp_server'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.BNIDisbursementServices.'
        'construct_zip_file_and_upload_to_sftp_server'
    )
    @patch(
        'juloserver.channeling_loan.services.bni_services.create_channeling_loan_send_file_tracking'
    )
    @patch('juloserver.channeling_loan.services.bni_services.logger')
    def test_send_recap_loan_for_channeling_to_bni(
        self,
        mock_logger,
        mock_create_tracking,
        mock_construct_zip_and_upload,
        mock_construct_xlsx_and_upload,
        mock_get_counter_suffix,
        mock_construct_list,
        mock_get_list_recap,
    ):
        # Mock the get_list_bni_pending_channeling_loan_status method
        loan1 = LoanFactory()
        loan2 = LoanFactory()
        channeling_loan_status1 = ChannelingLoanStatusFactory(loan=loan1)
        channeling_loan_status2 = ChannelingLoanStatusFactory(loan=loan2)
        mock_get_list_recap.return_value = [channeling_loan_status1, channeling_loan_status2]

        # TEST NO LOAN TO SEND
        mock_construct_list.return_value = (
            [],
            [],
            [],
        )
        self.service.send_loan_for_channeling_to_bni()
        mock_get_counter_suffix.assert_not_called()
        mock_construct_xlsx_and_upload.assert_not_called()

        # TEST SUCCESS CASE
        # Mock the construct_list_bni_disbursement_data_and_supporting_documents method
        mock_construct_list.return_value = (
            [channeling_loan_status1, channeling_loan_status2],
            [{'data': 'for loan 1'}, {'data': 'for loan 2'}],
            [
                {'skrtp': b'for loan 1', 'ktp': b'for loan 1', 'selfie': b'for loan 1'},
                {'skrtp': b'for loan 2', 'ktp': b'for loan 2', 'selfie': b'for loan 2'},
            ],
        )
        mock_get_list_recap.reset_mock()
        mock_construct_list.reset_mock()
        mock_logger.reset_mock()

        # Mock get_next_filename_counter_suffix function
        mock_get_counter_suffix.return_value = '001'

        # Mock the construct_xlsx_file_and_upload_to_sftp_server method
        mock_construct_xlsx_and_upload.return_value = 'Reimbursement.xlsx'

        # Mock the construct_zip_file_and_upload_to_sftp_server method
        mock_construct_zip_and_upload.return_value = 'SupportingDoc.zip'

        # Call the function
        self.service.send_recap_loan_for_channeling_to_bni()

        # Assertions
        mock_get_list_recap.assert_called_once()
        mock_construct_list.assert_called_once_with(
            channeling_loan_statuses=[channeling_loan_status1, channeling_loan_status2]
        )
        mock_get_counter_suffix.assert_called_once()
        mock_construct_xlsx_and_upload.assert_called_once_with(
            list_disbursement_data=[{'data': 'for loan 1'}, {'data': 'for loan 2'}],
            filename_counter_suffix='001',
            is_recap=True,
        )
        mock_construct_zip_and_upload.assert_called_once_with(
            list_supporting_documents=[
                {'skrtp': b'for loan 1', 'ktp': b'for loan 1', 'selfie': b'for loan 1'},
                {'skrtp': b'for loan 2', 'ktp': b'for loan 2', 'selfie': b'for loan 2'},
            ],
            filename_counter_suffix='001',
            is_recap=True,
        )
        mock_create_tracking.assert_called_once_with(
            channeling_type=ChannelingConst.BNI,
            action_type=ChannelingActionTypeConst.RECAP,
        )
        self.assertEqual(mock_logger.info.call_count, 1)
        log_call_args = mock_logger.info.call_args_list[0][0][0]
        self.assertEqual(log_call_args['number_of_loans'], 2)
        self.assertEqual(log_call_args['xlsx_filename'], 'Reimbursement.xlsx')
        self.assertEqual(log_call_args['zip_filename'], 'SupportingDoc.zip')
        self.assertEqual(
            log_call_args['message'], 'Send recap loan for channeling to BNI successfully'
        )


class TestBNIGeneralServices(TestCase):
    def setUp(self):
        self.current_ts = timezone.localtime(timezone.now())

    def test_construct_bni_xlsx_bytes(self):
        def _read_excel_content(excel_bytes: bytes) -> List[List[Any]]:
            """Helper method to read excel content for verification"""
            workbook = openpyxl.load_workbook(BytesIO(excel_bytes))
            sheet = workbook.active

            content = []
            for row in sheet.rows:
                content.append([cell.value for cell in row])
            return content

        basic_headers = ['NO', 'name', 'age']
        basic_data = [{'name': 'Jenny', 'age': 30}, {'name': 'Anna', 'age': 25}]
        sheet_name = 'Test Sheet'

        """Test basic excel generation with simple headers and data"""
        result = construct_bni_xlsx_bytes(
            headers=basic_headers,
            sheet_name=sheet_name,
            list_data=basic_data,
            header_no='NO',
            header_map=None,
        )
        self.assertIsInstance(result, bytes)
        content = _read_excel_content(result)
        self.assertEqual(content[0], basic_headers)
        self.assertEqual(content[1], [1, 'Jenny', 30])
        self.assertEqual(content[2], [2, 'Anna', 25])

        """Test excel generation with header mapping"""
        header_map = {'name': 'Full Name', 'age': 'Age (years)'}
        result = construct_bni_xlsx_bytes(
            headers=basic_headers,
            sheet_name=sheet_name,
            list_data=basic_data,
            header_no='NO',
            header_map=header_map,
        )
        content = _read_excel_content(result)
        self.assertEqual(content[0], ['NO', 'Full Name', 'Age (years)'])
        self.assertEqual(content[1], [1, 'Jenny', 30])
        self.assertEqual(content[2], [2, 'Anna', 25])

        """Test excel generation with missing data fields"""
        data_with_missing = [{'name': 'Jenny'}, {'age': 25}]  # missing age  # missing name
        result = construct_bni_xlsx_bytes(
            headers=basic_headers,
            sheet_name=sheet_name,
            list_data=data_with_missing,
            header_no='NO',
            header_map=None,
        )
        content = _read_excel_content(result)
        # Verify data with missing fields (should be None)
        self.assertEqual(content[1], [1, 'Jenny', None])
        self.assertEqual(content[2], [2, None, 25])

        """Test excel generation with empty data list"""
        result = construct_bni_xlsx_bytes(
            headers=basic_headers,
            sheet_name=sheet_name,
            list_data=[],
            header_no='NO',
            header_map=None,
        )
        content = _read_excel_content(result)
        # Should only contain headers
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0], basic_headers)

        """Test if sheet name is set correctly"""
        result = construct_bni_xlsx_bytes(
            headers=basic_headers,
            sheet_name='Custom Sheet',
            list_data=basic_data,
            header_no='NO',
            header_map=None,
        )
        workbook = openpyxl.load_workbook(BytesIO(result))
        self.assertEqual(workbook.active.title, 'Custom Sheet')

    @patch('juloserver.channeling_loan.services.bni_services.SFTPProcess')
    def test_send_file_for_channeling_to_bni(self, mock_sftp_process):
        mock_sftp_process_instance = MagicMock()
        mock_sftp_process.return_value = mock_sftp_process_instance
        filename_counter_suffix = '001'

        result = send_file_for_channeling_to_bni(
            data_bytes=b'fake xlsx content',
            folder_name='test',
            filename_format=BNIDisbursementConst.FILENAME_FORMAT,
            filename_datetime_format=BNIDisbursementConst.FILENAME_DATETIME_FORMAT,
            filename_counter_suffix=filename_counter_suffix,
            current_ts=self.current_ts,
        )

        mock_sftp_process_instance.upload.assert_called_once_with(
            content=b'fake xlsx content', remote_path='test/{}'.format(result)
        )


class TestBNIInterest(TestCase):
    @classmethod
    def setUpTestData(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.BNI_INTEREST_CONFIG,
            is_active=False,
            parameters={"interest": BNI_DEFAULT_INTEREST},
        )
        self.disbursement = DisbursementFactory()
        self.lender = LenderCurrentFactory(xfers_token="xfers_tokenforlender")
        self.account = AccountFactory()
        self.current_ts = timezone.localtime(timezone.now())
        self.application = ApplicationFactory(
            account=self.account,
        )
        self.loan = LoanFactory(
            application=self.application,
            account=self.account,
            lender=self.lender,
            disbursement_id=self.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            loan_amount=1_000_000,
            loan_duration=4,
        )

    def test_channeling_payment_interest(self):
        # test with FS turned off
        self.loan.fund_transfer_ts = self.current_ts.replace(year=2023, month=3, day=15)
        self.loan.save()
        payments = self.loan.payment_set.order_by('payment_number')
        month = 4
        for payment in payments:
            payment.due_date = timezone.localtime(
                self.current_ts.replace(year=2023, month=month, day=10)
            ).date()
            payment.save()
            month += 1

        bni_interest_service = BNIInterest(self.loan, ChannelingConst.BNI, 0, 360, list(payments))
        result = bni_interest_service.channeling_payment_interest()
        self.assertIsNotNone(result)
        # tested with 4 month, the yearly interest should be 6.72%, with 4 month 2.24%

        channeling_loan_payments = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.BNI
        )
        total_interest = 0
        for channeling_loan_payment in channeling_loan_payments:
            total_interest += channeling_loan_payment.interest_amount

        interest_calculation = py2round(self.loan.loan_amount * 0.0056) * 4
        self.assertEqual(total_interest, interest_calculation)

    def test_channeling_payment_interest_first_payment(self):
        # test with FS turned off
        self.loan.fund_transfer_ts = self.current_ts.replace(year=2023, month=3, day=1)
        self.loan.save()
        payments = self.loan.payment_set.order_by('payment_number')
        month = 4
        for payment in payments:
            payment.due_date = timezone.localtime(
                self.current_ts.replace(year=2023, month=month, day=10)
            ).date()
            payment.save()
            month += 1

        bni_interest_service = BNIInterest(self.loan, ChannelingConst.BNI, 0, 360, list(payments))
        result = bni_interest_service.channeling_payment_interest()
        self.assertIsNotNone(result)
        # tested with 4 month, the yearly interest should be 6.72%, with 4 month 2.24%
        monthly_interest = 0.0056

        channeling_loan_payments = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.BNI
        )
        total_interest = 0
        for channeling_loan_payment in channeling_loan_payments:
            total_interest += channeling_loan_payment.interest_amount

        # normal interest calculation when first payment <= 30 days
        interest_calculation = py2round(self.loan.loan_amount * monthly_interest) * 4
        self.assertNotEqual(total_interest, interest_calculation)

        first_payment = payments.first()
        date_diff = (first_payment.due_date - self.loan.fund_transfer_ts.date()).days

        correct_interest_calculation = py2round(
            self.loan.loan_amount * monthly_interest / 30 * (30 * 4 + (date_diff - 30))
        )
        monthly_interest_calculation = py2round(correct_interest_calculation / 4)
        self.assertEqual(total_interest, monthly_interest_calculation * 4)

    def test_channeling_payment_interest_fs_on(self):
        # test with FS turned on
        self.loan.fund_transfer_ts = self.current_ts.replace(year=2023, month=3, day=15)
        self.loan.save()
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {
            "interest": {
                '1': 12,
                '2': 12,
                '3': 12,
                '4': 12,
                '5': 12,
                '6': 12,
                '7': 12,
                '8': 12,
                '9': 12,
                '10': 12,
                '11': 12,
                '12': 12,
            }
        }
        self.feature_setting.save()
        payments = self.loan.payment_set.order_by('payment_number')
        month = 4
        for payment in payments:
            payment.due_date = timezone.localtime(
                self.current_ts.replace(year=2023, month=month, day=10)
            ).date()
            payment.save()
            month += 1

        bni_interest_service = BNIInterest(self.loan, ChannelingConst.BNI, 0, 360, list(payments))
        result = bni_interest_service.channeling_payment_interest()
        self.assertIsNotNone(result)
        # tested with 4 month, the yearly interest should be 12%, with 4 month 4%

        channeling_loan_payments = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.BNI
        )
        total_interest = 0
        for channeling_loan_payment in channeling_loan_payments:
            total_interest += channeling_loan_payment.interest_amount

        interest_calculation = py2round(self.loan.loan_amount * 0.01) * 4
        self.assertEqual(total_interest, interest_calculation)

    def test_channeling_payment_interest_risk_premium(self):
        # test with FS turned on
        self.loan.fund_transfer_ts = self.current_ts.replace(year=2023, month=3, day=15)
        self.loan.save()
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {
            "interest": {
                '1': 12,
                '2': 12,
                '3': 12,
                '4': 12,
                '5': 12,
                '6': 12,
                '7': 12,
                '8': 12,
                '9': 12,
                '10': 12,
                '11': 12,
                '12': 12,
            }
        }
        self.feature_setting.save()
        payments = self.loan.payment_set.order_by('payment_number')
        month = 4
        for payment in payments:
            payment.due_date = timezone.localtime(
                self.current_ts.replace(year=2023, month=month, day=10)
            ).date()
            payment.save()
            month += 1

        bni_interest_service = BNIInterest(
            self.loan, ChannelingConst.BNI, 0.12, 360, list(payments)
        )
        result = bni_interest_service.channeling_payment_interest()
        self.assertIsNotNone(result)
        # tested with 4 month, the yearly interest should be 12%, with 4 month 4%

        channeling_loan_payments = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.BNI
        )
        total_interest = 0
        for channeling_loan_payment in channeling_loan_payments:
            total_interest += channeling_loan_payment.interest_amount

        interest_calculation = py2round(self.loan.loan_amount * 0.02) * 4
        self.assertEqual(total_interest, interest_calculation)


class TestBNIRepaymentServices(TestCase):
    def setUp(self):
        self.service = BNIRepaymentServices()

    def test_get_bni_repayment_data(self):
        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.txt", csv_bytes, content_type='text/plain')
        request = RequestFactory().request()
        request.FILES['repayment_file_field'] = file

        with self.assertRaises(Exception) as context:
            self.service.get_bni_repayment_data(request)
            self.assertEqual(context, "Please upload correct file excel")

        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type='text/csv')
        request = RequestFactory().request()
        request.FILES['repayment_file_field'] = file

        results = self.service.get_bni_repayment_data(request)
        self.assertIsNotNone(results)

        for result in results:
            self.assertTrue('test' in result)

    def test_construct_bni_repayment_xlsx_bytes(self):
        list_data = [
            {'test': 1},
            {'test': 2},
        ]
        result = self.service.construct_bni_repayment_xlsx_bytes(list_data)
        self.assertIsNotNone(result)

    @patch('juloserver.channeling_loan.services.bni_services.SFTPProcess')
    @patch(
        'juloserver.channeling_loan.services.bni_services.create_channeling_loan_send_file_tracking'
    )
    def test_send_repayment_for_channeling_to_bni(self, mock_file_tracking, mock_sftp_process):
        mock_sftp_process_instance = MagicMock()
        mock_sftp_process.return_value = mock_sftp_process_instance

        csv_bytes = b'test\n1\n2\n'
        file = SimpleUploadedFile("test.csv", csv_bytes, content_type='text/csv')
        request = RequestFactory().request()
        request.FILES['repayment_file_field'] = file

        self.service.send_repayment_for_channeling_to_bni(request)
        mock_file_tracking.assert_called_once()
