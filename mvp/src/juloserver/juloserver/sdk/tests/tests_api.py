import time
from builtins import object, str
import mock
from mock.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.apiv2.models import PdPartnerModelResult
from juloserver.julo.models import AddressGeolocation, Application, Customer
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (ApplicationFactory,
                                             AuthUserFactory, CustomerFactory,
                                             PartnerFactory,
                                             StatusLookupFactory)
from juloserver.sdk.constants import PARTNER_PEDE
from juloserver.sdk.services import get_credit_score_partner, get_partner_score


class JuloAPITestCase(APITestCase):

    client = APIClient()
    @mock.patch('juloserver.apiv1.views.send_email_verification_email')
    def setUp(self, mock_send_email_verification_email):
        self.agent1 = "agent1"
        self.group= Group.objects.get_or_create(name=self.agent1)

        url = '/api/v1/rest-auth/registration/'
        data = {
            'email': 'hans+test_%s@julofinance.com' % time.time(),
            'password1': '1234567',
            'password2': '1234567'
        }
        response = self.client.post(url, data, format='json')
        user = User.objects.get(email=data['email'])
        permission = Permission.objects.get(codename='add_agent')
        user.user_permissions.add(permission)
        token = response.data['token']
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @mock.patch('juloserver.apiv1.tasks.send_email_verification_email')
    @mock.patch('collectioncrm.authserver.api.requests.post')
    def test_agent_create(self, mock_data, mock_send_email_verification_email):

        mock_data.return_value.ok = True
        role_url = '/api/v1/agents/roles'
        roles = self.client.get(role_url, format='json')
        url = '/api/v1/agents/'
        data = {
            'name': "name",
            'password': "password",
            "user":"julo@julofinance.com",
            "role":self.group[0].pk
        }
        result = self.client.post(url, data, format='json')
        self.assertEqual(200, result.status_code)


class TestSdkImageListCreateView(APITestCase):
    def create_user(self):
        user = AuthUserFactory(username='test')
        self.client.force_authenticate(user)
        partner = PartnerFactory(user=user, name=PARTNER_PEDE)
        return user, partner

    @mock.patch('juloserver.sdk.views.upload_image')
    def test_image_post(self, mock_upload_image):
        data = dict(upload=open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
                    image_type='Selfie')
        user, partner = self.create_user()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(customer=customer, application_xid=99999999)
        url = '/api/sdk/v1/applications/' + str(application.application_xid) + '/images/'
        self.client.force_authenticate(user)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = dict(upload=open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
                    image_type='KTP')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestGetPartnerScore(APITestCase):
    def create_user(self):
        user = AuthUserFactory(username='test')
        self.client.force_authenticate(user)
        partner = PartnerFactory(user=user, name=PARTNER_PEDE)
        return user, partner

    def setUp(self):
        self.pgood = 0.94848285729175
        self.user, self.partner = self.create_user()
        self.customer = CustomerFactory(user=self.user)
        self.status_lookup = StatusLookupFactory()
        self.status_lookup.status_code = 141
        self.status_lookup.save()
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status = self.status_lookup
        self.application.partner = self.partner
        self.application.save()

    def test_get_partner_score_with_pgood(self):
        credit_score = get_partner_score(self.pgood, self.partner)
        self.assertIn(credit_score[0], ['A-','B+','B-','C'])

    def test_get_credit_score_partner(self):
        class MockPdPartnerModelResult(object):
            id = 1
            application_id = 1
            customer_id = 1
            probability_fpd = 0.91
            pgood = 0.91
            version = 13

            def filter(self, application_id=None):
                return MockPdPartnerModelResult()

            def last(self):
                return MockPdPartnerModelResult()

        with mock.patch.object(PdPartnerModelResult.objects, 'filter',
                               return_value=MockPdPartnerModelResult()):
            credit_score = get_credit_score_partner(self.application.id)
            self.assertIn(credit_score.score, ['A-','B+','B-','C'])


class TestPartnerRegisterUser(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name=PARTNER_PEDE)
        self.client.force_authenticate(self.user)

    def generate_post_data(self):
        return {
            'email': 'dummy@email.com',
            'ktp': '1234561212120002',
            'app_version': '5.15.0',
            'gcm_reg_id': 'gcm-reg-id',
            'android_id': 'android-id',
            'latitude': '6.12',
            'longitude': '12.6',
            'imei': 'test-imei'
        }

    @patch('juloserver.sdk.views.create_application_checklist_async.delay')
    @patch('juloserver.sdk.views.generate_address_from_geolocation_async.delay')
    @patch('juloserver.sdk.views.process_application_status_change')
    @patch('juloserver.sdk.views.update_customer_data')
    def test_post_simple(self, mock_update_customer_data, mock_process_application_status_change,
            mock_generate_address_from_geolocation_async, mock_create_application_checklist_async):
        post_data = self.generate_post_data()
        response = self.client.post('/api/sdk/v1/authentication/', post_data)

        # Check expected response status
        self.assertEqual(201, response.status_code, response.content)

        # Check expected data in DB
        res_user = User.objects.filter(username=post_data.get('ktp')).last()
        res_customer = Customer.objects.filter(email=post_data.get('email')).last()
        res_application = Application.objects.filter(email=post_data.get('email'), customer_id=res_customer.id).last()
        res_geolocation = AddressGeolocation.objects.filter(application_id=res_application.id).last()
        self.assertIsNotNone(res_user)
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)
        self.assertIsNotNone(res_geolocation)

        # Check expected response data
        self.assertEqual(post_data['email'], response.json()['customer']['email'])
        self.assertEqual(post_data['ktp'], response.json()['applications'][0]['ktp'])

        # Check expeced mock function called
        mock_update_customer_data.assert_called_once_with(res_application)
        mock_process_application_status_change.assert_called_once_with(res_application.id,
                                                                       ApplicationStatusCodes.FORM_CREATED,
                                                                       change_reason='customer_triggered')
        mock_generate_address_from_geolocation_async.assert_called_once_with(res_geolocation.id)
        mock_create_application_checklist_async.assert_called_once_with(res_application.id)

    @patch('juloserver.sdk.views.create_application_checklist_async.delay')
    @patch('juloserver.sdk.views.generate_address_from_geolocation_async.delay')
    @patch('juloserver.sdk.views.process_application_status_change')
    @patch('juloserver.sdk.views.update_customer_data')
    def test_post_uppercase_email(self, *args):
        expectedEmail = 'email@testing.com'
        post_data = self.generate_post_data()
        post_data['email'] = ' EmaIL@testING.COm '
        response = self.client.post('/api/sdk/v1/authentication/', post_data)

        # Check expected response status
        self.assertEqual(201, response.status_code, response.content)

        # Check expected data in DB
        res_customer = Customer.objects.filter(email__iexact=expectedEmail).last()
        res_application = Application.objects.filter(email__iexact=expectedEmail).last()
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)
        self.assertEqual(expectedEmail, res_customer.email)
        self.assertEqual(expectedEmail, res_application.email)
