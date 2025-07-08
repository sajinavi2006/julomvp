from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from mock import patch

from rest_framework.test import APIClient, APITestCase
from django.contrib.auth.models import Group
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)
from juloserver.application_flow.factories import (
    SuspiciousFraudAppsFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

class TestSuspiciousAppsList(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.datetime = datetime(2024, 5, 22, 7, 24, 37)
        self.current_datetime = timezone.datetime(2024, 5, 22, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            self.suspicious_app = SuspiciousFraudAppsFactory(
                package_names=["com.fakegps.com"],
                transaction_risky_check = "fake_app",
                updated_by_user_id = 1
            )


    def test_get_list(self):
        url = '/api/fraud-portal/suspicious-apps'
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
                        "suspicious_fraud_app_id": self.suspicious_app.id,
                        "package_names": [
                            "com.fakegps.com"
                        ],
                        "transaction_risky_check": "fake_app",
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
        url = '/api/fraud-portal/suspicious-apps'
        data = [
            {
                "package_names": "com.phoneclone.copymydata.smartswitch.app",
                "transaction_risky_check": "clone_app"
            }
        ]
        with patch('django.utils.timezone.now', return_value=self.current_datetime):
            response = self.client.post(url, data=data, format='json')
        expected_result = {
            "success": True,
            "data": [
                {
                    "suspicious_fraud_app_id": 5,
                    "package_names": [
                        "com.phoneclone.copymydata.smartswitch.app"
                    ],
                    "transaction_risky_check": "clone_app",
                    "cdate": "2024-05-22 12:00:00",
                    "udate": "2024-05-22 12:00:00"
                }
            ],
            "errors": []
        }
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # Remove id from response data for comparison due to dynamic id
        response['data'][0].pop('suspicious_fraud_app_id', None)
        expected_result['data'][0].pop('suspicious_fraud_app_id', None)
        self.assertEqual(response, expected_result)


    def test_delete_data(self):
        url = '/api/fraud-portal/suspicious-apps/'+str(self.suspicious_app.id)
        response = self.client.delete(url)
        expected_result = {
            "success": True,
            "data": "success",
            "errors": []
        }
        self.assertEqual(response.json(), expected_result)


    def test_upload_data(self):
        csv_content = b'suspicious_fraud_app_id,package_names,transaction_risky_check,cdate,udate\n49,com.intplus.idchanger,\
            device_spoofing_app_3,2023-07-17 10:30:38,2023-07-17 10:30:38\n'
        fake_csv_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        url = '/api/fraud-portal/suspicious-apps/upload'
        response = self.client.post(url, {'file': fake_csv_file})
        expected_result = {
            "data": "File uploaded successfully", 
            "errors": [], 
            "success": True
        }
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_result)
