from django import forms

from django.test import TestCase
from rest_framework.test import APIClient

from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from juloserver.julo.tests.factories import AuthUserFactory

from juloserver.healthcare.admin import HealthcarePlatformForm
from juloserver.healthcare.tests.factories import HealthcarePlatformFactory


class TestHealthcareAdmin(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)

    def test_upload_healthcare_admin_page(self):
        res = self.client.get(reverse('admin:healthcare_platform_upload'), {})
        self.assertEqual(res.status_code, 200)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/excel/upload-test-file.xlsx', 'rb')
        res = self.client.post(reverse('admin:healthcare_platform_upload'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 302)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/excel/upload-zero.xlsx', 'rb')
        res = self.client.post(reverse('admin:healthcare_platform_upload'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 302)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/csv/upload-failed.csv', 'rb')
        res = self.client.post(reverse('admin:healthcare_platform_upload'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 200)

        res = self.client.post(reverse('admin:healthcare_platform_upload'), {'xls_file': None})
        self.assertEqual(res.status_code, 200)

    def test_healthcare_form(self):
        HealthcarePlatformFactory(name='sma 1', city='bandung')
        xls_file = open(str(settings.BASE_DIR) + '/misc_files/excel/upload-test-file.xlsx', 'rb')
        file_dict = {'xls_file': SimpleUploadedFile(xls_file.name, xls_file.read())}
        form = HealthcarePlatformForm(data=file_dict)
        self.assertEqual(form.full_clean(), None)
