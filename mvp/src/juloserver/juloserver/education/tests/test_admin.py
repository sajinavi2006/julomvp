from django.test import TestCase
from rest_framework.test import APIClient

from django.conf import settings
from django.core.urlresolvers import reverse

from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.education.tests.factories import SchoolFactory


class TestEducationAdmin(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)

    def test_upload_school_admin_page(self):
        res = self.client.get(reverse('admin:education_upload_school'), {})
        self.assertEqual(res.status_code, 200)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/excel/upload-test-file.xlsx', 'rb')
        res = self.client.post(reverse('admin:education_upload_school'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 302)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/excel/upload-zero.xlsx', 'rb')
        res = self.client.post(reverse('admin:education_upload_school'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 302)

        xls_file = open(str(settings.BASE_DIR) + '/misc_files/csv/upload-failed.csv', 'rb')
        res = self.client.post(reverse('admin:education_upload_school'), {'xls_file': xls_file})
        self.assertEqual(res.status_code, 200)
