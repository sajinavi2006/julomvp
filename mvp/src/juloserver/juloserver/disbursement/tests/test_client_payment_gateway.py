from django.test import TestCase
from unittest.mock import patch, MagicMock
import json
import time

from juloserver.disbursement.clients.payment_gateway import (
    PaymentGatewayClient,
    TransferResponse,
    InquiryResponse,
    Vendor,
    PaymentGatewayApiError,
    PaymentGatewayAPIInternalError,
)


class TestPaymentGatewayClient(TestCase):
    def setUp(self):
        self.client = PaymentGatewayClient(
            base_url="https://api.example.com",
            client_id="test_client_id",
            secret_key="test_secret_key",
            api_key="test_api_key",
        )

        # Common test data
        self.test_bank_data = {
            "bank_account": "1234567890",
            "bank_id": 1,
            "bank_account_name": "John Doe",
            "preferred_pg": 'doku',
        }

        self.test_transfer_data = {
            **self.test_bank_data,
            "object_transfer_id": "TR123",
            "object_transfer_type": "DISBURSEMENT",
            "amount": "100000",
            "callback_url": "https://callback.example.com",
        }

    def test_generate_signature(self):
        """Test signature generation logic"""
        timestamp = 1234567890.0
        method = "POST"
        path = "/v1/transfer"

        signature_data = self.client._generate_signature(method, path, timestamp)

        self.assertIn('signature', signature_data)
        self.assertIn('api_key_hash', signature_data)
        self.assertTrue(isinstance(signature_data['signature'], str))
        self.assertTrue(isinstance(signature_data['api_key_hash'], str))

    @patch('requests.request')
    def test_validate_bank_account_success(self, mock_request):
        """Test successful bank account validation"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "bank_account": self.test_bank_data["bank_account"],
                "bank_code": "bca",
                "bank_id": self.test_bank_data["bank_id"],
                "bank_account_name": self.test_bank_data["bank_account_name"],
                "preferred_pg": self.test_bank_data["preferred_pg"],
                "validation_result": {"is_valid": True},
            }
        }
        mock_request.return_value = mock_response

        response = self.client.validate_bank_account(**self.test_bank_data)

        self.assertFalse(response['is_error'])
        self.assertIsNone(response['error'])
        self.assertIsInstance(response['response'], InquiryResponse)
        self.assertEqual(response['response'].bank_account, self.test_bank_data["bank_account"])

    @patch('requests.request')
    def test_validate_bank_account_failure(self, mock_request):
        """Test failed bank account validation"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "Invalid bank account"}
        mock_request.return_value = mock_response

        response = self.client.validate_bank_account(**self.test_bank_data)

        self.assertTrue(response['is_error'])
        self.assertIsInstance(response['error'], PaymentGatewayAPIInternalError)

    @patch('requests.request')
    def test_create_disbursement_success(self, mock_request):
        """Test successful disbursement creation"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "transaction_id": 12345,
                "object_transfer_id": "TR123",
                "object_transfer_type": "DISBURSEMENT",
                "transaction_date": "2025-01-23T10:00:00Z",
                "status": "PENDING",
                "amount": self.test_transfer_data["amount"],
                "bank_account": self.test_transfer_data["bank_account"],
                "bank_account_name": self.test_transfer_data["bank_account_name"],
                "bank_id": self.test_transfer_data["bank_id"],
                "bank_code": "014",
                "preferred_pg": self.test_transfer_data["preferred_pg"],
                "message": None,
                "can_retry": True,
            }
        }
        mock_request.return_value = mock_response

        response = self.client.create_disbursement(**self.test_transfer_data)

        self.assertFalse(response['is_error'])
        self.assertIsNone(response['error'])
        self.assertIsInstance(response['response'], TransferResponse)
        self.assertEqual(response['response'].transaction_id, 12345)
        self.assertEqual(response['response'].status, "PENDING")

    @patch('requests.request')
    def test_create_disbursement_server_error(self, mock_request):
        """Test disbursement creation with server error"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal server error"}
        mock_request.return_value = mock_response

        response = self.client.create_disbursement(**self.test_transfer_data)

        self.assertTrue(response['is_error'])
        self.assertIsInstance(response['error'], PaymentGatewayApiError)

    @patch('requests.request')
    def test_get_transfer_status_success(self, mock_request):
        """Test successful transfer status retrieval"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "transaction_id": 12345,
                    "object_transfer_id": "TR123",
                    "object_transfer_type": "DISBURSEMENT",
                    "transaction_date": "2025-01-23T10:00:00Z",
                    "status": "SUCCESS",
                    "amount": "100000",
                    "bank_account": "1234567890",
                    "bank_account_name": "John Doe",
                    "bank_code": "BCA",
                    "bank_id": 1,
                    "preferred_pg": Vendor.DOKU,
                    "message": None,
                    "can_retry": False,
                }
            ]
        }
        mock_request.return_value = mock_response

        response = self.client.get_transfer_status(
            preferred_pg=Vendor.DOKU, object_transfer_id="TR123"
        )

        self.assertIsInstance(response['response'], list)
        self.assertEqual(len(response['response']), 1)
        self.assertIsInstance(response['response'][0], TransferResponse)
        self.assertEqual(response['response'][0].status, "SUCCESS")

    @patch('requests.request')
    def test_request_exception_handling(self, mock_request):
        """Test handling of request exceptions"""
        mock_request.side_effect = Exception("Network error")

        response = self.client.validate_bank_account(**self.test_bank_data)

        self.assertTrue(response['is_error'])
        self.assertIsInstance(response['error'], PaymentGatewayApiError)
        self.assertIsNone(response['response'])
