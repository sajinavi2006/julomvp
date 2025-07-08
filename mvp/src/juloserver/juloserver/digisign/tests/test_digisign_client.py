import json
import os
import tempfile
from unittest.mock import patch, Mock
from django.test import TestCase
from requests.exceptions import RequestException, Timeout
from juloserver.digisign.services.digisign_client import DigisignClient
from juloserver.julo.tests.factories import CustomerFactory


class TestDigisignClient(TestCase):
    def setUp(self):
        self.client = DigisignClient()
        self.client.base_url = "https://api.example.com"
        self.client.auth_token = "test_token"

        # Test data
        self.customer = CustomerFactory()
        self.file_path = "/path/to/document.pdf"
        self.document_detail = {
            "digisign_document_id": "1_loan_agreement_borrower",
            "file_name": "test.pdf",
            "sign_positions": [
                {"pos_x": "100", "pos_y": "200", "sign_page": "1"}
            ]
        }
        self.test_file = tempfile.NamedTemporaryFile(delete=False)
        self.test_file.write(b'Test file content')
        self.test_file.close()

    def tearDown(self):
        os.remove(self.test_file.name)

    def test_sign_document_empty_file_paths(self):
        """Test signing with empty file paths"""
        request_data = {
            'signer_xid': self.customer.customer_xid,
            'file_paths': [],
            'document_details': str({"documents": [self.document_detail]})
        }
        with self.assertRaises(ValueError):
            self.client.sign_documents(request_data)

    @patch('requests.post')
    @patch('builtins.open', new_callable=Mock, read_data='{}')
    def test_sign_client_document_success(self, mock_open, mock_post):
        """Test successful document signing"""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "data": {
                "responses": [
                    {
                        "file_name": "test.pdf",
                        "digisign_document_id": "1_loan_agreement_borrower",
                        "document_token": "12345",
                        "reference_number": "67890",
                        "status": "processing",
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        request_data = {
            'signer_xid': self.customer.id,
            'file_path': self.file_path,
            'document_detail': self.document_detail
        }

        success, result = self.client.sign_document(request_data)

        self.assertTrue(success)
        expected_response = {
            '1_loan_agreement_borrower': {
                'file_name': 'test.pdf',
                'digisign_document_id': '1_loan_agreement_borrower',
                'document_token': '12345',
                'reference_number': '67890',
                'status': 'processing'
            }
        }
        self.assertEqual(expected_response, result)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['timeout'], self.client.REQUEST_TIMEOUT)
        self.assertIn('files', kwargs)
        self.assertIn('data', kwargs)
        self.assertEqual(
            kwargs['data'],
            {
                'customer_xid': self.customer.id,
                'document_details': str(json.dumps({"documents": [self.document_detail]}))
            }
        )

    @patch('requests.post')
    def test_sign_document_api_error(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        request_data = {
            'signer_xid': self.customer.id,
            'file_path': self.test_file.name,
            'document_detail': self.document_detail
        }

        success, result = self.client.sign_document(request_data)

        self.assertFalse(success)
        self.assertEqual(result, {'status': 'failed', 'error': 'Bad Request'})

    @patch('requests.post')
    def test_sign_document_request_exception(self, mock_post):
        mock_post.side_effect = RequestException("Connection error")

        request_data = {
            'signer_xid': self.customer.id,
            'file_path': self.test_file.name,
            'document_detail': self.document_detail
        }
        success, result = self.client.sign_document(request_data)

        self.assertFalse(success)
        self.assertEqual(result, {'status': 'failed', 'error': 'Connection error'})

    @patch('requests.post')
    def test_sign_document_timeout(self, mock_post):
        mock_post.side_effect = Timeout("Request timed out")

        request_data = {
            'signer_xid': self.customer.id,
            'file_path': self.test_file.name,
            'document_detail': self.document_detail
        }
        success, result = self.client.sign_document(request_data)
        self.assertFalse(success)
        self.assertEqual(result, {'status': 'failed', 'error': 'Request timed out'})
