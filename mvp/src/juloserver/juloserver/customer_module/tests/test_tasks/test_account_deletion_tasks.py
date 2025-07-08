from django.test import TestCase
from django.core.exceptions import ObjectDoesNotExist
from unittest.mock import patch, Mock
from juloserver.julo.models import Customer
from juloserver.customer_module.tasks.account_deletion_tasks import (
    handle_web_account_deletion_request,
)


class TestHandleWebAccountDeletionRequestTask(TestCase):

    data = {
        "fullname": "test",
        "nik": "1234567890123456",
        "phone": "081234567890",
        "email": "test@julofinance.com",
        "reason": "test",
        "details": "test",
        "image_ktp_filepath": "test",
        "image_selfie_filepath": "test",
    }

    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.WebAccountDeletionRequest.objects.create'
    )
    @patch('juloserver.customer_module.tasks.account_deletion_tasks.get_file_from_oss')
    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.forward_web_account_deletion_request_to_ops'
    )
    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.send_web_account_deletion_received_success'
    )
    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.delete_ktp_and_selfie_file_from_oss'
    )
    def test_happy_path(
        self,
        mock_create_web_account_deletion_request,
        mock_get_file_from_oss,
        mock_forward_web_account_deletion_request_to_ops,
        mock_send_web_account_deletion_received_success,
        mock_delete_ktp_and_selfie_file_from_oss,
    ):

        mock_customer = Mock()
        mock_customer.id = 0

        with patch(
            'juloserver.customer_module.tasks.account_deletion_tasks.Customer.objects.get',
            return_value=mock_customer,
        ):
            mock_create_web_account_deletion_request.return_value = None
            mock_get_file_from_oss.return_value = None
            mock_forward_web_account_deletion_request_to_ops.return_value = None
            mock_send_web_account_deletion_received_success.return_value = None
            mock_delete_ktp_and_selfie_file_from_oss.side_effect = None
            mock_delete_ktp_and_selfie_file_from_oss.return_value = None

            resp = handle_web_account_deletion_request(self.data)
            assert resp == None

    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.WebAccountDeletionRequest.objects.create'
    )
    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.send_web_account_deletion_received_failed'
    )
    @patch(
        'juloserver.customer_module.tasks.account_deletion_tasks.delete_ktp_and_selfie_file_from_oss'
    )
    def test_customer_not_found(
        self,
        mock_create_web_account_deletion_request,
        mock_send_web_account_deletion_received_failed,
        mock_delete_ktp_and_selfie_file_from_oss,
    ):

        with patch('juloserver.julo.models.Customer.objects.get') as mock_get_customer:
            mock_get_customer.side_effect = Customer.DoesNotExist
            mock_create_web_account_deletion_request.return_value = None
            mock_send_web_account_deletion_received_failed.return_value = None
            mock_delete_ktp_and_selfie_file_from_oss.side_effect = None

            resp = handle_web_account_deletion_request(self.data)
            assert resp == None

            mock_create_web_account_deletion_request.assert_called_once()
            mock_send_web_account_deletion_received_failed.assert_called_once()
            mock_delete_ktp_and_selfie_file_from_oss.assert_called_once()
