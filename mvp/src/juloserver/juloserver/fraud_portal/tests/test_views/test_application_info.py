import pytz
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    DeviceFactory,
    ImageFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

jakarta_tz = pytz.timezone('Asia/Jakarta')

class TestApplicationInfo(APITestCase):
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
        self.device = DeviceFactory(
            device_model_name='Iphone 17 Ultra', android_id='android 12311', customer=self.customer
        )
        self.device2 = DeviceFactory(
            device_model_name='Iphone 17 Ultra', android_id='android 12311', customer=self.customer
        )
        self.application.device = self.device
        self.application.save()
        self.documnt_1 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.documnt_2 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.documnt_3 = ImageFactory(
            image_source=self.application.id, image_status=-1, image_type='ktp'
        )

    def test_get_application_info(self):
        # arrange
        url = '/api/fraud-portal/application-info/?application_id=77777'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()

        application_data = response_json["data"][0]
        self.assertTrue(response_json["success"])
        self.assertEqual(response_json["errors"], [])
        self.assert_response(self.application, self.device, application_data, 2, 1)

    def test_get_application_info_without_documents(self):
        # arrange
        self.user_2 = AuthUserFactory(username='testpartner')
        self.group_2 = Group(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.group_2.save()
        self.user_2.groups.add(self.group)
        self.customer_2 = CustomerFactory(user=self.user_2)
        self.application_2 = ApplicationFactory(
            id=1123,
            fullname='delberth',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_detail="kalideres",
            address_street_num="kalideres no 1",
            name_in_bank="delberth",
            application_xid="22222222",
            customer=self.customer_2,
            gender="Perempuan",
            monthly_income=2800000,
            last_month_salary='2011-12-09',
            employment_status='full time',
        )
        self.device_2 = DeviceFactory(
            device_model_name='Iphone 18 Ultra',
            android_id='android 12311',
            customer=self.customer_2,
        )
        self.application_2.device = self.device_2
        self.application_2.save()
        url = '/api/fraud-portal/application-info/?application_id=1123'

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        application_data = response_json["data"][0]
        self.assertTrue(response_json["success"])
        self.assertEqual(response_json["errors"], [])
        self.assert_response(self.application_2, self.device_2, application_data, 0, 0)

    def assert_response(
        self,
        expected_application,
        expected_device,
        application_data,
        total_document,
        total_other_documents,
    ):
        self.assertEqual(application_data["application_id"], expected_application.id)
        self.assertEqual(application_data["application_full_name"], expected_application.fullname)
        self.assertEqual(application_data["application_status_code"], expected_application.status)
        self.assertEqual(application_data["application_status"], expected_application.code_status)
        self.assertEqual(
            application_data["cdate"], str(expected_application.cdate.astimezone(jakarta_tz))
        )
        self.assertEqual(application_data["ktp"], expected_application.ktp)
        self.assertEqual(application_data["email"], expected_application.email)
        self.assertEqual(application_data["dob"], str(expected_application.dob))
        self.assertEqual(application_data["birth_place"], expected_application.birth_place)
        self.assertEqual(application_data["mobile_phone_1"], expected_application.mobile_phone_1)
        self.assertEqual(application_data["marital_status"], expected_application.marital_status)
        self.assertEqual(
            application_data["spouse_or_kin_mobile_phone"], expected_application.spouse_mobile_phone
        )
        self.assertEqual(application_data["spouse_or_kin_name"], expected_application.spouse_name)
        self.assertEqual(
            application_data["address_detail"], expected_application.address_street_num
        )
        self.assertEqual(
            application_data["address_provinsi"], expected_application.address_provinsi
        )
        self.assertEqual(
            application_data["address_kabupaten"], expected_application.address_kabupaten
        )
        self.assertEqual(
            application_data["address_kecamatan"], expected_application.address_kecamatan
        )
        self.assertEqual(
            application_data["address_kelurahan"], expected_application.address_kelurahan
        )
        self.assertEqual(application_data["bank_name"], expected_application.bank_name)
        self.assertEqual(application_data["name_in_bank"], expected_application.name_in_bank)
        self.assertEqual(
            application_data["bank_account_number"], expected_application.bank_account_number
        )
        self.assertEqual(application_data["gender"], expected_application.gender)
        self.assertEqual(
            application_data["employment_status"], expected_application.employment_status
        )
        self.assertEqual(application_data["bpjs_package"], "JHT,JKK,JKM,JPN")

        expected_device_model_name = None
        expected_android_id = None
        if len(application_data["device_info_list"]) > 0:
            expected_device_model_name = application_data["device_info_list"][0][
                "device_model_name"
            ]
            expected_android_id = application_data["device_info_list"][0]["android_id"]

        self.assertEqual(expected_device_model_name, expected_device.device_model_name)
        self.assertEqual(expected_android_id, expected_device.android_id)
        self.assertTrue(len(application_data["documents"]) == total_document)
        self.assertTrue(len(application_data["other_documents"]) == total_other_documents)
