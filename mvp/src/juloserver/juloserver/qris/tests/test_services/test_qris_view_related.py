import datetime
from mock import patch

from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.apiv2.tests.test_apiv2_services import CustomerFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.services.view_related import (
    get_monthly_income_range,
    get_education_level_label,
    get_gender_label,
    get_marital_status_label,
    convert_image_to_base64
)
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    PartnerFactory,
    ApplicationFactory,
    ImageFactory,
    StatusLookupFactory
)


class TestAmarPrefilledAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth,
            fullname="John Doe",
            phone="01234567890",
            address_street_num="1",
            address_kelurahan="2",
            address_kecamatan="3",
            address_kabupaten="4",
            address_provinsi="5",
            address_kodepos="6",
            address_detail="Apt 4B",
            dob=datetime.date(2004, 3, 2),
            birth_place="BANDUNG",
            gender="Pria",
            nik="3175095001670004",
            marital_status="Lajang",
            job_description="Admin",
            company_name="Selly salon",
            last_education="SLTA",
            monthly_income=3000000,
            mother_maiden_name="Dariyah",
            job_type="Freelance",
            kin_name="Masitoh",
            job_industry="Service",
        )

        self.customer.current_application_id = 2011232020
        self.customer.save()
        self.image = ImageFactory(
            image_type='ktp_self',
            image_source=self.customer.current_application_id,
            image_status=0
        )
        self.token = self.user_auth.auth_expiry_token
        self.client.force_login(self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.partner_xid = "Amar123321"
        self.partner = PartnerFactory(
            user=self.user_auth, name=PartnerNameConstant.AMAR, partner_xid=self.partner_xid
        )
        self.qris_partner_linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            status=QrisLinkageStatus.REQUESTED,
        )
        self.to_partner_user_xid = self.qris_partner_linkage.to_partner_user_xid
        self.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            id=self.customer.current_application_id,
            application_status=self.application_status,
        )

    def test_get_prefilled_data(self):
        monthly_income_range = get_monthly_income_range(self.customer.monthly_income)
        education = get_education_level_label(self.customer.last_education)
        gender = get_gender_label(self.customer.gender)
        marital_status = get_marital_status_label(self.customer.marital_status)
        detail_user_data = {
            "companyField": "",
            "companyName": self.customer.company_name,
            "education": education,
            "monthlyIncome": monthly_income_range,
            "motherName": self.customer.mother_maiden_name,
            "taxNumber": "",
            "phoneNumber": self.customer.phone,
            "position": self.customer.job_type,
            "purpose": "Rekening Tabungan",
            "relatives": self.customer.kin_name,
            "sourceOfIncome": "Gaji Bulanan",
            "occupation": "",
        }

        domicile_address_data = {
            "address": self.customer.address_street_num,
            "city": self.customer.address_kabupaten,
            "district": self.customer.address_kecamatan,
            "homeType": "",
            "postalCode": self.customer.address_kodepos,
            "province": self.customer.address_provinsi,
            "rt": "0",
            "rw": "0",
            "village": self.customer.address_kelurahan
        }

        id_card_data = {
            "address": self.customer.address_street_num,
            "birthDate": self.customer.dob,
            "birthPlace": self.customer.birth_place,
            "city": self.customer.address_kabupaten,
            "district": self.customer.address_kecamatan,
            "fullName": self.customer.fullname,
            "gender": gender,
            "idCardNumber": self.customer.nik,
            "maritalStatus": marital_status,
            "postalCode": self.customer.address_kodepos,
            "province": self.customer.address_provinsi,
            "religion": "",
            "rt": "0",
            "rw": "0",
            "village": self.customer.address_kelurahan
        }

        expected_response = {
            "detailUserData": detail_user_data,
            "domicileAddressData": domicile_address_data,
            "idCardData": id_card_data,
        }
        image_base_64 = convert_image_to_base64(self.image)
        if image_base_64:
            id_card_file_data = {
                "imageBase64": image_base_64
            }
            expected_response['idCardFileData'] = id_card_file_data
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid}', **headers)
        assert response.status_code == 200
        self.assertEqual(
            expected_response,
            response.data
        )

        # test xid in hex
        response = self.client.get(
            f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers
        )
        assert response.status_code == 200
        self.assertEqual(expected_response, response.data)

        # invalid uuid
        bad_uuid = "abc123-wukong"
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{bad_uuid}', **headers)
        assert response.status_code == 400
        self.assertIn("invalid xid", response.data['errors'][0])

    def test_get_prefilled_data_for_image_status_1(self):
        monthly_income_range = get_monthly_income_range(self.customer.monthly_income)
        education = get_education_level_label(self.customer.last_education)
        gender = get_gender_label(self.customer.gender)
        marital_status = get_marital_status_label(self.customer.marital_status)
        self.image.image_status = 1
        self.image.save()
        detail_user_data = {
            "companyField": "",
            "companyName": self.customer.company_name,
            "education": education,
            "monthlyIncome": monthly_income_range,
            "motherName": self.customer.mother_maiden_name,
            "taxNumber": "",
            "phoneNumber": self.customer.phone,
            "position": self.customer.job_type,
            "purpose": "Rekening Tabungan",
            "relatives": self.customer.kin_name,
            "sourceOfIncome": "Gaji Bulanan",
            "occupation": "",
        }

        domicile_address_data = {
            "address": self.customer.address_street_num,
            "city": self.customer.address_kabupaten,
            "district": self.customer.address_kecamatan,
            "homeType": "",
            "postalCode": self.customer.address_kodepos,
            "province": self.customer.address_provinsi,
            "rt": "0",
            "rw": "0",
            "village": self.customer.address_kelurahan
        }

        id_card_data = {
            "address": self.customer.address_street_num,
            "birthDate": self.customer.dob,
            "birthPlace": self.customer.birth_place,
            "city": self.customer.address_kabupaten,
            "district": self.customer.address_kecamatan,
            "fullName": self.customer.fullname,
            "gender": gender,
            "idCardNumber": self.customer.nik,
            "maritalStatus": marital_status,
            "postalCode": self.customer.address_kodepos,
            "province": self.customer.address_provinsi,
            "religion": "",
            "rt": "0",
            "rw": "0",
            "village": self.customer.address_kelurahan
        }

        expected_response = {
            "detailUserData": detail_user_data,
            "domicileAddressData": domicile_address_data,
            "idCardData": id_card_data,
        }
        image_base_64 = convert_image_to_base64(self.image)
        if image_base_64:
            id_card_file_data = {
                "imageBase64": image_base_64
            }
            expected_response['idCardFileData'] = id_card_file_data
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid}', **headers)
        assert response.status_code == 200
        self.assertEqual(
            expected_response,
            response.data
        )

    def test_permission_qris_prefilled_api(self):
        # without headers => will get 403
        res = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid}')
        assert res.status_code == 403

        # wrong partner_xid
        headers = {'HTTP_PARTNERXID': 'invalid_xid'}
        res = self.client.post('/api/qris/v1/transaction-limit-check', **headers)
        assert res.status_code == 403

        # request headers => success
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        res = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid}', **headers)
        assert res.status_code == 200

        # user is not partner
        self.partner.user_id = None
        self.partner.save()
        res = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid}')
        assert res.status_code == 403

        # invalid to_partner_user_xid
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        res = self.client.get(f'/api/qris/v1/amar/prefilled-data/38cb4d52ac4b4dbb8efea4a80643f4bf', **headers)
        assert res.status_code == 403

    def test_monthly_income_range(self):
        headers = {'HTTP_PARTNERXID': self.partner_xid}

        # income=None output -> monthly_income = "Dibawah 3 juta"
        self.customer.monthly_income = None
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Dibawah 3 juta", response.data['detailUserData']['monthlyIncome'])

        # income=2_500_000 output -> monthly_income = "Dibawah 3 juta"
        self.customer.monthly_income = 2_500_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Dibawah 3 juta", response.data['detailUserData']['monthlyIncome'])

        # income=4_000_000 output -> monthly_income = "3 - 5 juta"
        self.customer.monthly_income = 4_000_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("3 - 5 juta", response.data['detailUserData']['monthlyIncome'])

        # income=5_000_000 output -> monthly_income = "5 - 10 juta"
        self.customer.monthly_income = 5_000_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("5 - 10 juta", response.data['detailUserData']['monthlyIncome'])

        # income=2_500_000 output -> monthly_income = "10 - 20 juta"
        self.customer.monthly_income = 11_000_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("10 - 20 juta", response.data['detailUserData']['monthlyIncome'])

        # income=2_500_000 output -> monthly_income = "20 - 30 juta"
        self.customer.monthly_income = 21_500_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("20 - 30 juta", response.data['detailUserData']['monthlyIncome'])

        # income=32_500_000 output -> monthly_income = "30 - 50 juta"
        self.customer.monthly_income = 32_500_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("30 - 50 juta", response.data['detailUserData']['monthlyIncome'])

        # income=52_500_000 output -> monthly_income = "50 - 100 juta"
        self.customer.monthly_income = 52_500_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("50 - 100 juta", response.data['detailUserData']['monthlyIncome'])

        # income=102_500_000 output -> monthly_income = "Diatas 100 juta"
        self.customer.monthly_income = 102_500_000
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Diatas 100 juta", response.data['detailUserData']['monthlyIncome'])

    def test_gender(self):
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        # male
        self.customer.gender = "Pria"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Laki-Laki", response.data['idCardData']['gender'])

        # female
        self.customer.gender = "Wanita"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Perempuan", response.data['idCardData']['gender'])

    def test_education(self):
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        # "SD": "SD",
        self.customer.last_education = "SD"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("SD", response.data['detailUserData']['education'])

        # "SLTP": "SMP",
        self.customer.last_education = "SLTP"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("SMP", response.data['detailUserData']['education'])

        # "SLTA": "SMA",
        self.customer.last_education = "SLTA"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("SMA", response.data['detailUserData']['education'])

        # "Diploma": "Diploma",
        self.customer.last_education = "Diploma"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("Diploma", response.data['detailUserData']['education'])

        # "S1": "S1 (Sarjana)",
        self.customer.last_education = "S1"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("S1 (Sarjana)", response.data['detailUserData']['education'])

        # "S2": "S2 (Magister)",
        self.customer.last_education = "S2"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("S2 (Magister)", response.data['detailUserData']['education'])

        # "S3": "S3 (Doktoral)"
        self.customer.last_education = "S3"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("S3 (Doktoral)", response.data['detailUserData']['education'])

    def test_marital_status(self):
        headers = {'HTTP_PARTNERXID': self.partner_xid}

        # "Lajang": "BELUM KAWIN",
        self.customer.marital_status = "Lajang"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("BELUM KAWIN", response.data['idCardData']['maritalStatus'])

        # "Menikah": "KAWIN",
        self.customer.marital_status = "Menikah"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("KAWIN", response.data['idCardData']['maritalStatus'])

        # "Cerai": "CERAI HIDUP",
        self.customer.marital_status = "Cerai"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("CERAI HIDUP", response.data['idCardData']['maritalStatus'])

        # "Janda / duda": "CERAI MATI"
        self.customer.marital_status = "Janda / duda"
        self.customer.save()
        response = self.client.get(f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers)
        self.assertEqual("CERAI MATI", response.data['idCardData']['maritalStatus'])

    @patch("juloserver.qris.views.view_api_v1.get_prefilled_data")
    @patch("juloserver.qris.views.view_api_v1.update_linkage_status")
    def test_update_linkage_status_to_regis_form(
        self, mock_update_linkage_status, mock_get_prefilled_data
    ):
        self.qris_partner_linkage.status = QrisLinkageStatus.REQUESTED
        self.qris_partner_linkage.save()

        mock_get_prefilled_data.return_value = {}
        mock_update_linkage_status.return_value = True

        # call api
        headers = {'HTTP_PARTNERXID': self.partner_xid}
        response = self.client.get(
            f'/api/qris/v1/amar/prefilled-data/{self.to_partner_user_xid.hex}', **headers
        )

        self.assertEqual(response.status_code, 200)

        mock_get_prefilled_data.assert_called_once()
        mock_update_linkage_status.assert_called_once_with(
            linkage=self.qris_partner_linkage,
            to_status=QrisLinkageStatus.REGIS_FORM,
        )
