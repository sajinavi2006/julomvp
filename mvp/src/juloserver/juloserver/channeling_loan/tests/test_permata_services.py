import copy
import csv
import io
from unittest.mock import patch

from django.conf import settings
from django.test.testcases import TestCase
from juloserver.channeling_loan.services.permata_services import (
    padding_words,
    get_latest_permata_approval_filename,
    download_latest_permata_disbursement_approval_files_from_sftp_server,
    parse_permata_disbursement_accepted_loan_xids,
    construct_permata_disbursement_approval_csv,
    construct_permata_early_payoff_request_file_content,
    construct_permata_disbursement_approval_file,
    construct_permata_single_approval_file,
)


class TestPermataServices(TestCase):
    @classmethod
    def setUpTestData(self):
        pass

    def test_padding_words(self):
        words = "123456"
        result = padding_words(words, 5)
        self.assertEquals(result, "12345")

        result = padding_words(words, 10)
        self.assertEquals(result, "123456    ")

    def test_test_construct_permata_early_payoff_request_file_content(self):
        valid_dict_rows = [
            {
                'loan_id': '8199000441',
                'nama_end_user': 'NguyenVanE',
                'tgl_bayar_end_user': 'Apr 3, 2024',
                'nilai_pokok': '166666',
                'bunga': '42334',
                'nominal_denda_dibayar': '0',
                'penalty': '0',
                'diskon_denda': '0',
                'tgl_terima_rekanan': 'Apr 3, 2024, 12:15 AM',
                'diskon_bunga': '0',
            },
            {
                'loan_id': '8199000442',
                'nama_end_user': 'Cristiano Ronaldo',
                'tgl_bayar_end_user': 'Oct 15, 2023',
                'nilai_pokok': '266666',
                'bunga': '42534',
                'nominal_denda_dibayar': '12',
                'penalty': '11',
                'diskon_denda': '15',
                'tgl_terima_rekanan': 'May 31, 2024, 08:35 PM',
                'diskon_bunga': '100',
            },
        ]

        # TEST CASE 1: happy case
        success, result = construct_permata_early_payoff_request_file_content(valid_dict_rows)
        self.assertTrue(success)
        expected_lines = [
            '8199000441       NguyenVanE               03/04/2024166666      42334       0           0           0           03/04/20240           ',
            '8199000442       Cristiano Ronaldo        15/10/2023266666      42534       12          11          15          31/05/2024100         ',
        ]
        expected_result = '\n'.join(expected_lines)
        self.assertEqual(result, expected_result)

        # TEST CASE 2: invalid date
        invalid_dict_rows = copy.deepcopy(valid_dict_rows)
        invalid_dict_rows[0]['tgl_bayar_end_user'] = 'Invalid Date'
        success, result = construct_permata_early_payoff_request_file_content(invalid_dict_rows)
        self.assertFalse(success)
        self.assertIn("Row 1: TGL_BAYAR_ENDUSER is not a valid date", result)

        # TEST CASE 3: missing a field
        invalid_dict_rows = copy.deepcopy(valid_dict_rows)
        del invalid_dict_rows[0]['loan_id']
        success, result = construct_permata_early_payoff_request_file_content(invalid_dict_rows)
        self.assertFalse(success)
        self.assertIn("Row 1: LOAN_ID is missing", result)

        # TEST CASE 4: multiple errors
        invalid_dict_rows = copy.deepcopy(valid_dict_rows)
        invalid_dict_rows[0]['tgl_bayar_end_user'] = 'Invalid Date'
        del invalid_dict_rows[1]['loan_id']
        success, result = construct_permata_early_payoff_request_file_content(invalid_dict_rows)
        self.assertFalse(success)
        self.assertIn("Row 1: TGL_BAYAR_ENDUSER is not a valid date", result)
        self.assertIn("Row 2: LOAN_ID is missing", result)

        # TEST CASE 5: empty list
        success, result = construct_permata_early_payoff_request_file_content([])
        self.assertTrue(success)
        self.assertEqual(result, '')


