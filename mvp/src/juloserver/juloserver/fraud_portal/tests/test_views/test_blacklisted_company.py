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
    FraudBlacklistedCompanyFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

class TestBlacklistedCompanyList(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.datetime = datetime(2024, 5, 22, 7, 24, 37)
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.fraud_blacklisted_company = FraudBlacklistedCompanyFactory(
                company_name='Wizard Comp'
            )


    def test_get_list(self):
        url = '/api/fraud-portal/blacklisted-companies'
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
                        "fraud_blacklisted_company_id": self.fraud_blacklisted_company.id,
                        "company_name": "Wizard Comp",
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
        url = '/api/fraud-portal/blacklisted-companies'
        data = [
            {
                "company_name": "PT Hobby"
            }
        ]
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            response = self.client.post(url, data=data, format='json')
        expected_result = {
            "success": True,
            "data": [
                {
                    "fraud_blacklisted_company_id": 1,
                    "company_name": "PT Hobby",
                    "cdate": "2024-05-22 12:00:00",
                    "udate": "2024-05-22 12:00:00"
                }
            ],
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # Remove id from response data for comparison due to dynamic id
        response['data'][0].pop('fraud_blacklisted_company_id', None)
        expected_result['data'][0].pop('fraud_blacklisted_company_id', None)
        self.assertEqual(response, expected_result)


    def test_delete_data(self):
        url = '/api/fraud-portal/blacklisted-companies/'+str(self.fraud_blacklisted_company.id)
        response = self.client.delete(url)
        expected_result = {
            "success": True,
            "data": "success",
            "errors": []
        }
        self.assertEqual(response.json(), expected_result)


    def test_upload_data(self):
        csv_content = b'company_name\nsure\n'
        fake_csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        url = '/api/fraud-portal/blacklisted-companies/upload'
        response = self.client.post(url, {'file': fake_csv_file})
        expected_result = {
            "data": "File uploaded successfully", 
            "errors": [], 
            "success": True
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)
