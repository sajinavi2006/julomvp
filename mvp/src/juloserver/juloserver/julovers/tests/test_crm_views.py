import csv
import io

from django.contrib.auth.models import (
    Group,
)
from django.core.urlresolvers import reverse
from django.test import TestCase, RequestFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

PACKAGE_NAME = 'juloserver.julovers.views.crm_views'


class TestJuloversHistory(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_get_history(self):
        url = reverse('julovers.crm:upload_history')
        with self.assertTemplateUsed('julovers/upload_history.html'):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    def test_get_not_julovers_role(self):
        url = reverse('julovers.crm:upload_history')
        user = AuthUserFactory()
        group = Group.objects.create(name=JuloUserRoles.BO_FULL)
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)


class TestUploadJulovers(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.request_factory = RequestFactory()
        self.group = Group.objects.create(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.url = reverse('julovers.crm:upload_julovers_data')

    @staticmethod
    def generate_file():
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows([
            '3', 'Grady Richata', 'grady.richata@julofinance.com',
            'Bandung, road 123', '', '18/08/1980', '08123452889',
            'Pria', 'Lajang', 'Product', 'Group Product Manager', 'Pengawai swasta',
            '15/11/2021', 'BCA', '90248000', 'Grady Richata', '18/08/2022', '10,000,000',
            '1871023012910003'
        ])
        return output

    def test_upload_julovers(self):
        upload_file = self.generate_file()
        upload_file.content_type = 'text/csv'
        post_data = {
            'csv_file': upload_file
        }
        response = self.client.post(self.url, post_data)

        self.assertEqual(response.status_code, 302)  # 302 redirect http response
