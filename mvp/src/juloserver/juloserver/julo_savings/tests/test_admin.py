from django.test import TestCase
import csv
import io

from django.contrib.auth.models import (
    Group,
)
from django.test import TestCase, RequestFactory
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo_savings.models import JuloSavingsMobileContentSetting
from juloserver.julo_savings.tests.factories import JuloSavingsMobileContentSettingFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles


# Create your tests here.
class TestUploadCsvJuloSavings(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.request_factory = RequestFactory()
        self.group = Group.objects.create(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.url = '/xgdfat82892ddn/julo_savings/julosavingswhitelistapplication/add-file/'

    @staticmethod
    def generate_csv_file():
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(['1', '138919'])
        return output

    def test_upload_julo_savings_csv(self):
        upload_file = self.generate_csv_file()
        upload_file.content_type = 'text/csv'
        post_data = {'csv_file': upload_file}
        response = self.client.post(self.url, post_data)

        self.assertEqual(response.status_code, 302)


class TestJuloSavingsMobileContent(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.request_factory = RequestFactory()
        self.group = Group.objects.create(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_insertion_of_julosavings_mobile_content_setting_from_factory(self):
        mobile_content = JuloSavingsMobileContentSettingFactory(
            content_name='Julo Savings TNC',
            description='Terms and Condition for Julo Savings Customer',
            content='abcdefg',
            parameters={'key': 'value'},
            is_active=True,
        )
        self.assertIsNotNone(mobile_content)

    def test_insertion_julosavings_mobile_content_setting_from_model(self):
        mobile_content = JuloSavingsMobileContentSetting.objects.create(
            content_name='Julo Savings TNC',
            description='Terms and Condition for Julo Savings Customer',
            content='abcdefg',
            parameters={'key': 'value'},
            is_active=True,
        )
        self.assertIsNotNone(mobile_content)
