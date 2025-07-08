import json
from builtins import object
from urllib.parse import urlencode
import pytest

import mock
from django.test import TestCase, override_settings
from faker import Faker
from mock import ANY, patch
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

import juloserver.registration_flow.services.v1
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.models import (
    Device,
    DeviceGeolocation,
    Customer,
)

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    OtpRequestFactory,
    ProductLineFactory,
    WorkflowFactory,
    OnboardingFactory,
    FeatureSettingFactory,
)
from juloserver.partnership.constants import ErrorMessageConst
from django.utils import timezone
from datetime import timedelta
from juloserver.pin.tests.factories import TemporarySessionFactory
from juloserver.julo.constants import FeatureNameConst, ExperimentConst, IdentifierKeyHeaderAPI
from juloserver.registration_flow.services.v1 import do_encrypt_or_decrypt_sync_register
from juloserver.pin.models import CustomerPin, RegisterAttemptLog
from juloserver.julo.tests.factories import ExperimentSettingFactory
from juloserver.account.models import ExperimentGroup


def fake_send_task(task_name, param, **kargs):
    eval(task_name)(*param)


fake = Faker()
fake.add_provider(JuloFakerProvider)


class PhoneNumberApiClient(APIClient):
    def check_phone_number(self, phone):
        url = '/api/registration-flow/v1/check'
        data = {'phone': phone}
        return self.post(url, data, format='json')

    def vaildate_nik_email(self, username):
        url = '/api/registration-flow/v1/validate'
        data = {'username': username}
        return self.post(url, data, format='json')

    def generate_customer(self, phone):
        url = '/api/registration-flow/v1/generate-customer'
        data = {'phone': phone}
        return self.post(url, data, format='json')

    def register(self, data):
        url = '/api/registration-flow/v1/register'
        return self.post(url, data, format='json')

    def _mock_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp


