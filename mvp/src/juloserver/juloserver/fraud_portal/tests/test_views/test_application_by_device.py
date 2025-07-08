import pytz
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    DeviceFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

jakarta_tz = pytz.timezone('Asia/Jakarta')


class TestApplicationsByDevice(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.application = ApplicationFactory(
            id=77777,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_street_num="kalideres no 3",
            name_in_bank="haidyan",
            customer=self.customer,
            gender="Pria",
            monthly_income=2800000,
            last_month_salary='2011-12-09',
            employment_status='full time',
        )
        self.user_2 = AuthUserFactory()
        self.customer_2 = CustomerFactory(user=self.user_2)
        self.application_2 = ApplicationFactory(
            id=99999,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_street_num="kalideres no 3",
            name_in_bank="haidyan",
            customer=self.customer_2,
            gender="Pria",
            monthly_income=2800000,
            last_month_salary='2011-12-09',
            employment_status='full time',
        )
        self.device = DeviceFactory(
            device_model_name='Iphone 17 Ultra', android_id='android12311', customer=self.customer
        )
        self.device_2 = DeviceFactory(
            device_model_name='Samsung S25 Pro max', ios_id='ios12311', customer=self.customer
        )
        self.device_3 = DeviceFactory(
            device_model_name='Iphone 17 Ultra', android_id='android12311', customer=self.customer_2
        )
        self.application.device = self.device
        self.application.save()

    def test_get_applications_by_android(self):
        # arrange
        url = '/api/fraud-portal/applications-by-device/?android_id=android12311'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()

        expected_ids = sorted([99999, 77777])
        actual_ids = response_json["data"]
        self.assertTrue(response_json["success"])
        self.assertEqual(response_json["errors"], [])
        self.assertEqual(sorted(actual_ids), expected_ids)

    def test_get_applications_by_ios(self):
        # arrange
        url = '/api/fraud-portal/applications-by-device/?ios_id=ios12311'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()

        expected_ids = [77777]
        actual_ids = response_json["data"]
        self.assertTrue(response_json["success"])
        self.assertEqual(response_json["errors"], [])
        self.assertEqual(actual_ids, expected_ids)

    def test_get_applications_by_ios_and_android(self):
        # arrange
        url = '/api/fraud-portal/applications-by-device/?ios_id=ios12311&android_id=android12311'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()

        expected_ids = None
        actual_ids = response_json["data"]

        self.assertFalse(response_json["success"])
        self.assertEqual(
            response_json["errors"], ['you can only use either android_id or ios_id, but not both']
        )
        self.assertEqual(actual_ids, expected_ids)

    def test_get_applications_without_ios_and_android(self):
        # arrange
        url = '/api/fraud-portal/applications-by-device/'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()

        expected_ids = []
        actual_ids = response_json["data"]

        self.assertTrue(response_json["success"])
        self.assertEqual(response_json["errors"], [])
        self.assertEqual(actual_ids, expected_ids)
