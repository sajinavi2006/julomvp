from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.test import RequestFactory
from django.test.testcases import TestCase

from juloserver.channeling_loan.constants import (
    ChannelingLoanApprovalFileConst,
    ChannelingConst,
    ChannelingActionTypeConst,
)
from juloserver.channeling_loan.services.views_services import (
    get_approval_response,
    process_permata_early_payoff_request,
)


class TestViewsServices(TestCase):
    @patch('juloserver.channeling_loan.services.views_services.get_response_approval_file')
    @patch(
        'juloserver.channeling_loan.services.views_services.'
        'get_process_approval_response_time_delay_in_minutes'
    )
    @patch('juloserver.channeling_loan.services.views_services.get_latest_approval_file_object')
    @patch(
        'juloserver.channeling_loan.services.views_services.execute_new_approval_response_process'
    )
    @patch('juloserver.channeling_loan.services.views_services.messages')
    def test_get_approval_response(
        self, mock_messages, mock_execute, mock_get_latest, mock_get_delay, mock_get_response
    ):
        factory = RequestFactory()
        channeling_type = 'channel'
        file_type = 'test_file'
        base_url = reverse('channeling_loan_portal:list', args=[channeling_type])

        mock_get_delay.return_value = 3
        mock_get_latest.return_value = None
        request = factory.get('/')

        # Doesn't have any process => start new async process and return waiting message
        response = get_approval_response(
            request=request, channeling_type=channeling_type, file_type=file_type
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, base_url)  # noqa
        mock_execute.assert_called_once_with(channeling_type=channeling_type, file_type=file_type)
        mock_messages.info.assert_called_once_with(
            request, ChannelingLoanApprovalFileConst.BEING_PROCESSED_MESSAGE.format(3)
        )

        # Already started an async process, but being processed => return waiting message
        mock_messages.info.reset_mock()
        mock_get_latest.return_value = MagicMock(is_processed=False)
        response = get_approval_response(
            request=request, channeling_type=channeling_type, file_type=file_type
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, base_url)  # noqa
        mock_messages.info.assert_called_once_with(
            request, ChannelingLoanApprovalFileConst.BEING_PROCESSED_MESSAGE.format(3)
        )

        # Async process was success => return file
        mock_get_latest.return_value = MagicMock(
            is_processed=True, document_id=1, is_processed_succeed=True
        )
        mock_get_response.return_value = MagicMock()
        response = get_approval_response(
            request=request, channeling_type=channeling_type, file_type=file_type
        )
        self.assertEqual(response, mock_get_response.return_value)
        mock_get_response.assert_called_once_with(approval_file_document_id=1)

        # Async process was fail => return error message
        mock_get_latest.return_value = MagicMock(
            is_processed=True,
            document_id=None,
            is_processed_succeed=False,
            is_processed_failed=True,
        )
        response = get_approval_response(
            request=request, channeling_type=channeling_type, file_type=file_type
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, base_url)  # noqa
        mock_messages.error.assert_called_once_with(
            request, ChannelingLoanApprovalFileConst.ERROR_PROCESSED_MESSAGE
        )

    @patch('juloserver.channeling_loan.services.views_services.xls_to_dict')
    @patch(
        'juloserver.channeling_loan.services.views_services.'
        'construct_permata_early_payoff_request_file_content'
    )
    @patch('juloserver.channeling_loan.services.views_services.get_next_filename_counter_suffix')
    @patch(
        'juloserver.channeling_loan.services.views_services.'
        'encrypt_data_and_upload_to_permata_sftp_server'
    )
    @patch(
        'juloserver.channeling_loan.services.views_services.'
        'create_channeling_loan_send_file_tracking'
    )
    def test_process_permata_early_payoff_request_success(
        self,
        mock_create_tracking,
        mock_encrypt_upload,
        mock_get_suffix,
        mock_construct_content,
        mock_xls_to_dict,
    ):
        # Mock return values
        mock_xls_to_dict.return_value = {'sheet1': [{'col1': 'val1'}]}
        mock_construct_content.return_value = (True, 'content')

        # Create a mock file
        mock_file = SimpleUploadedFile("file.csv", b"file_content")

        result = process_permata_early_payoff_request(csv_file=mock_file, user_id=1)
        self.assertTrue(result[0])
        self.assertIsInstance(result[1], HttpResponse)
        mock_xls_to_dict.assert_called_once_with(mock_file)
        mock_construct_content.assert_called_once_with(dict_rows=[{'col1': 'val1'}])
        mock_get_suffix.assert_called_once()
        mock_encrypt_upload.delay.assert_called_once()
        mock_create_tracking.assert_called_once_with(
            channeling_type=ChannelingConst.PERMATA,
            action_type=ChannelingActionTypeConst.EARLY_PAYOFF,
            user_id=1,
        )

    @patch('juloserver.channeling_loan.services.views_services.xls_to_dict')
    def test_process_permata_early_payoff_request_invalid_file(self, mock_xls_to_dict):
        mock_xls_to_dict.side_effect = Exception("Invalid file")

        mock_file = SimpleUploadedFile("file.csv", b"file_content")

        result = process_permata_early_payoff_request(mock_file, 1)

        self.assertFalse(result[0])
        self.assertEqual(result[1], "Early payoff file has invalid data")

    @patch('juloserver.channeling_loan.services.views_services.xls_to_dict')
    @patch(
        'juloserver.channeling_loan.services.views_services.'
        'construct_permata_early_payoff_request_file_content'
    )
    def test_process_permata_early_payoff_request_construct_failure(
        self, mock_construct_content, mock_xls_to_dict
    ):
        mock_xls_to_dict.return_value = {'sheet1': [{'col1': 'val1'}]}
        mock_construct_content.return_value = (False, "Construction failed")

        mock_file = SimpleUploadedFile("file.csv", b"file_content")

        result = process_permata_early_payoff_request(mock_file, 1)

        self.assertFalse(result[0])
        self.assertEqual(result[1], "Construction failed")
