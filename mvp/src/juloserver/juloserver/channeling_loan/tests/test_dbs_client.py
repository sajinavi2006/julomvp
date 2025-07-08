import json
import requests
from django.test import TestCase
from unittest.mock import patch, Mock

from juloserver.channeling_loan.clients import DBSChannelingClient
from juloserver.channeling_loan.exceptions import DBSApiError


class TestDBSChannelingClient(TestCase):
    def setUp(self):
        self.base_url: str = "https://api.dbs.com"
        self.api_key: str = "test-api-key"
        self.org_id: str = "test-org-id"
        self.client: DBSChannelingClient = DBSChannelingClient(
            base_url=self.base_url, api_key=self.api_key, org_id=self.org_id
        )

    def test_init_removes_trailing_slash(self):
        client = DBSChannelingClient(
            base_url="https://api.dbs.com/", api_key=self.api_key, org_id=self.org_id
        )
        self.assertEqual(client.base_url, "https://api.dbs.com")
        self.assertEqual(client.api_key, self.api_key)
        self.assertEqual(client.org_id, self.org_id)

    @patch('juloserver.channeling_loan.clients.dbs.requests.post')
    def test_send_loan_successful(self, mock_post):
        # Arrange
        loan_id = 12345
        x_dbs_uuid = "test-uuid"
        x_dbs_timestamp = "2024-01-01T00:00:00Z"
        disbursement_request_body = {"amount": 10000, "currency": "SGD"}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}
        mock_post.return_value = mock_response

        expected_url = f"{self.base_url}/unsecuredLoans/application"
        expected_headers = {
            'Content-Type': 'text/plain',
            'X-DBS-ORG_ID': self.org_id,
            'x-api-key': self.api_key,
            'X-DBS-uuid': x_dbs_uuid,
            'X-DBS-timestamp': x_dbs_timestamp,
        }

        # Act
        response = self.client.send_loan(
            loan_id=loan_id,
            x_dbs_uuid=x_dbs_uuid,
            x_dbs_timestamp=x_dbs_timestamp,
            disbursement_request_body=json.dumps(disbursement_request_body),
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})

        mock_post.assert_called_once_with(
            expected_url, headers=expected_headers, data=json.dumps(disbursement_request_body)
        )

    @patch('juloserver.channeling_loan.clients.dbs.requests.post')
    def test_send_loan_api_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError()

        # Act & Assert
        with self.assertRaises(DBSApiError) as context:
            self.client.send_loan(
                loan_id=12345,
                x_dbs_uuid="test-uuid",
                x_dbs_timestamp="2024-01-01T00:00:00Z",
                disbursement_request_body=json.dumps({"amount": 10000, "currency": "IDR"}),
            )

        self.assertEqual(context.exception.response_status_code, 0)
        self.assertEqual(context.exception.response_text, '')
