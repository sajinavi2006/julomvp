from future import standard_library

from juloserver.portal.object.dashboard.constants import JuloUserRoles

standard_library.install_aliases()
import json
from urllib.parse import urlencode
from django.test import TestCase
from django.test import Client
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.test import override_settings
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    GroupFactory,
    LoanFactory,
    CustomerFactory,
    PaymentMethodFactory,
    ApplicationFactory,
)

testing_middleware = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware',
    'juloserver.routing.middleware.CustomReplicationMiddleware']


@override_settings(MIDDLEWARE=testing_middleware)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestChangePaymentVisibility(TestCase):

    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        group = GroupFactory(name=JuloUserRoles.CHANGE_OF_PAYMENT_VISIBILITY)
        self.user.groups.add(group)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_dashboard_change_of_payment_visibility(self):
        response = self.client.get('/dashboard/change_of_payment_visibility')
        self.assertEqual(response.status_code, 200)

    def test_get_payment_methods(self):
        # wrong method
        response = self.client.post('/dashboard/get_payment_visibility_details/?appln_id=')
        self.assertEqual(response.status_code, 405)

        # invalid application id
        response = self.client.get('/dashboard/get_payment_visibility_details/?appln_id=')
        self.assertEqual(response.json()['data']['status'], 'failure')

        # application not found
        response = self.client.get('/dashboard/get_payment_visibility_details/?appln_id=99999999')
        self.assertEqual(response.json()['data']['status'], 'failure')

        # loan not found
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        response = self.client.get('/dashboard/get_payment_visibility_details/?appln_id=%s'
                                   % application.id)
        self.assertEqual(response.json()['data']['status'], 'failure')

        # payment method not found
        loan = LoanFactory(customer=customer, application=application)
        response = self.client.get('/dashboard/get_payment_visibility_details/?appln_id=%s'
                                   % application.id)
        self.assertEqual(response.json()['data']['status'], 'failure')

        # success case
        payment_method = PaymentMethodFactory(loan=loan)
        response = self.client.get('/dashboard/get_payment_visibility_details/?appln_id=%s'
                                   % loan.application.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']['payment_methods']), 1)
        self.assertEqual(response.json()['data']['payment_methods'][0]['id'], payment_method.id)

    def test_update_payment_method(self):
        # wrong method
        response = self.client.get('/dashboard/update_payments_visibility/')
        self.assertEqual(response.status_code, 405)

        # invalid payment method id
        data = urlencode({
            "payment_methods": json.dumps([{"id": 9999999999, "is_shown": True}])
        })
        response = self.client.post(reverse('dashboard:update_payments_visibility'), data,
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.json()['data']['status'], 'failure')

        # application not found
        customer = CustomerFactory()
        loan = LoanFactory(customer=customer)
        payment_method = PaymentMethodFactory(loan=loan, customer=customer)
        data = urlencode({
            "payment_methods": json.dumps([{"id": payment_method.id, "is_shown": True}])
        })
        response = self.client.post('/dashboard/update_payments_visibility/', data,
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['status'], 'success')
        self.assertEqual(len(response.json()['data']['payment_methods']), 1)
        self.assertEqual(response.json()['data']['payment_methods'][0]['id'], payment_method.id)
