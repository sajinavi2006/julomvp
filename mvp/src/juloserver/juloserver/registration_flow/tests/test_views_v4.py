from http import HTTPStatus
from dateutil.relativedelta import relativedelta
from rest_framework.test import APIClient, APITestCase
from mock import patch
from django.test.utils import override_settings
from django.utils import timezone

from juloserver.julo.models import (
    ProductLine,
    FeatureNameConst,
)
from juloserver.julo.tests.factories import (
    OnboardingFactory,
    ProductLineFactory,
    FeatureSettingFactory,
)
from juloserver.julo.constants import OnboardingIdConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.pin.models import RegisterAttemptLog
from juloserver.registration_flow.services.google_auth_services import generate_email_verify_token


@override_settings(GOOGLE_AUTH_CLIENT_ID='gggggggggggggggggggggggggg')
class TestRegisterJuloOneUserApiV4(APITestCase):
    REGISTER_URL = '/api/registration-flow/v4/register'

    def setUp(self):
        self.client_wo_auth = APIClient()
        if not ProductLine.objects.filter(product_line_code=1).exists():
            ProductLineFactory(product_line_code=1)

        OnboardingFactory(id=OnboardingIdConst.ONBOARDING_DEFAULT)
        OnboardingFactory(id=OnboardingIdConst.LF_REG_PHONE_ID)
        OnboardingFactory(id=OnboardingIdConst.LFS_REG_PHONE_ID)
        OnboardingFactory(id=OnboardingIdConst.SHORTFORM_ID)
        OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_ID)
        OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_FORM_ID)
        OnboardingFactory(id=OnboardingIdConst.JULO_360_EXPERIMENT_ID)

        # payload to send registration data
        self.payload = {
            "username": "3998490402199715",
            "pin": "056719",
            "email": "captainmarvel@gmail.com",
            "gcm_reg_id": "12313131313",
            "android_id": "c32d6eee0040052v",
            "latitude": -6.9288264,
            "longitude": 107.6253394,
            "app_version": "7.10.0",
            "onboarding_id": OnboardingIdConst.JULO_STARTER_ID,
            "email_token": 'fake_token',
        }

        self.fs_user_as_jturbo = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
            parameters={
                "operation": "equal",
                "value": "captainmarvel@gmail.com",
            },
        )

    def test_new_user_registration_with_nik_invalid_email(self):
        """
        test case email is invalid for registration with nik
        """
        # no attempt_log
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

        # attempt log is not valid
        register_attempt = RegisterAttemptLog.objects.create(
            email='captaindc@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=False,
        )
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

        now = timezone.localtime(timezone.now())
        register_attempt.email = 'captainmarvel@gmail.com'
        register_attempt.cdate = now - relativedelta(hours=4)
        register_attempt.is_email_validated = True
        code, token = generate_email_verify_token('captaindc@gmail.com')
        register_attempt.email_validation_code = code
        register_attempt.save()
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_new_user_registration_with_nik_valid_email(self):
        """
        test case success for registration with nik
        """
        code, token = generate_email_verify_token('captainmarvel@gmail.com')
        register_attempt = RegisterAttemptLog.objects.create(
            email='captainmarvel@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=True,
            email_validation_code=code,
        )
        self.payload['email_token'] = token

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)
        self.assertEqual(json_response['data']['customer']['nik'], self.payload['username'])
        self.assertEqual(json_response['data']['customer']['email'], self.payload['email'])
        self.assertEqual(json_response['data']['set_as_jturbo'], True)

    def test_register_with_app_version_check(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

        code, token = generate_email_verify_token('captainmarvel@gmail.com')
        register_attempt = RegisterAttemptLog.objects.create(
            email='captainmarvel@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=True,
            email_validation_code=code,
        )
        self.payload['email_token'] = token

        self.app_version = '7.21.1'
        self.payload['onboarding_id'] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client_wo_auth.post(
            self.REGISTER_URL,
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        self.app_version = '8.21.1'
        self.payload['onboarding_id'] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client_wo_auth.post(
            self.REGISTER_URL,
            data=self.payload,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.assertEqual(response.status_code, HTTPStatus.CREATED)

    def test_new_user_registration_with_nik_valid_email_without_latitude_longitude(self):
        """
        test case success for registration with nik
        """
        code, token = generate_email_verify_token('captainmarvel@gmail.com')
        register_attempt = RegisterAttemptLog.objects.create(
            email='captainmarvel@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=True,
            email_validation_code=code,
        )
        self.payload['email_token'] = token
        self.payload.pop('latitude')
        self.payload.pop('longitude')

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)
        self.assertEqual(json_response['data']['customer']['nik'], self.payload['username'])
        self.assertEqual(json_response['data']['customer']['email'], self.payload['email'])
        self.assertEqual(json_response['data']['set_as_jturbo'], True)

    def test_new_user_registration_with_nik_valid_email_without_latitude_longitude_as_none(self):
        """
        test case success for registration with nik
        """
        code, token = generate_email_verify_token('captainmarvel@gmail.com')
        register_attempt = RegisterAttemptLog.objects.create(
            email='captainmarvel@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=True,
            email_validation_code=code,
        )
        self.payload['email_token'] = token
        self.payload['latitude'] = None
        self.payload['longitude'] = None

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload, format="json")
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)
        self.assertEqual(json_response['data']['customer']['nik'], self.payload['username'])
        self.assertEqual(json_response['data']['customer']['email'], self.payload['email'])
        self.assertEqual(json_response['data']['set_as_jturbo'], True)

    def test_new_user_registration_with_nik_valid_email_without_latitude_longitude_as_empty_string(
        self,
    ):
        """
        test case success for registration with nik
        """
        code, token = generate_email_verify_token('captainmarvel@gmail.com')
        register_attempt = RegisterAttemptLog.objects.create(
            email='captainmarvel@gmail.com',
            nik='1235352212927869',
            attempt=1,
            is_email_validated=True,
            email_validation_code=code,
        )

        self.payload['email_token'] = token
        self.payload['latitude'] = "a"
        self.payload['longitude'] = "a"

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload, format="json")
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], 'Invalid request')

        # should be allowed
        self.payload['latitude'] = ""
        self.payload['longitude'] = ""

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload, format="json")
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)
        self.assertEqual(json_response['data']['customer']['nik'], self.payload['username'])
        self.assertEqual(json_response['data']['customer']['email'], self.payload['email'])
        self.assertEqual(json_response['data']['set_as_jturbo'], True)
