import mock
from mock import patch

from faker import Faker
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from django.test import TestCase

from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    MobileFeatureSettingFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.registration_flow.services.v2 import process_register_phone_number
from juloserver.pin.tests.factories import (
    TemporarySessionFactory,
    LoginAttemptFactory,
)
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.julo.constants import (
    ApplicationStatusCodes,
    FeatureNameConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.registration_flow.constants import ErrorMsgCrossDevices


class RegistrationClient(APIClient):
    def register(self, data):
        url = '/api/registration-flow/v2/register'
        return self.post(url, data, format='json')


class TestRegisterWithPhone(APITestCase):
    def setUp(self):
        self.client = RegistrationClient()

    @patch('juloserver.registration_flow.views.process_register_phone_number_v2')
    def test_missing_session_token(self, mock_process_register):
        data = {
            'phone': '0883231231231',
            'app_version': '2.2.2',
            'pin': '012355',
            'gcm_reg_id': '2312312321312',
            'android_id': 'testandroidid',
            'imei': 'fakeimeiid',
            'latitude': 20.0,
            'longitude': 10.0,
            'appsflyer_device_id': 999999,
            'advertising_id': 999999,
            'username': '0883231231231',
        }
        # not session_token
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        user = AuthUserFactory(username='0883231231231')
        mock_process_register.return_value = {}
        result = self.client.register(data=data)
        self.assertEqual(result.status_code, 400)
        # not user
        mock_process_register.return_value = {}
        data['session_token'] = 'dsadsadasd'
        data['username'] = 'fake_user'
        result = self.client.register(data=data)
        self.assertEqual(result.status_code, 401)

    @patch('juloserver.registration_flow.views.process_register_phone_number_v2')
    def test_success(self, mock_process_register):
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        user = AuthUserFactory(username='0883231231231')
        session_token = TemporarySessionFactory(user=user)
        data = {
            'phone': '0883231231231',
            'username': '0883231231231',
            'app_version': '2.2.2',
            'pin': '012355',
            'gcm_reg_id': '2312312321312',
            'android_id': 'testandroidid',
            'imei': 'fakeimeiid',
            'latitude': 20.0,
            'longitude': 10.0,
            'appsflyer_device_id': 999999,
            'advertising_id': 999999,
            'session_token': session_token.access_key,
        }
        mock_process_register.return_value = {}
        result = self.client.register(data=data)
        self.assertEqual(result.status_code, 201)
        session_token.refresh_from_db()
        self.assertEqual(session_token.is_locked, True)

    @patch('juloserver.registration_flow.views.process_register_phone_number_v2')
    def test_register_with_app_version_check(self, mock_process_register):
        mock_process_register.return_value = {}
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )


        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        user = AuthUserFactory(username='0883231231231')
        session_token = TemporarySessionFactory(user=user)
        data = {
            'phone': '0883231231231',
            'username': '0883231231231',
            'app_version': '2.2.2',
            'pin': '012355',
            'gcm_reg_id': '2312312321312',
            'android_id': 'testandroidid',
            'imei': 'fakeimeiid',
            'latitude': 20.0,
            'longitude': 10.0,
            'appsflyer_device_id': 999999,
            'advertising_id': 999999,
            'session_token': session_token.access_key,
        }

        # app version lower than minimum
        self.app_version = '7.21.1'
        response = self.client.post(
            '/api/registration-flow/v2/register',
            data=data,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # app version higher than minimum
        self.app_version = '8.21.1'
        response = self.client.post(
            '/api/registration-flow/v2/register',
            data=data,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ValidateNikEmailApiClient(APIClient):
    def validate_nik_email(self, username, new_header={}):
        url = '/api/registration-flow/v2/validate'
        data = {'username': username}
        return self.post(url, data=data, format='json', **new_header)


class TestValidateNikEmail(APITestCase):
    def setUp(self):
        self.client = ValidateNikEmailApiClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer.nik = "1111110101900003"
        self.customer.phone = "08812345678"
        self.customer.save()

        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'
        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0.1',
        }

        self.feature_setting_login = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOGIN_ERROR_MESSAGE,
            is_active=True,
            parameters={
                "existing_nik/email": {
                    "title": "NIK/Email Terdaftar atau Tidak Valid",
                    "message": "Silakan masuk atau ginakan NIK / email yang valid dan belum didaftarkan di JULO, ya.",
                    "button": "Mengerti",
                    "link_image": None,
                },
                "android_to_iphone": {
                    "title": " Kamu Tidak Bisa Masuk dengan HP Ini",
                    "message": "Silakan gunakan Androidmu untuk masuk ke JULO dan selesaikan dulu proses pendaftarannya."
                    " Jika sudah tak ada akses ke HP sebelumnya, silakan kontak CS kami, ya!",
                    "button": "Kembali",
                    "link_image": None,
                },
                "iphone_to_android": {
                    "title": " Kamu Tidak Bisa Masuk dengan HP Ini",
                    "message": "Silakan gunakan iPhonemu untuk masuk ke JULO dan selesaikan dulu proses pendaftarannya."
                    " Jika sudah tak ada akses ke HP sebelumnya, silakan kontak CS kami, ya!",
                    "button": "Kembali",
                    "link_image": None,
                },
            },
        )

    def test_validate_nik(self):
        username = self.customer.nik
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        username = self.customer.nik[:-1] + "9"
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_validate_email(self):
        username = self.customer.email
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        username = self.customer.email[:-1] + "0"
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_deleted_user(self):
        self.customer.is_active = False
        self.customer.save()
        username = self.customer.nik
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.data.get('errors'), [ErrorMessageConst.CONTACT_CS_JULO])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

        username = self.customer.email
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.data.get('errors'), [ErrorMessageConst.CONTACT_CS_JULO])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_with_cross_device_last_success_android(self):

        login_attempt = LoginAttemptFactory(
            android_id='12b56c4365a56d6c',
            customer=self.customer,
            is_success=True,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=self.customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)
        expected_message_error = self.feature_setting_login.parameters['android_to_iphone'][
            'message'
        ]

        username = self.customer.nik
        response = self.client.validate_nik_email(username, self.new_device_header)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], expected_message_error)

    def test_with_cross_device_last_success_iphone(self):

        login_attempt = LoginAttemptFactory(
            android_id=None,
            customer=self.customer,
            is_success=True,
            ios_id='E78E234E-4981-4BB7-833B-2B6CEC2F56DF',
        )
        application = ApplicationFactory(
            customer=self.customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)
        expected_message_error = self.feature_setting_login.parameters['iphone_to_android'][
            'message'
        ]

        username = self.customer.nik
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], expected_message_error)

    def test_with_cross_device_last_success_iphone_app_status_not_in_criteria(self):

        login_attempt = LoginAttemptFactory(
            android_id=None,
            customer=self.customer,
            is_success=True,
            ios_id='E78E234E-4981-4BB7-833B-2B6CEC2F56DF',
        )
        application = ApplicationFactory(
            customer=self.customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)

        username = self.customer.nik
        response = self.client.validate_nik_email(username, self.new_device_header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_with_cross_device_last_success_iphone_in_criteria_but_turn_off_feature(self):

        login_attempt = LoginAttemptFactory(
            android_id=None,
            customer=self.customer,
            is_success=True,
            ios_id='E78E234E-4981-4BB7-833B-2B6CEC2F56DF',
        )
        application = ApplicationFactory(
            customer=self.customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)
        self.feature_setting_login.update_safely(
            is_active=False,
        )

        expected_message_error = ErrorMsgCrossDevices.PARAMETERS['iphone_to_android']['message']
        username = self.customer.nik
        response = self.client.validate_nik_email(username)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], expected_message_error)
