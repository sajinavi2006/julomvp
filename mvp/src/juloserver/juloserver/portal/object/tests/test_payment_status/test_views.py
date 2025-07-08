from django.test import TestCase
from django.test import Client
from django.contrib.auth.models import User
from django.test import override_settings
from juloserver.account_payment.tests.factories import AccountPaymentFactory

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
class TestJuloOneUpdateRobocall(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)

    def test_method_not_allow(self):
        response = self.client.put('/payment_status/julo_one_update_robocall/',
                                   {'account_payment_id': 999999})
        self.assertEqual(response.status_code, 405)

    def test_payment_not_found(self):
        response = self.client.get('/payment_status/julo_one_update_robocall/?account_payment_id=999999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')

    def test_retrieve_validation_info_success(self):
        account_payment = AccountPaymentFactory()
        response = self.client.get('/payment_status/julo_one_update_robocall/?account_payment_id=%s' %
                                   account_payment.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(response.json()['message'], 'successfully updated')
        account_payment.refresh_from_db()
        self.assertEqual(account_payment.is_robocall_active, True)
