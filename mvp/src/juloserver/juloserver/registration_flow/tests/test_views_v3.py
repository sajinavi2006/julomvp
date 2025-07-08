from http import HTTPStatus
from rest_framework.test import APIClient, APITestCase
from mock import ANY, patch, MagicMock

from juloserver.julo.models import (
    ProductLine,
    WorkflowConst,
    FeatureNameConst,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    OtpRequestFactory,
    OnboardingFactory,
    ProductLineFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    RegisterAttemptLogFactory,
    CreditScoreFactory,
)
from juloserver.pin.tests.factories import (
    CustomerPinFactory,
    TemporarySessionFactory,
    LoginAttemptFactory,
)
from juloserver.julo.constants import OnboardingIdConst, IdentifierKeyHeaderAPI
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory


class PhoneNumberApiClient(APIClient):
    def check_phone_number(self, phone, new_header={}):
        url = '/api/registration-flow/v3/check'
        data = {'phone': phone}
        return self.post(url, data=data, format='json', **new_header)

    def check_username(self, username, new_header={}):
        url = '/api/registration-flow/v3/check'
        data = {'username': username}
        return self.post(url, data=data, format='json', **new_header)


class PhoneNumberApiTestCase(APITestCase):
    client_class = PhoneNumberApiClient

    def setUp(self):

        self.workflow_j1 = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
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
                    "title": "title",
                    "message": "message",
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
        self.feature_setting_cross_os = FeatureSettingFactory(
            feature_name=FeatureNameConst.CROSS_OS_LOGIN,
            is_active=True,
            parameters={
                'status_code': 'x190',
                'expiry_status_code': [106, 135, 136, 185, 186, 133],
            },
        )
        self.workflow_j1_ios = WorkflowFactory(
            name=WorkflowConst.JULO_ONE_IOS, handler='JuloOneIOSWorkflowHandler'
        )

    def test_phone_invalid(self):
        phone = '628889991010'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST, response.data)

        phone = '088899917,11'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST, response.data)

    def test_phone_valid_registered(self):
        phone = '088889991010'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, HTTPStatus.OK, response.data)
        self.assertEqual(response.json()['data']['total_found'], 0)

    def test_phone_valid_unregistered(self):
        phone = '08812345678'
        response = self.client.check_phone_number(phone)
        self.assertEqual(response.status_code, HTTPStatus.OK, response.data)

    def test_customer_has_pin(self):
        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        CustomerPinFactory(user=customer.user)

        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertTrue(response.json()['data']['customer'][0]['customer_has_pin'])

    def test_customer_locked(self):
        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        CustomerPinFactory(
            user=customer.user,
            latest_failure_count=5,
        )

        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertTrue(response.json()['data']['customer'][0]['is_locked'])

    def test_customer_permanently_blocked(self):
        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        CustomerPinFactory(
            user=customer.user,
            latest_blocked_count=5,
        )

        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertTrue(response.json()['data']['customer'][0]['is_permanently_blocked'])

    def test_phone_valid_registered_with_cross_device(self):

        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        login_attempt = LoginAttemptFactory(
            android_id='12b56c4365a56d6c',
            customer=customer,
            is_success=True,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        login_attempt.update_safely(is_success=False)
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['total_found'], 1)

    def test_phone_valid_registered_with_cross_device_with_turn_off_setting(self):
        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        login_attempt = LoginAttemptFactory(
            android_id='12b56c4365a56d6c',
            customer=customer,
            is_success=True,
            ios_id=None,
        )
        self.feature_setting_login.update_safely(is_active=False)

        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_phone_valid_registered_with_cross_device_from_android(self):

        nik = '3113052412920301'
        customer = CustomerFactory(nik=nik)
        login_attempt = LoginAttemptFactory(
            android_id=None,
            customer=customer,
            is_success=True,
            ios_id=self.ios_id,
        )

        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_registered_android_cross_device_register_attempt(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_registered_android_cross_device_register_login_attempt(self):
        """
        Cases:
        1. User registration and create application in Android
        2. Then try to login with Android
        3. and then try login again with iOS Device

        """

        nik = '3113052412920301'
        email = 'tester@julo.co.id'
        android_id = '12b56c4365a56d6c'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )

        # Register Attempt Log record
        register_attempt_log = RegisterAttemptLogFactory(
            android_id=android_id,
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        # Login Attempt record
        login_attempt = LoginAttemptFactory(
            android_id=android_id,
            customer=customer,
            is_success=True,
            ios_id='',
        )

        # Try login with iOS Device
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        # Login with existing device Android
        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['total_found'], 1)

    def test_valid_registered_android_cross_device_register_attempt_success(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.LOC_APPROVED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_valid_registered_android_cross_device_register_attempt_in_x105(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_registered_android_cross_login_expired_status(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_valid_registered_android_cross_login_form_x100_and_case_feature_turn_off(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        new_parameters = self.feature_setting_cross_os.parameters
        new_parameters['status_code'] = 'x100'
        self.feature_setting_cross_os.update_safely(parameters=new_parameters)
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)

        # case feature setting is turn-off, so will block all status cannot bypass
        self.feature_setting_cross_os.update_safely(
            is_active=False,
        )
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_registered_android_cross_login_form_x105(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
        )

        # case for x105 non-c
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)
        credit_score = CreditScoreFactory(application_id=application.id, score='B')
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        # case for x105 C
        credit_score.update_safely(score='C')
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_valid_registered_android_cross_device_register_attempt_multiple_case(self):
        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        register_attempt_log = RegisterAttemptLogFactory(
            android_id='12b56c4365a56d6c',
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        register_attempt_log_other_data = RegisterAttemptLogFactory(
            android_id=None,
            email=customer.email,
            nik=customer.nik,
            ios_id=self.ios_id,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_registered_android_cross_device_register_attempt_is_empty(self):
        """
        Test with empty register attempt log
        """

        nik = '3113052412920301'
        email = 'tester@julo.co.id'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )
        application = ApplicationFactory(
            customer=customer,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        # Login Attempt record with Android
        login_attempt = LoginAttemptFactory(
            android_id='android_id_testing',
            customer=customer,
            is_success=True,
            ios_id=None,
        )

        # Login Attempt record with iOS ID
        login_attempt = LoginAttemptFactory(
            android_id=None,
            customer=customer,
            is_success=True,
            ios_id='ios_id_testing',
        )

        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_valid_login_with_both_device_success_with_android(self):

        nik = '3113052412920301'
        email = 'tester@julo.co.id'
        android_id = '12b56c4365a56d6c'
        ios_id = 'ios_id_testing'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )

        # Register Attempt Log record Android
        register_attempt_log = RegisterAttemptLogFactory(
            android_id=android_id,
            email=customer.email,
            nik=customer.nik,
            ios_id=None,
        )
        application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow_j1,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        # Login Attempt record with Android
        login_attempt_1 = LoginAttemptFactory(
            android_id=android_id,
            customer=customer,
            is_success=True,
            ios_id='',
        )

        # Login attempt with iOS device
        login_attempt_2 = LoginAttemptFactory(
            android_id=None,
            customer=customer,
            is_success=True,
            ios_id=ios_id,
        )

        # Try login with iOS Device
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        # Login with existing device Android
        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['total_found'], 1)

    def test_valid_login_with_both_device_success_with_ios(self):

        nik = '3113052412920301'
        email = 'tester@julo.co.id'
        android_id = '12b56c4365a56d6c'
        ios_id = 'ios_id_testing'

        customer = CustomerFactory(
            nik=nik,
            email=email,
        )

        # Register Attempt Log record Android
        register_attempt_log = RegisterAttemptLogFactory(
            android_id=None,
            email=customer.email,
            nik=customer.nik,
            ios_id=ios_id,
        )
        application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow_j1_ios,
        )
        application.update_safely(application_status_id=ApplicationStatusCodes.FORM_CREATED)

        # Login Attempt record with Android
        login_attempt_1 = LoginAttemptFactory(
            android_id=None,
            customer=customer,
            is_success=True,
            ios_id=ios_id,
        )

        # Login attempt with iOS device
        login_attempt_2 = LoginAttemptFactory(
            android_id=android_id,
            customer=customer,
            is_success=True,
            ios_id=None,
        )

        # Try login with Android ID
        response = self.client.check_username(nik)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        # Login with existing device iOS
        response = self.client.check_username(nik, self.new_device_header)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['total_found'], 1)


