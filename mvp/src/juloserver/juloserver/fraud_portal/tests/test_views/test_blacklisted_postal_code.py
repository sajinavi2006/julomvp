from datetime import datetime
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from mock import patch

from rest_framework.test import APITestCase
from django.contrib.auth.models import Group
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedPostalCodeFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

class TestBlacklistedPostalCodeList(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.datetime = datetime(2024, 5, 22, 7, 24, 37)
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_postal_code = FraudBlacklistedPostalCodeFactory(
                id=20,
                postal_code='45434'
            )


    def test_get_list(self):
        url = '/api/fraud-portal/blacklisted-postal-codes'
        response = self.client.get(url)
        expected_result = {
            "success": True,
            "data": {
                "count": 1,
                "pages": 1,
                "next": None,
                "prev": None,
                "data": [
                    {
                        "fraud_blacklisted_postal_code_id": self.blacklisted_postal_code.id,
                        "postal_code": "45434",
                        "cdate": "2024-05-22 05:00:00",
                        "udate": "2024-05-22 05:00:00"
                    }
                ]
            },
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)

    def test_add_data(self):
        url = '/api/fraud-portal/blacklisted-postal-codes'
        data = [
            {
                "postal_code": "23456"
            }
        ]
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            response = self.client.post(url, data=data, format='json')
        expected_result = {
            "success": True,
            "data": [
                {
                    "fraud_blacklisted_postal_code_id": 1,
                    "postal_code": "23456",
                    "cdate": "2024-05-22 12:00:00",
                    "udate": "2024-05-22 12:00:00"
                }
            ],
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # Remove id from response data for comparison due to dynamic id
        response['data'][0].pop('fraud_blacklisted_postal_code_id', None)
        expected_result['data'][0].pop('fraud_blacklisted_postal_code_id', None)
        self.assertEqual(response, expected_result)


    def test_delete_data(self):
        url = '/api/fraud-portal/blacklisted-postal-codes/'+str(self.blacklisted_postal_code.id)
        response = self.client.delete(url)
        expected_result = {
            "success": True,
            "data": "success",
            "errors": []
        }
        self.assertEqual(response.json(), expected_result)


    def test_upload_data(self):
        csv_content = b'postal_code\n26789\n'
        fake_csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        url = '/api/fraud-portal/blacklisted-postal-codes/upload'
        response = self.client.post(url, {'file': fake_csv_file})
        expected_result = {
            "data": "File uploaded successfully", 
            "errors": [], 
            "success": True
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)
