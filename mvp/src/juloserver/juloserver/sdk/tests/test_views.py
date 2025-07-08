from juloserver.julo.tests.factories import AppVersionFactory, ApplicationFactory, CustomerFactory
from juloserver.sdk.views import PartnerApplicationView
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from django.test.testcases import TestCase
from juloserver.apiv2.tests.test_apiv2_services import AuthUserFactory

class TestPartnerApplicationView(TestCase):
    def setUp(self):
        super().setUp()
        AppVersionFactory(status='latest')
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_authenticate(self.user)
        self.application_xid = 1234567890
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=self.application_xid)


    def generate_app_data(self):
        return {
            'bank_name': 'bank name',
            'bank_account_number': 123456789,
            'name_in_bank': 'name in bank'
        }

    def test_perform_update_email_uppercase(self):
        data = self.generate_app_data()
        data['email'] = 'EmAil@TestING.com'

        url = '/api/sdk/v1/applications/{}/'.format(self.application_xid)
        response = self.client.patch(url, data, format='json')
        self.application.refresh_from_db()
        self.customer.refresh_from_db()

        expected_email = 'email@testing.com'
        self.assertEqual(200, response.status_code, response.json())
        self.assertEqual(expected_email, self.application.email)
        self.assertEqual(expected_email, self.customer.email)
        self.assertEqual(expected_email, response.json()['email'])
