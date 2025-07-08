from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from juloserver.bpjs.tests.factories import (
    SdBpjsProfileScrapeFactory,
    SdBpjsCompanyScrapeFactory,
    BpjsApiLogFactory,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
)
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestBPJSAndDukcapilInfoViews(APITestCase):
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
            address_detail="kalideres",
            name_in_bank="haidyan",
        )
        self.dukcapil_response = DukcapilResponseFactory(
            application=self.application,
            name=False,
            gender=False,
            birthdate=False,
            birthplace=False,
            address_street=False,
            address_kabupaten=True,
        )
        self.bpjs_profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, real_name="John Doe"
        )
        self.bpjs_company = SdBpjsCompanyScrapeFactory(profile=self.bpjs_profile)
        self.bpjs_api_log = BpjsApiLogFactory(
            application=self.application,
            service_provider='bpjs_direct',
            response="{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}",
        )

    def test_get_bpjs_and_dukcapil_info(self):
        # arrange
        url = '/api/fraud-portal/bpjs-dukcapil-info/?application_id=77777'
        expected_response = {
            'success': True,
            'data': {
                'bpjs_brick_info_list': [
                    {
                        'application_id': 77777,
                        'real_name': 'John Doe',
                        'identity_number': '12313131132',
                        'dob': '19-04-1986',
                        'birth_place': None,
                        'gender': 'Laki-laki',
                        'status_sipil': None,
                        'address': 'Jalan. xxxxxx',
                        'provinsi': None,
                        'kabupaten': None,
                        'kecamatan': None,
                        'kelurahan': None,
                        'phone': '+62891283131',
                        'email': None,
                        'total_balance': '4556700',
                        'company_name': 'PT. XYZ',
                        'range_upah': None,
                        'current_salary': "7000000",
                        'blth_upah': None,
                        'last_payment_date': '19-04-2022',
                        'status_pekerjaan': 'Aktif',
                        'employment_month_duration': '2',
                        'paket': None,
                        'bpjs_type': 'bpjs-tk',
                        'bpjs_cards': '{"number": "019238","balance": "4556700"}',
                    }
                ],
                'bpjs_direct_info_list': [
                    {
                        'application_id': 77777,
                        'namaLengkap': 'SESUAI',
                        'nomorIdentitas': 'SESUAI',
                        'tglLahir': 'SESUAI',
                        'jenisKelamin': 'SESUAI',
                        'handphone': 'SESUAI',
                        'email': 'SESUAI',
                        'namaPerusahaan': 'SESUAI',
                        'paket': 'SESUAI',
                        'upahRange': 'SESUAI',
                        'blthUpah': 'SESUAI',
                    }
                ],
                'ducakpil_list': [
                    {
                        'application_id': 77777,
                        'name': False,
                        'birthdate': False,
                        'birthplace': False,
                        'gender': False,
                        'marital_status': None,
                        'address_kabupaten': True,
                        'address_kecamatan': None,
                        'address_kelurahan': None,
                        'address_provinsi': None,
                        'address_street': False,
                        'job_type': None,
                    }
                ],
            },
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        self.assertEqual(expected_response, response_json)

    def test_get_bpjs_and_dukcapil_info_but_400_error_for_bpjs_direct(self):
        # arrange
        self.application_2 = ApplicationFactory(
            id=888888,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_detail="kalideres",
            name_in_bank="haidyan",
        )
        self.dukcapil_response_2 = DukcapilResponseFactory(
            application=self.application_2,
            name=False,
            gender=False,
            birthdate=False,
            birthplace=False,
            address_street=False,
            address_kabupaten=True,
        )
        self.bpjs_profile_2 = SdBpjsProfileScrapeFactory(
            application_id=self.application_2.id, real_name="John Doe"
        )
        self.bpjs_company = SdBpjsCompanyScrapeFactory(profile=self.bpjs_profile_2)
        self.bpjs_api_log = BpjsApiLogFactory(
            application=self.application_2,
            service_provider='bpjs_direct',
            http_status_code=400,
            response="{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}",
        )
        url = '/api/fraud-portal/bpjs-dukcapil-info/?application_id=888888'
        expected_response = {
            'success': True,
            'data': {
                'bpjs_brick_info_list': [
                    {
                        'application_id': 888888,
                        'real_name': 'John Doe',
                        'identity_number': '12313131132',
                        'dob': '19-04-1986',
                        'birth_place': None,
                        'gender': 'Laki-laki',
                        'status_sipil': None,
                        'address': 'Jalan. xxxxxx',
                        'provinsi': None,
                        'kabupaten': None,
                        'kecamatan': None,
                        'kelurahan': None,
                        'phone': '+62891283131',
                        'email': None,
                        'total_balance': '4556700',
                        'company_name': 'PT. XYZ',
                        'range_upah': None,
                        'current_salary': "7000000",
                        'blth_upah': None,
                        'last_payment_date': '19-04-2022',
                        'status_pekerjaan': 'Aktif',
                        'employment_month_duration': '2',
                        'paket': None,
                        'bpjs_type': 'bpjs-tk',
                        'bpjs_cards': '{"number": "019238","balance": "4556700"}',
                    }
                ],
                'bpjs_direct_info_list': [
                    {
                        'application_id': 888888,
                        'namaLengkap': None,
                        'nomorIdentitas': None,
                        'tglLahir': None,
                        'jenisKelamin': None,
                        'handphone': None,
                        'email': None,
                        'namaPerusahaan': None,
                        'paket': None,
                        'upahRange': None,
                        'blthUpah': None,
                    }
                ],
                'ducakpil_list': [
                    {
                        'application_id': 888888,
                        'name': False,
                        'birthdate': False,
                        'birthplace': False,
                        'gender': False,
                        'marital_status': None,
                        'address_kabupaten': True,
                        'address_kecamatan': None,
                        'address_kelurahan': None,
                        'address_provinsi': None,
                        'address_street': False,
                        'job_type': None,
                    }
                ],
            },
            'errors': [],
        }
        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        self.assertEqual(expected_response, response_json)

    def test_get_bpjs_and_dukcapil_info_without_bpjs_profile(self):
        # arrange
        self.application_3 = ApplicationFactory(
            id=1111111,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_detail="kalideres",
            name_in_bank="haidyan",
        )
        self.dukcapil_response_3 = DukcapilResponseFactory(
            application=self.application_3,
            name=False,
            gender=False,
            birthdate=False,
            birthplace=False,
            address_street=False,
            address_kabupaten=True,
        )
        self.bpjs_api_log = BpjsApiLogFactory(
            application=self.application_3,
            service_provider='bpjs_direct',
            http_status_code=200,
            response="{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}",
        )
        url = '/api/fraud-portal/bpjs-dukcapil-info/?application_id=1111111'
        expected_response = {
            'success': True,
            'data': {
                'bpjs_brick_info_list': [
                    {
                        'application_id': 1111111,
                        'real_name': None,
                        'identity_number': None,
                        'dob': None,
                        'birth_place': None,
                        'gender': None,
                        'status_sipil': None,
                        'address': None,
                        'provinsi': None,
                        'kabupaten': None,
                        'kecamatan': None,
                        'kelurahan': None,
                        'phone': None,
                        'email': None,
                        'total_balance': None,
                        'company_name': None,
                        'range_upah': None,
                        'current_salary': None,
                        'blth_upah': None,
                        'last_payment_date': None,
                        'status_pekerjaan': None,
                        'employment_month_duration': None,
                        'paket': None,
                        'bpjs_type': None,
                        'bpjs_cards': None,
                    }
                ],
                'bpjs_direct_info_list': [
                    {
                        'application_id': 1111111,
                        'namaLengkap': 'SESUAI',
                        'nomorIdentitas': 'SESUAI',
                        'tglLahir': 'SESUAI',
                        'jenisKelamin': 'SESUAI',
                        'handphone': 'SESUAI',
                        'email': 'SESUAI',
                        'namaPerusahaan': 'SESUAI',
                        'paket': 'SESUAI',
                        'upahRange': 'SESUAI',
                        'blthUpah': 'SESUAI',
                    }
                ],
                'ducakpil_list': [
                    {
                        'application_id': 1111111,
                        'name': False,
                        'birthdate': False,
                        'birthplace': False,
                        'gender': False,
                        'marital_status': None,
                        'address_kabupaten': True,
                        'address_kecamatan': None,
                        'address_kelurahan': None,
                        'address_provinsi': None,
                        'address_street': False,
                        'job_type': None,
                    }
                ],
            },
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        self.assertEqual(expected_response, response_json)

    def test_get_bpjs_and_dukcapil_info_without_bpjs_company(self):
        # arrange
        self.application_2 = ApplicationFactory(
            id=888888,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_detail="kalideres",
            name_in_bank="haidyan",
        )
        self.dukcapil_response_2 = DukcapilResponseFactory(
            application=self.application_2,
            name=False,
            gender=False,
            birthdate=False,
            birthplace=False,
            address_street=False,
            address_kabupaten=True,
        )
        self.bpjs_profile_2 = SdBpjsProfileScrapeFactory(
            application_id=self.application_2.id, real_name="John Doe"
        )
        self.bpjs_api_log = BpjsApiLogFactory(
            application=self.application_2,
            service_provider='bpjs_direct',
            http_status_code=400,
            response="{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}",
        )
        url = '/api/fraud-portal/bpjs-dukcapil-info/?application_id=888888'
        expected_response = {
            'success': True,
            'data': {
                'bpjs_brick_info_list': [
                    {
                        'application_id': 888888,
                        'real_name': 'John Doe',
                        'identity_number': '12313131132',
                        'dob': '19-04-1986',
                        'birth_place': None,
                        'gender': 'Laki-laki',
                        'status_sipil': None,
                        'address': 'Jalan. xxxxxx',
                        'provinsi': None,
                        'kabupaten': None,
                        'kecamatan': None,
                        'kelurahan': None,
                        'phone': '+62891283131',
                        'email': None,
                        'total_balance': '4556700',
                        'company_name': None,
                        'range_upah': None,
                        'current_salary': None,
                        'blth_upah': None,
                        'last_payment_date': None,
                        'status_pekerjaan': None,
                        'employment_month_duration': None,
                        'paket': None,
                        'bpjs_type': 'bpjs-tk',
                        'bpjs_cards': '{"number": "019238","balance": "4556700"}',
                    }
                ],
                'bpjs_direct_info_list': [
                    {
                        'application_id': 888888,
                        'namaLengkap': None,
                        'nomorIdentitas': None,
                        'tglLahir': None,
                        'jenisKelamin': None,
                        'handphone': None,
                        'email': None,
                        'namaPerusahaan': None,
                        'paket': None,
                        'upahRange': None,
                        'blthUpah': None,
                    }
                ],
                'ducakpil_list': [
                    {
                        'application_id': 888888,
                        'name': False,
                        'birthdate': False,
                        'birthplace': False,
                        'gender': False,
                        'marital_status': None,
                        'address_kabupaten': True,
                        'address_kecamatan': None,
                        'address_kelurahan': None,
                        'address_provinsi': None,
                        'address_street': False,
                        'job_type': None,
                    }
                ],
            },
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        self.assertEqual(expected_response, response_json)

    def test_get_bpjs_and_dukcapil_info_without_ducakpil_info(self):
        # arrange
        self.application_2 = ApplicationFactory(
            id=888888,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_detail="kalideres",
            name_in_bank="haidyan",
        )
        self.bpjs_profile_2 = SdBpjsProfileScrapeFactory(
            application_id=self.application_2.id, real_name="John Doe"
        )
        self.bpjs_api_log = BpjsApiLogFactory(
            application=self.application_2,
            service_provider='bpjs_direct',
            http_status_code=400,
            response="{'ret': '0', 'msg': 'Sukses', 'score': {'namaLengkap': 'SESUAI', 'nomorIdentitas': 'SESUAI', 'tglLahir': 'SESUAI', 'jenisKelamin': 'SESUAI', 'handphone': 'SESUAI', 'email': 'SESUAI', 'namaPerusahaan': 'SESUAI', 'paket': 'SESUAI', 'upahRange': 'SESUAI', 'blthUpah': 'SESUAI'}, 'CHECK_ID': '22111000575686'}",
        )
        url = '/api/fraud-portal/bpjs-dukcapil-info/?application_id=888888'
        expected_response = {
            'success': True,
            'data': {
                'bpjs_brick_info_list': [
                    {
                        'application_id': 888888,
                        'real_name': 'John Doe',
                        'identity_number': '12313131132',
                        'dob': '19-04-1986',
                        'birth_place': None,
                        'gender': 'Laki-laki',
                        'status_sipil': None,
                        'address': 'Jalan. xxxxxx',
                        'provinsi': None,
                        'kabupaten': None,
                        'kecamatan': None,
                        'kelurahan': None,
                        'phone': '+62891283131',
                        'email': None,
                        'total_balance': '4556700',
                        'company_name': None,
                        'range_upah': None,
                        'current_salary': None,
                        'blth_upah': None,
                        'last_payment_date': None,
                        'status_pekerjaan': None,
                        'employment_month_duration': None,
                        'paket': None,
                        'bpjs_type': 'bpjs-tk',
                        'bpjs_cards': '{"number": "019238","balance": "4556700"}',
                    }
                ],
                'bpjs_direct_info_list': [
                    {
                        'application_id': 888888,
                        'namaLengkap': None,
                        'nomorIdentitas': None,
                        'tglLahir': None,
                        'jenisKelamin': None,
                        'handphone': None,
                        'email': None,
                        'namaPerusahaan': None,
                        'paket': None,
                        'upahRange': None,
                        'blthUpah': None,
                    }
                ],
                'ducakpil_list': [
                    {
                        'application_id': 888888,
                        'name': None,
                        'birthdate': None,
                        'birthplace': None,
                        'gender': None,
                        'marital_status': None,
                        'address_kabupaten': None,
                        'address_kecamatan': None,
                        'address_kelurahan': None,
                        'address_provinsi': None,
                        'address_street': None,
                        'job_type': None,
                    }
                ],
            },
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        response_json = response.json()
        self.assertEqual(expected_response, response_json)