class TestRegisterJuloOneUserApiV3(APITestCase):
    REGISTER_URL = '/api/registration-flow/v3/register'

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
        OnboardingFactory(id=OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT)
        OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)

        # payload to send registration data
        self.payload = {
            "username": "3998490402199715",
            "pin": "056719",
            "email": "testing@gmail.com",
            "gcm_reg_id": "12313131313",
            "android_id": "c32d6eee0040052v",
            "latitude": -6.9288264,
            "longitude": 107.6253394,
            "app_version": "7.10.0",
        }

        self.fs_user_as_jturbo = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SPECIFIC_USER_FOR_JSTARTER,
            parameters={
                "operation": "equal",
                "value": "testing@gmail.com",
            },
        )

    def test_new_user_with_phone_number_is_success(self):
        """
        For test case if user register with phone
        """

        # delete username and email for registration by phone
        self.payload.pop('email', None)

        onboarding_id = OnboardingIdConst.LFS_REG_PHONE_ID
        phone = "08398298129831"
        user = AuthUserFactory(username=phone)
        otp_request = OtpRequestFactory(
            phone_number=phone, otp_service_type='sms', is_used=True, action_type='phone_register'
        )
        session = TemporarySessionFactory(user=user, otp_request=otp_request)
        self.payload["onboarding_id"] = onboarding_id
        self.payload["phone"] = phone
        self.payload['username'] = phone
        self.payload['session_token'] = session.access_key
        self.payload['registration_type'] = 'phone_number'

        # for case otp require verification when registration flow
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['customer']['phone'], phone)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)

    def test_new_user_with_phone_number_is_key_invalid(self):
        """
        For test case if user register with phone
        """

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        onboarding_id = OnboardingIdConst.LFS_REG_PHONE_ID
        phone = "08398298129831"
        self.payload["onboarding_id"] = onboarding_id
        self.payload["phone"] = phone
        self.payload['registration_type'] = 'phone_number'

        # for case otp require verification when registration flow
        OtpRequestFactory(
            customer=customer,
            phone_number=phone,
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_new_user_registration_with_nik(self):
        """
        test case success for registration with nik
        """

        self.payload['onboarding_id'] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)
        self.assertEqual(json_response['data']['customer']['nik'], self.payload['username'])
        self.assertEqual(json_response['data']['customer']['email'], self.payload['email'])
        self.assertEqual(json_response['data']['set_as_jturbo'], True)

    def test_new_user_registration_duplicate_with_nik(self):
        """
        test case for duplicate nik when registration
        """

        self.payload['onboarding_id'] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.CREATED)

        second_response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(second_response.status_code, HTTPStatus.BAD_REQUEST)

    def test_new_user_registration_with_disallow_onboarding(self):
        """
        test case to check onboarding_id disallow when registration
        """

        self.payload['onboarding_id'] = OnboardingIdConst.JULO_STARTER_FORM_ID
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_new_user_registration_with_pin_is_weak(self):
        """
        test case to check onboarding_id disallow when registration
        """

        self.payload['pin'] = "123456"
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_user_registration_with_nik_for_j360(
        self,
        mock_application_change,
        mock_create_application_checklist,
        mock_address_generate_geolocation,
        mock_fraud_check,
    ):
        """
        test case success for registration for J360
        """

        self.payload['onboarding_id'] = OnboardingIdConst.JULO_360_EXPERIMENT_ID

        phone = "08398298129831"
        user = AuthUserFactory(username=phone)
        otp_request = OtpRequestFactory(
            phone_number=phone, otp_service_type='sms', is_used=True, action_type='phone_register'
        )
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        session = TemporarySessionFactory(user=user, otp_request=otp_request)
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_360_EXPERIMENT_ID
        self.payload["phone"] = phone
        self.payload['username'] = phone
        self.payload['session_token'] = session.access_key
        self.payload['registration_type'] = 'phone_number'

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertIn('applications', json_response['data'])

    def test_new_user_registration_with_nik_for_split_emergency_contact(
        self,
    ):
        """
        test case success for registration for LFS_SPLIT_EMERGENCY_CONTACT
        """

        self.payload.pop('email', None)

        onboarding_id = OnboardingIdConst.LFS_REG_PHONE_ID
        phone = "08398298129831"
        user = AuthUserFactory(username=phone)
        otp_request = OtpRequestFactory(
            phone_number=phone, otp_service_type='sms', is_used=True, action_type='phone_register'
        )
        session = TemporarySessionFactory(user=user, otp_request=otp_request)
        self.payload["onboarding_id"] = onboarding_id
        self.payload["phone"] = phone
        self.payload['username'] = phone
        self.payload['session_token'] = session.access_key
        self.payload['registration_type'] = 'phone_number'

        # for case otp require verification when registration flow
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        json_response = response.json()
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(json_response['data']['customer']['phone'], phone)
        self.assertEqual(json_response['data']['status'], ApplicationStatusCodes.NOT_YET_CREATED)

    def test_register_with_app_version_check(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

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
