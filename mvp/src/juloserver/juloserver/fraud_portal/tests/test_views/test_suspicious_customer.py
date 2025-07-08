from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from mock import patch

from rest_framework.test import APITestCase
from django.contrib.auth.models import Group
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)
from juloserver.pin.tests.factories import (
    BlacklistedFraudsterFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

class TestSuspiciousCustomersList(APITestCase):
    def setUp(self):
        self.maxDiff = None
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.datetime = datetime(2024, 5, 22, 7, 24, 37)
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.blacklisted_fraudster = BlacklistedFraudsterFactory(
                android_id=12345678,
                phone_number=None,
                blacklist_reason='report fraudster',
                updated_by_user_id=1
            )


    def test_get_list(self):
        url = '/api/fraud-portal/suspicious-customers'
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
                        "suspicious_customer_id": self.blacklisted_fraudster.id,
                        "android_id": "12345678",
                        "phone_number": "",
                        "type": 0,
                        "reason": "report fraudster",
                        "customer_id": "",
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
        url = '/api/fraud-portal/suspicious-customers'
        data = [
            {
                "android_id": "1000000004",
                "phone_number": "",
                "type" :0,
                "reason": "report fraudster",
                "customer_id": ""
            }
        ]
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            response = self.client.post(url, data=data, format='json')
        expected_result = {
            "success": True,
            "data": [
                {
                    "suspicious_customer_id": 1,
                    "android_id": "1000000004",
                    "phone_number": "",
                    "type": 0,
                    "reason": "report fraudster",
                    "customer_id": "",
                    "cdate": "2024-05-22 12:00:00",
                    "udate": "2024-05-22 12:00:00"
                }
            ],
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # Remove id from response data for comparison due to dynamic id
        response['data'][0].pop('suspicious_customer_id', None)
        expected_result['data'][0].pop('suspicious_customer_id', None)
        self.assertEqual(response, expected_result)


    def test_delete_data(self):
        url = '/api/fraud-portal/suspicious-customers/?id={}&type={}'\
            .format(str(self.blacklisted_fraudster.id), '0')
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 200)
        expected_result = {
            "success": True,
            "data": "success",
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)


    def test_upload_data(self):
        csv_content = b'android_id,phone_number,type,reason,customer_id\n,0833392838,0,report fraudster,\n'
        fake_csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        url = '/api/fraud-portal/suspicious-customers/upload'
        response = self.client.post(url, {'file': fake_csv_file})
        self.assertEqual(response.status_code, 200)
        expected_result = {
            "data": "File uploaded successfully", 
            "errors": [], 
            "success": True
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)