class TestPermataGetDisbursementApproval(TestCase):
    def test_get_latest_permata_approval_filename(self):
        filenames = []
        result = get_latest_permata_approval_filename(filenames, 'APPROVAL')
        self.assertIsNone(result)

        filenames = [
            'OTHER_20210101000000.txt.gpg',
            'APPROVAL_20210101000000.txt.gpg',
            'REJECTED_20210102000000.xlsx.gpg',
            'APPROVAL_20210103000000.txt.gpg',
            'REJECTED_20210104000000.xlsx.gpg',
        ]

        result = get_latest_permata_approval_filename(filenames, 'APPROVAL')
        self.assertEqual(result, 'APPROVAL_20210103000000.txt.gpg')

        result = get_latest_permata_approval_filename(filenames, 'REJECTED')
        self.assertEqual(result, 'REJECTED_20210104000000.xlsx.gpg')

        result = get_latest_permata_approval_filename(filenames, 'ABC')
        self.assertIsNone(result)

    @patch(
        'juloserver.channeling_loan.services.permata_services.get_latest_permata_approval_filename'
    )
    @patch('juloserver.channeling_loan.services.permata_services.SFTPProcess')
    def test_download_latest_permata_disbursement_approval_files_from_sftp_server(
        self, mock_sftp_process, mock_get_latest_permata_approval_filename
    ):
        mock_sftp_process().list_dir.return_value = []
        is_success, result = download_latest_permata_disbursement_approval_files_from_sftp_server()
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path='Inbox')
        self.assertFalse(is_success)
        self.assertIsNone(result)
        mock_get_latest_permata_approval_filename.assert_not_called()

        mock_sftp_process().list_dir.reset_mock()
        mock_sftp_process().list_dir.return_value = ['test.txt.gpg']
        mock_get_latest_permata_approval_filename.return_value = 'test.txt.gpg'
        mock_sftp_process().download.return_value = 'XXXXXXXXXX'

        is_success, result = download_latest_permata_disbursement_approval_files_from_sftp_server()
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path='Inbox')
        mock_sftp_process().download.assert_called_with(remote_path='Inbox/test.txt.gpg')
        mock_get_latest_permata_approval_filename.assert_called()
        self.assertTrue(is_success)
        self.assertEqual(
            result,
            {
                'accepted_filename': 'test.txt.gpg',
                'accepted_encrypted_data': 'XXXXXXXXXX',
                'rejected_filename': 'test.txt.gpg',
                'rejected_encrypted_data': 'XXXXXXXXXX',
            },
        )

    def test_parse_permata_disbursement_accepted_loan_xids(self):
        # Test case 1: Normal case with multiple loan XIDs
        txt_data = """
        1      8310935048        PROD ONLY 6/12/2021 5/12/2021 5/01/2022 005
        2      8335950275        PROD ONLY 6/12/2021 5/12/2021 5/01/2022 005
        3       147415168        PROD ONLY 6/12/2021 5/12/2021 5/01/2022 004
        """
        result = parse_permata_disbursement_accepted_loan_xids(txt_data)
        self.assertEqual(result, ['8310935048', '8335950275', '147415168'])

        # Test case 2: Empty string
        txt_data = ""
        result = parse_permata_disbursement_accepted_loan_xids(txt_data)
        self.assertEqual(result, [])

        # Test case 3: No matching patterns
        txt_data = "This text contains no loan XIDs"
        result = parse_permata_disbursement_accepted_loan_xids(txt_data)
        self.assertEqual(result, [])

        # Test case 4: Mixed content with loan XIDs
        txt_data = """
        Some text here
        1      8310935048        PROD ONLY
        More text
        2      8335950275        PROD ONLY
        Even more text
        """
        result = parse_permata_disbursement_accepted_loan_xids(txt_data)
        self.assertEqual(result, ['8310935048', '8335950275'])

        # Test case 5: Loan XIDs with different formats (to test robustness)
        txt_data = """
        1   8310935048   PROD ONLY
        2 8335950275 PROD ONLY
        3      8347415168        PROD ONLY
        """
        result = parse_permata_disbursement_accepted_loan_xids(txt_data)
        self.assertEqual(result, ['8310935048', '8335950275', '8347415168'])

    def test_construct_permata_disbursement_approval_csv(self):
        # TEST CASE 1: Normal case with multiple accepted and rejected loan XIDs
        accepted_loan_xids = ['A001', 'A002', 'A003']
        rejected_loan_xids = ['R001', 'R002']

        # Call the function
        csv_content = construct_permata_disbursement_approval_csv(
            accepted_loan_xids, rejected_loan_xids
        )

        # Parse the CSV content
        csv_reader = csv.reader(io.StringIO(csv_content))
        rows = list(csv_reader)

        # Assertions
        self.assertEqual(len(rows), 6)  # Header + 3 accepted + 2 rejected
        self.assertEqual(rows[0], ['Application_XID', 'disetujui'])  # Check header

        # Check accepted loans
        for i, xid in enumerate(accepted_loan_xids, start=1):
            self.assertEqual(rows[i], [xid, 'y'])

        # Check rejected loans
        for i, xid in enumerate(rejected_loan_xids, start=4):
            self.assertEqual(rows[i], [xid, 'n'])

        # TEST CASE 2: empty accepted and rejected loan XIDs
        csv_content = construct_permata_disbursement_approval_csv([], [])
        csv_reader = csv.reader(io.StringIO(csv_content))
        rows = list(csv_reader)

        self.assertEqual(len(rows), 1)  # Only header
        self.assertEqual(rows[0], ['Application_XID', 'disetujui'])

        # TEST CASE 3: Only accepted loans
        accepted_loan_xids = ['A001', 'A002']
        csv_content = construct_permata_disbursement_approval_csv(accepted_loan_xids, [])
        csv_reader = csv.reader(io.StringIO(csv_content))
        rows = list(csv_reader)

        self.assertEqual(len(rows), 3)  # Header + 2 accepted
        self.assertEqual(rows[1], ['A001', 'y'])
        self.assertEqual(rows[2], ['A002', 'y'])

        # TEST CASE 4: Only rejected loans
        rejected_loan_xids = ['R001', 'R002']
        csv_content = construct_permata_disbursement_approval_csv([], rejected_loan_xids)
        csv_reader = csv.reader(io.StringIO(csv_content))
        rows = list(csv_reader)

        self.assertEqual(len(rows), 3)  # Header + 2 rejected
        self.assertEqual(rows[1], ['R001', 'n'])
        self.assertEqual(rows[2], ['R002', 'n'])

    @patch(
        'juloserver.channeling_loan.services.permata_services.'
        'download_latest_permata_disbursement_approval_files_from_sftp_server'
    )
    @patch('juloserver.channeling_loan.services.permata_services.decrypt_data')
    @patch('juloserver.channeling_loan.services.permata_services.replace_gpg_encrypted_file_name')
    @patch(
        'juloserver.channeling_loan.services.permata_services.'
        'construct_permata_disbursement_approval_csv'
    )
    @patch(
        'juloserver.channeling_loan.services.permata_services.'
        'parse_permata_disbursement_accepted_loan_xids'
    )
    @patch(
        'juloserver.channeling_loan.services.permata_services.'
        'parse_permata_disbursement_rejected_loan_xids'
    )
    def test_construct_permata_disbursement_approval_file(
        self,
        mock_parse_rejected,
        mock_parse_accepted,
        mock_construct_csv,
        mock_replace_filename,
        mock_decrypt,
        mock_download,
    ):
        # Test download failure
        mock_download.return_value = (False, None)
        result = construct_permata_disbursement_approval_file()
        self.assertEqual(result, (None, None))
        mock_download.assert_called_once()
        mock_decrypt.assert_not_called()
        mock_replace_filename.assert_not_called()
        mock_parse_accepted.assert_not_called()
        mock_parse_rejected.assert_not_called()
        mock_construct_csv.assert_not_called()

        # Test decryption failure
        mock_download.reset_mock()
        mock_download.return_value = (
            True,
            {
                'accepted_filename': 'accepted.gpg',
                'accepted_encrypted_data': b'encrypted_accepted',
                'rejected_filename': 'rejected.gpg',
                'rejected_encrypted_data': b'encrypted_rejected',
            },
        )
        mock_decrypt.return_value = None
        result = construct_permata_disbursement_approval_file()
        self.assertEqual(result, (None, None))
        mock_download.assert_called_once()
        mock_decrypt.assert_called_once()
        mock_replace_filename.assert_not_called()
        mock_parse_accepted.assert_not_called()
        mock_parse_rejected.assert_not_called()
        mock_construct_csv.assert_not_called()

        # Test happy case
        mock_download.reset_mock()
        mock_decrypt.reset_mock()
        mock_decrypt.side_effect = ['decrypted_accepted_data', b'decrypted_rejected_data']
        mock_replace_filename.return_value = 'output.csv'
        mock_parse_accepted.return_value = ['accepted1', 'accepted2']
        mock_parse_rejected.return_value = ['rejected1', 'rejected2']
        mock_construct_csv.return_value = 'csv_content'

        result = construct_permata_disbursement_approval_file()

        self.assertEqual(result, ('output.csv', 'csv_content'))
        mock_download.assert_called_once()
        self.assertEqual(mock_decrypt.call_count, 2)
        mock_replace_filename.assert_called_once_with(
            encrypted_file_name='accepted.gpg', new_file_extension='csv'
        )
        mock_parse_accepted.assert_called_once_with(txt_accepted_data='decrypted_accepted_data')
        mock_parse_rejected.assert_called_once_with(xlsx_rejected_data=b'decrypted_rejected_data')
        mock_construct_csv.assert_called_once_with(
            accepted_loan_xids=['accepted1', 'accepted2'],
            rejected_loan_xids=['rejected1', 'rejected2'],
        )

        mock_download.reset_mock()
        mock_decrypt.reset_mock()
        mock_replace_filename.reset_mock()
        mock_parse_accepted.reset_mock()
        mock_parse_rejected.reset_mock()
        mock_construct_csv.reset_mock()

    @patch(
        'juloserver.channeling_loan.services.permata_services.'
        'download_latest_permata_single_approval_file_from_sftp_server'
    )
    @patch('juloserver.channeling_loan.services.permata_services.replace_gpg_encrypted_file_name')
    @patch('juloserver.channeling_loan.services.permata_services.decrypt_data')
    def test_construct_permata_single_approval_file_success(
        self, mock_decrypt, mock_replace_filename, mock_download
    ):
        # Test download failure
        mock_download.return_value = (None, None)
        result = construct_permata_single_approval_file(filename_prefix='test_prefix')
        self.assertEqual(result, (None, None))
        mock_download.assert_called_once_with(filename_prefix='test_prefix')
        mock_replace_filename.assert_not_called()
        mock_decrypt.assert_not_called()

        # Test decryption failure
        mock_download.reset_mock()
        mock_download.return_value = ('encrypted.gpg', b'encrypted_data')
        mock_replace_filename.return_value = 'decrypted.txt'
        mock_decrypt.return_value = None
        result = construct_permata_single_approval_file('test_prefix')
        self.assertEqual(result, (None, None))
        mock_download.assert_called_once_with(filename_prefix='test_prefix')
        mock_replace_filename.assert_called_once_with(encrypted_file_name='encrypted.gpg')
        mock_decrypt.assert_called_once_with(
            filename='encrypted.gpg',
            content=b'encrypted_data',
            passphrase=settings.PERMATA_GPG_DECRYPT_PASSPHRASE,
            gpg_recipient=settings.PERMATA_GPG_DECRYPT_RECIPIENT,
            gpg_key_data=settings.PERMATA_GPG_DECRYPT_KEY_DATA,
        )

        # Test happy case
        mock_download.reset_mock()
        mock_replace_filename.reset_mock()
        mock_decrypt.reset_mock()
        mock_replace_filename.return_value = 'decrypted.txt'
        mock_decrypt.return_value = 'decrypted_content'
        result = construct_permata_single_approval_file(filename_prefix='test_prefix')
        self.assertEqual(result, ('decrypted.txt', 'decrypted_content'))
        mock_download.assert_called_once_with(filename_prefix='test_prefix')
        mock_replace_filename.assert_called_once_with(encrypted_file_name='encrypted.gpg')
        mock_decrypt.assert_called_once_with(
            filename='encrypted.gpg',
            content=b'encrypted_data',
            passphrase=settings.PERMATA_GPG_DECRYPT_PASSPHRASE,
            gpg_recipient=settings.PERMATA_GPG_DECRYPT_RECIPIENT,
            gpg_key_data=settings.PERMATA_GPG_DECRYPT_KEY_DATA,
        )
