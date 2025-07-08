from mock import patch
from rest_framework.test import APIClient
from django.test import TestCase
from django.contrib.auth.hashers import make_password

from juloserver.julo.models import (
    AuthUser as User,
    Application,
    Customer,
    Device,
)
from juloserver.api_token.models import ExpiryToken
from juloserver.julo.tests.factories import (
    ProductLineFactory,
    WorkflowFactory,
    OnboardingFactory,
    OtpRequestFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
    OnboardingIdConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.pin.models import LoginAttempt


class TestRegisterVersion6(TestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()
        self.endpoint = '/api/registration-flow/v6/register'
        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'
        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0',
        }
        self.workflow_ios = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        OnboardingFactory(
            id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
            description='LongForm Shortened',
            status=True,
        )
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow_ios,
        )

    @patch('juloserver.registration_flow.services.v3.verify_email_token')
    def test_success_register_user_for_refresh_token(self, verify_email_token):
        data = {
            "android_id": "test-android-id",
            "email": "testemail9@julofinance.com",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "onboarding_id": 3,
            "pin": "159357",
            "username": "1598930506022615",
            "app_version": "8.11.1",
            "email_token": 'fake_token',
        }
        verify_email_token.return_value = True

        response = self.client_wo_auth.post(self.endpoint, data, format='json')
        self.assertTrue(response.status_code, 201)
        self.assertContains(response, "auth", 1)
        self.user = User.objects.get(username='1598930506022615')
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    def test_register_user_for_refresh_token_with_invalid_nik(self):

        data = {
            "android_id": "test-android-id",
            "email": "testemail9@julofinance.com",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "onboarding_id": 3,
            "pin": "159357",
            "username": "086689326159",
            "app_version": "8.11.1",
        }

        response = self.client_wo_auth.post(self.endpoint, data, format='json')
        self.assertTrue(response.status_code, 400)

    @patch('juloserver.registration_flow.services.v3.verify_email_token')
    def test_success_register_user_for_refresh_token_in_ios_device(self, verify_email_token):
        data = {
            "android_id": "",
            "email": "testemail9@julofinance.com",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "onboarding_id": 3,
            "pin": "159357",
            "username": "1598930506022615",
            "app_version": "8.11.1",
            "email_token": 'fake_token',
        }
        verify_email_token.return_value = True

        response = self.client_wo_auth.post(
            self.endpoint, data, format='json', **self.new_device_header
        )
        response_json = response.json()
        self.assertTrue(response.status_code, 201)
        self.assertContains(response, "auth", 1)
        self.user = User.objects.get(username='1598930506022615')
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)
        application_id = response_json['data']['applications'][0]['id']
        application = Application.objects.filter(pk=application_id).last()
        self.assertIsNotNone(application)
        self.assertEqual(application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.assertEqual(application.workflow.name, WorkflowConst.JULO_ONE_IOS)
        self.assertEqual(application.product_line_code, ProductLineCodes.J1)

    @patch('juloserver.otp.views.validate_otp')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    @patch('juloserver.registration_flow.services.v3.verify_email_token')
    def test_success_register_user_for_refresh_token_in_android_device(
        self,
        verify_email_token,
        mock_sms_validate_otp,
        mock_login_otp,
        mock_address_geolocation,
        mock_validate_otp,
    ):
        nik = "1598930506022615"
        plain_password = "159357"

        data = {
            "android_id": "TestAndroidDevice",
            "email": "testemail9@julofinance.com",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "onboarding_id": 3,
            "pin": plain_password,
            "username": nik,
            "app_version": "8.11.1",
            "email_token": 'fake_token',
        }
        verify_email_token.return_value = True

        response = self.client_wo_auth.post(
            self.endpoint,
            data,
            format='json',
        )
        self.assertTrue(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        self.user = User.objects.get(username=nik)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

        # Try to login in IOS Device
        # And should be automatically create application with JuloOneIOSWorkflow
        self.customer = Customer.objects.filter(pk=response.json()['data']['customer']['id']).last()
        self.otp_request = OtpRequestFactory(
            customer=self.customer,
            phone_number='08999999999',
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        otp_request_data = {
            "action_type": "login",
            "android_id": '12b56c4365a56d6c',
            "customer_xid": self.customer.customer_xid,
            "otp_token": self.otp_request.otp_token,
            "password": plain_password,
            "username": self.user.username,
        }

        mock_validate_otp.return_value = 'success', 'test'
        self.token = self.user.auth_expiry_token.key
        self.client_wo_auth.credentials(
            HTTP_AUTHORIZATION='Token ' + self.token, HTTP_TOKEN_VERSION=1.0
        )
        response = self.client_wo_auth.post('/api/otp/v2/validate', data=otp_request_data)

        # try to login
        app_version = '1.0.1'
        self.new_device_header.update({'HTTP_X_APP_VERSION': app_version})
        payload_login = {
            "android_id": "",
            "app_version": app_version,
            "gcm_reg_id": "9DftTH9u3kZf4fFcQY9cwthI",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "jstar_toggle": 1,
            'latitude': -6.175499,
            'longitude': 106.820512,
            "manufacturer": "iPhone",
            "model": "iPhone",
            "password": plain_password,
            "require_expire_session_token": True,
            "username": nik,
        }
        response = self.client_wo_auth.post(
            '/api/pin/v7/login',
            format='json',
            data=payload_login,
            **self.new_device_header,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEqual(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

        query_set = Application.objects.filter(customer_id=self.customer.id)
        self.assertEqual(query_set.count(), 1)
        application = query_set.last()
        self.assertTrue(application.is_julo_one_ios())
        self.assertEqual(application.app_version, app_version)
        self.assertEqual(application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.assertEqual(application.application_status_id, 100)

        device = Device.objects.filter(pk=response.json()['data']['device_id']).last()
        self.assertIsNotNone(device)
        self.assertEqual(device.ios_id, self.ios_id)

        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNotNone(login_attempt)
        self.assertEqual(login_attempt.ios_id, self.ios_id)
