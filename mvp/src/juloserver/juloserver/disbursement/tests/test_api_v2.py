from unittest.mock import patch

from django.conf import settings
from rest_framework.test import APITestCase
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
)


class TestXenditDisburseEventCallbackViewV2(APITestCase):
    def setUp(self):
        self.client.credentials(HTTP_X_CALLBACK_TOKEN=settings.XENDIT_DISBURSEMENT_VALIDATION_TOKEN)
        self.url = '/api/disbursement/callbacks/v2/xendit-disburse'

    def test_case_no_data(self):
        data = {}
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_case_missing_data(self):
        # missing some optional fields
        data = {
            "id": "57e214ba82b034c325e84d6e",
            "external_id": "disbursement_123124123",
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "status": "COMPLETED",
        }
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)

        # miss an important field
        data = {
            "id": "57e214ba82b034c325e84d6e",
            # "external_id": "disbursement_123124123",
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "status": "COMPLETED",
        }
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)


    @patch('juloserver.disbursement.views.views_api_v2.process_xendit_callback')
    def test_case_status_completed(self, xendit_task):
        data = {
            "id": "57e214ba82b034c325e84d6e",
            "created": "2021-07-10T08:15:03.404Z",
            "updated": "2021-07-10T08:15:03.404Z",
            "external_id": "disbursement_123124123",
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "disbursement_description": "Refund for shoes",
            "status": "COMPLETED",
            "is_instant": True,
        }
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        xendit_task.delay.assert_called_once_with(
            disburse_id=data['external_id'],
            xendit_response=data,
        )

    def test_case_status_failed(self):
        data = {
            "id": "57e214ba82b034c325e84d6e",
            "created": "2021-07-10T08:15:03.404Z",
            "updated": "2021-07-10T08:15:03.404Z",
            "external_id": "disbursement_123124123",
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "disbursement_description": "Refund for shoes",
            "status": "FAILED",
            "is_instant": True,
        }
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, HTTP_200_OK)