class PhoneNumberApi(APITestCase):
    client_class = PhoneNumberApiClient

    def setUp(self):
        WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        ProductLineFactory(product_line_code=1)
        self.payload = {
            "android_id": "c32d6eee0040052a",
            "gcm_reg_id": "DEFAULT_GCM_ID",
            "is_rooted_device": False,
            "is_suspicious_ip": False,
            "latitude": -6.9287081,
            "longitude": 107.6250815,
            "manufacturer": "docomo",
            "model": "SO-02J",
            "pin": "091391",
            "app_version": "7.3.0",
        }

        # Set onboarding factory
        OnboardingFactory(id=1, description='Longform', status=True)
        OnboardingFactory(id=2, description='Shortform', status=True)

    def test_phone_invalid(self):
        phone = '628889991010'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

        phone = '088899917,11'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_phone_valid_registered(self):
        phone = '088889991010'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_phone_valid_unregistered(self):
        phone = '08812345678'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_valid_generate_customer(self):
        phone = '08812345678'
        response = self.client.generate_customer(phone)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.julo.services.process_application_status_change')
    def test_register_with_onboarding(self, mocking_1, mocking_2, mocking_3):
        """
        Test case phone number with onboarding_id
        """

        phone = "088889991010"
        self.payload['onboarding_id'] = 2
        self.payload['phone'] = phone
        self.client.generate_customer(phone)

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        # for case otp require verification when registration flow
        self.otp_request = OtpRequestFactory(
            customer=customer,
            phone_number=phone,
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        now = timezone.localtime(timezone.now())
        expire_time = now + timedelta(minutes=15)
        TemporarySessionFactory(
            user=customer.user,
            expire_at=expire_time,
            is_locked=False,
            otp_request=self.otp_request,
        )
        response = self.client.register(self.payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.julo.services.process_application_status_change')
    def test_register_with_onboarding_false(self, mocking_1, mocking_2, mocking_3):
        """
        Test case phone number with onboarding_id
        """

        phone = "08113213131"
        self.payload['onboarding_id'] = 1
        self.payload['phone'] = phone
        self.client.generate_customer(phone)
        response = self.client.register(self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_generate_customer(self):
        phone = '08812345'
        result = self.client.generate_customer(phone)
        print(result.status_code, result.json())
        self.assertEqual(result.status_code, 400)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.registration_flow.services.v1.process_register_phone_number')
    def test_register_with_app_version_check(
        self, mock_registration, mocking_1, mocking_2, mocking_3
    ):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

        phone = "088889991010"
        self.payload['onboarding_id'] = 2
        self.payload['phone'] = phone
        self.client.generate_customer(phone)

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        self.otp_request = OtpRequestFactory(
            customer=customer,
            phone_number=phone,
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        now = timezone.localtime(timezone.now())
        expire_time = now + timedelta(hours=1)
        TemporarySessionFactory(
            user=customer.user,
            expire_at=expire_time,
            is_locked=False,
            otp_request=self.otp_request,
        )

        mock_registration.return_value = {
            "token": 'test_token',
            "customer": 'test_customer',
            "applications": ['test_applications'],
            "partner": 'test_partner',
            "device_id": 'test_device_id',
        }

        # app version lower than minimum
        self.app_version = '7.21.1'
        response = self.client.post(
            '/api/registration-flow/v1/register',
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # app version higher than minimum
        self.app_version = '8.21.1'
        response = self.client.post(
            '/api/registration-flow/v1/register',
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.registration_flow.services.v1.process_register_phone_number')
    def test_register_with_app_version_check_invalid_parameter(
        self, mock_registration, mocking_1, mocking_2, mocking_3
    ):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

        phone = "088889991010"
        self.payload['onboarding_id'] = 2
        self.payload['phone'] = phone
        self.client.generate_customer(phone)

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        self.otp_request = OtpRequestFactory(
            customer=customer,
            phone_number=phone,
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        now = timezone.localtime(timezone.now())
        expire_time = now + timedelta(hours=1)
        TemporarySessionFactory(
            user=customer.user,
            expire_at=expire_time,
            is_locked=False,
            otp_request=self.otp_request,
        )

        mock_registration.return_value = {
            "token": 'test_token',
            "customer": 'test_customer',
            "applications": ['test_applications'],
            "partner": 'test_partner',
            "device_id": 'test_device_id',
        }

        # parameters are invalid, registration should run as normal
        self.app_version = '7.21.1'
        self.fs.parameters = {
            'app_minimum_version': '8.x.a',
            'error_message': 'This is the error message',
        }
        self.fs.save()

        response = self.client.post(
            '/api/registration-flow/v1/register',
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.registration_flow.services.v1.process_register_phone_number')
    def test_register_with_app_version_check_setting_off(
        self, mock_registration, mocking_1, mocking_2, mocking_3
    ):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

        phone = "088889991010"
        self.payload['onboarding_id'] = 2
        self.payload['phone'] = phone
        self.client.generate_customer(phone)

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        self.otp_request = OtpRequestFactory(
            customer=customer,
            phone_number=phone,
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        now = timezone.localtime(timezone.now())
        expire_time = now + timedelta(hours=1)
        TemporarySessionFactory(
            user=customer.user,
            expire_at=expire_time,
            is_locked=False,
            otp_request=self.otp_request,
        )

        mock_registration.return_value = {
            "token": 'test_token',
            "customer": 'test_customer',
            "applications": ['test_applications'],
            "partner": 'test_partner',
            "device_id": 'test_device_id',
        }

        # feature settings is off, registration should as normal
        self.app_version = '7.21.1'
        self.fs.is_active = False
        self.fs.parameters = {
            'app_minimum_version': '8.21.1',
            'error_message': 'This is the error message',
        }
        self.fs.save()

        response = self.client.post(
            '/api/registration-flow/v1/register',
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestValidateNikEmail(APITestCase):
    def setUp(self):
        self.client = PhoneNumberApiClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.nik = "1111110101900003"
        self.customer.phone = "08812345678"
        self.customer.save()

    def test_validate_nik(self):
        username = self.customer.nik
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        username = self.customer.nik[:-1] + "9"
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_validate_email(self):
        username = self.customer.email
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        username = self.customer.email[:-1] + "0"
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_deleted_user(self):
        self.customer.is_active = False
        self.customer.save()
        username = self.customer.nik
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.data.get('errors'), [ErrorMessageConst.CONTACT_CS_JULO])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

        username = self.customer.email
        response = self.client.vaildate_nik_email(username)
        self.assertEqual(response.data.get('errors'), [ErrorMessageConst.CONTACT_CS_JULO])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)


class TestPopulateData(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.content_type = "application/x-www-form-urlencoded"
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.endpoint = "/api/registration-flow/v1/prepopulate-form"
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    def test_populate_data_application_notfound(self):
        """
        Test populate data if condition application is None.
        """

        payload_data = {"application_id": None}
        response = self.client.post(self.endpoint, payload_data, content_type=self.content_type)
        response_error_message = response.json()["errors"]
        self.assertEqual(["Param is empty."], response_error_message)

    def test_populate_data_app_id(self):
        """
        Test Application id
        """
        self.application.partner_id = 9
        self.application.save()
        payload_data = urlencode({"application_id": str(self.application.id)})
        with self.assertRaises(Exception) as e:
            self.client.post(self.endpoint, payload_data, content_type=self.content_type)
        self.assertTrue(str(e), "")


@override_settings(GOOGLE_AUTH_CLIENT_ID='gggggggggggggggggggggggggg')
class TestPreRegister(APITestCase):
    PRE_REGISTER_URL = '/api/registration-flow/v1/pre-register-check'

    def setUp(self):
        self.client_wo_auth = APIClient()

        # payload to send pre-registration data
        self.payload = {
            'nik': '1111123219324444',
            'email': 'captainmarvel@gmail.com',
            'android_id': '23956476584765',
            'google_auth_access_token': 'sdfsdf',
            'app_name': 'android',
        }

        self.google_auth_id_info_response = {
            'iss': 'https://accounts.google.com',
            'azp': 'pd7plqvtd9e5t8mtuke.apps.googleusercontent.com',
            'aud': '930pd7plqvtd9e5t8mtuke.apps.googleusercontent.com',
            'sub': '112329350075606479999',
            'email': 'captainmarvel@gmail.com',
            'email_verified': True,
            'at_hash': '-hduashdjqwh4oZ4eZYabrA',
            'name': 'tony stark',
            'picture': 'https://lh3.googleusercontent.com/dsdhyeuwuehwu7238213b321u32u321',
            'given_name': 'tony',
            'family_name': 'stark',
            'locale': 'vi',
            'iat': 1696251438,
            'exp': 1696255038,
        }

    @patch('juloserver.registration_flow.services.google_auth_services.id_token')
    def test_preregister_happy_case(self, mock_id_token):
        mock_id_token.verify_oauth2_token.return_value = self.google_auth_id_info_response
        response = self.client_wo_auth.post(self.PRE_REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.registration_flow.services.google_auth_services.id_token')
    def test_preregister_negative_case(self, mock_id_token):
        user = AuthUserFactory(username='1111123219324444')
        customer = CustomerFactory(
            user=user, nik='1111123219324445', email='captainmarvel@gmail.com'
        )
        self.payload['nik'] = '1111123219324444'
        mock_id_token.verify_oauth2_token.return_value = self.google_auth_id_info_response
        response = self.client_wo_auth.post(self.PRE_REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.payload.update(
            {
                'nik': '1111123219324446',
                'email': 'captainmarvel@gmail.com',
            }
        )
        response = self.client_wo_auth.post(self.PRE_REGISTER_URL, data=self.payload)

        self.payload.update(
            {
                'nik': '1111123219324447',
                'email': 'captainmarvel@gmail.com',
            }
        )
        response = self.client_wo_auth.post(self.PRE_REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, 423)

        self.payload['email'] = 'captainmarvel3@gmail.com'
        response = self.client_wo_auth.post(self.PRE_REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('juloserver.registration_flow.services.google_auth_services.id_token')
    def test_preregister_happy_case_with_ios(self, mock_id_token):
        mock_id_token.verify_oauth2_token.return_value = self.google_auth_id_info_response

        self.payload['android_id'] = ''
        self.payload['app_name'] = 'ios'

        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'
        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0.1',
        }

        response = self.client_wo_auth.post(
            self.PRE_REGISTER_URL, data=self.payload, **self.new_device_header
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        register_data = RegisterAttemptLog.objects.filter(email=self.payload['email']).last()
        self.assertEqual(register_data.ios_id, self.ios_id)
        self.assertIsNone(register_data.android_id)


class TestSyncRegister(TestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()
        self.endpoint = '/api/registration-flow/v1/sync-registration'
        self.latitude = 10.0540540540541
        self.longitude = 76.325242394343
        self.payload = {
            "android_id": "test-android-id",
            "gcm_reg_id": "hyvlU8ykJpKamiA_lNwQ",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "pin": None,
            "phone_number": "083822825720",
            "app_version": "8.11.1",
        }
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.SYNC_REGISTRATION_J360_SERVICES,
        )

    def test_success_register_user_for_refresh_token(self):

        pin = do_encrypt_or_decrypt_sync_register('012345', encrypt=True)
        self.payload['pin'] = pin

        response = self.client_wo_auth.post(self.endpoint, self.payload, format='json')
        response_json = response.json()
        customer_id = response_json['data']['customer']['id']
        customer = Customer.objects.filter(pk=customer_id).last()

        self.assertTrue(response.status_code, 201)
        self.assertIn('auth_user_id', response_json['data'])
        self.assertTrue(CustomerPin.objects.filter(user_id=customer.user_id).exists())
        self.assertTrue(ExperimentGroup.objects.filter(customer_id=customer.id).exists())
        device = Device.objects.filter(customer_id=customer_id).last()
        device_latlong = DeviceGeolocation.objects.filter(device=device).last()
        self.assertEqual(device_latlong.latitude, self.latitude)
        self.assertEqual(device_latlong.longitude, self.longitude)

        response = self.client_wo_auth.post(self.endpoint, self.payload, format='json')
        response_json = response.json()
        self.assertEqual(response_json['errors'][0], 'Data yang Anda masukkan telah terdaftar')

    def test_bad_request_register_user_for_refresh_token(self):

        pin = do_encrypt_or_decrypt_sync_register('112233', encrypt=True)
        self.payload['pin'] = pin
        response = self.client_wo_auth.post(self.endpoint, self.payload, format='json')
        self.assertTrue(response.status_code, 400)

    def test_bad_request_phone_number_register_user_for_refresh_token(self):

        pin = do_encrypt_or_decrypt_sync_register('012345', encrypt=True)
        self.payload['pin'] = pin
        self.payload['phone_number'] = '083'
        response = self.client_wo_auth.post(self.endpoint, self.payload, format='json')
        self.assertTrue(response.status_code, 400)
        self.assertTrue(response.json()['errors'][0], 'Phone number Tidak Valid')
