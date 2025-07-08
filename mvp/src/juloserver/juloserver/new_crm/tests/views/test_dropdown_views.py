from django.contrib.auth.models import Group
from django.core.urlresolvers import reverse
from factory import Iterator
from rest_framework.test import (
    APIClient,
    APITestCase,
)

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CityLookupFactory,
    DistrictLookupFactory,
    ProvinceLookupFactory,
    SubDistrictLookupFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestDropDownApi(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_job(self):
        url = '/new_crm/v1/dropdown/job/'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            "Pegawai negeri",
            "Pegawai swasta",
            "Pengusaha",
            "Freelance",
            "Staf rumah tangga",
            "Ibu rumah tangga",
            "Mahasiswa",
            "Tidak bekerja"
        ]
        self.assertEqual(expected_data, response.data['data'], str(response.content))

    def test_job_filter(self):
        url = '/new_crm/v1/dropdown/job/'
        response = self.client.get(url, {'level': 'Pegawai negeri,Pendidikan'})
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            "Dosen",
            "Guru",
            "Instruktur / Pembimbing Kursus",
            "Kepala Sekolah",
            "Tata Usaha",
            "Lainnya"
        ]
        self.assertEqual(expected_data, response.data['data'], str(response.content))

    def test_job_search(self):
        url = '/new_crm/v1/dropdown/job/'
        response = self.client.get(url, {'search': 'pegawai'})
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            "Pegawai negeri",
            "Pegawai swasta",
        ]
        self.assertEqual(expected_data, response.data['data'], str(response.content))


class DropdownAddressApi(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    @classmethod
    def setUpTestData(cls):
        provinces = ProvinceLookupFactory.create_batch(
            2,
            province=Iterator(['Aceh', 'Sumatera']),
        )
        cities = CityLookupFactory.create_batch(
            4,
            city=Iterator(['City 1', 'City 2', 'City 3', 'City 4']),
            province=Iterator(provinces)
        )
        districts = DistrictLookupFactory.create_batch(
            2,
            district=Iterator(['District 1', 'District 2']),
            city=cities[0]
        )
        SubDistrictLookupFactory.create_batch(
            2,
            sub_district=Iterator(['Sub District 1', 'Sub District 2']),
            zipcode=Iterator(['123456', '654321']),
            district=districts[0]
        )

    def test_get_province(self):
        url = '/new_crm/v1/dropdown/address/'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            'Aceh',
            'Sumatera',
        ]
        self.assertEqual(expected_data, list(response.data['data']), str(response.content))

    def test_get_city(self):
        url = '/new_crm/v1/dropdown/address/'
        response = self.client.get(url, {'province': 'Aceh'})
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            'City 1',
            'City 3',
        ]
        self.assertEqual(expected_data, list(response.data['data']), str(response.content))

    def test_get_district(self):
        url = '/new_crm/v1/dropdown/address/'
        response = self.client.get(url, {
            'province': 'Aceh',
            'city': 'City 1',
        })
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            'District 1',
            'District 2',
        ]
        self.assertEqual(expected_data, list(response.data['data']), str(response.content))

    def test_get_subdistrict(self):
        url = '/new_crm/v1/dropdown/address/'
        response = self.client.get(url, {
            'province': 'Aceh',
            'city': 'City 1',
            'district': 'District 1',
        })
        self.assertEqual(200, response.status_code, str(response.content))

        expected_data = [
            {'subDistrict': 'Sub District 1', 'zipcode': '123456'},
            {'subDistrict': 'Sub District 2', 'zipcode': '654321'},
        ]
        self.assertEqual(expected_data, response.data['data'], str(response.content))
