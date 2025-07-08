from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase
from mock.mock import patch

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
)
from juloserver.application_flow.factories import ApplicationRiskyCheckFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestConnectionAndDevice(APITestCase):
    def setUp(self):
        self.maxDiff = None
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.application = ApplicationFactory()

    @patch('juloserver.fraud_portal.services.connection_and_device.get_uninstalled')
    @patch('juloserver.fraud_portal.services.connection_and_device.get_overlap_connection_to_wifi')
    @patch('juloserver.fraud_portal.services.connection_and_device.get_overlap_installed_apps')
    def test_get_connection_and_device(
        self,
        mock_get_overlap_installed_apps,
        mock_get_overlap_connection_to_wifi,
        mock_get_uninstalled,
    ):
        mock_get_uninstalled.return_value = "Yes (03-05-2024 07:00:00)"
        mock_get_overlap_connection_to_wifi.return_value = [
            {"ip_address": "103.123.64.106", "ssid": "AndroidWifi", "number_of_overlap": 200}
        ]
        mock_get_overlap_installed_apps.return_value = [
            {
                "app_name": "Contacts Storage",
                "app_package_name": "com.android.providers.contacts",
                "number_of_overlap": 3662,
            }
        ]
        ApplicationRiskyCheckFactory(
            application=self.application,
            is_rooted_device=True,
            is_address_suspicious=True,
            is_special_event=True,
            is_bpjs_name_suspicious=False,
            is_bank_name_suspicious=False,
            is_bpjs_nik_suspicious=False,
            is_sus_ektp_generator_app=True,
            is_sus_camera_app=False,
            is_vpn_detected=False,
            is_fh_detected=True,
            is_similar_face_suspicious=True,
            is_sus_app_detected=True,
            is_dukcapil_not_match=False,
            is_mycroft_holdout=True,
            is_fraud_face_suspicious=False,
            is_high_risk_asn_mycroft=True,
        )
        expected_response = {
            "success": True,
            "data": [
                {
                    "application_id": self.application.id,
                    "application_fullname": self.application.fullname,
                    "uninstalled": "Yes (03-05-2024 07:00:00)",
                    "application_risky_flag": {
                        'is_address_device': True,
                        'is_bpjs_name_suspicious': False,
                        'is_bpjs_nik_suspicious': False,
                        'is_dukcapil_not_match': False,
                        'is_fh_detected': True,
                        'is_mycroft_holdout': True,
                        'is_rooted_device': True,
                        'is_similar_face_suspicious': True,
                        'is_special_event': True,
                        'is_sus_app_detected': True,
                        'is_sus_ektp_generator_app': True,
                        'is_suspicious_camera_app': False,
                        'is_vpn_detected': False,
                    },
                    "overlap_connection_to_wifi": [
                        {
                            "ip_address": "103.123.64.106",
                            "ssid": "AndroidWifi",
                            "number_of_overlap": 200,
                        }
                    ],
                    "overlap_installed_apps": [
                        {
                            "app_name": "Contacts Storage",
                            "app_package_name": "com.android.providers.contacts",
                            "number_of_overlap": 3662,
                        }
                    ],
                }
            ],
            "errors": [],
        }
        url = '/api/fraud-portal/connection-and-device/?application_id={0}'.format(
            self.application.id
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), expected_response)

    def test_failed_invalid_application_get_connection_and_device(self):
        invalid_application_id = self.application.id + 2024
        url = '/api/fraud-portal/connection-and-device/?application_id={0}'.format(
            invalid_application_id
        )
        response = self.client.get(url)
        expected_response = {
            "success": False,
            "data": None,
            "errors": ["Application matching query does not exist."],
        }
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), expected_response)
