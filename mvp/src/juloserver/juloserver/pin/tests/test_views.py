import hashlib
import io
from datetime import datetime, timedelta

import mock
from http import HTTPStatus
from django.contrib.auth.models import User, Group
from django.test.utils import override_settings
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from mock import ANY, patch, MagicMock
from rest_framework.test import APIClient, APITestCase

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.julo.clients.sms import JuloSmsClient
from juloserver.julo.constants import (
    WorkflowConst,
    OnboardingIdConst,
    ApplicationStatusCodes,
    ExperimentConst,
    MobileFeatureNameConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.julo.models import (
    Customer,
    ProductLine,
    Application,
    Device,
)
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    ExperimentTestGroupFactory,
    FeatureSettingFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    ProductLineFactory,
    WorkflowFactory,
    OnboardingFactory,
    StatusLookupFactory,
    PartnerFactory,
    AppVersionFactory,
    ApplicationUpgradeFactory,
    CustomerRemovalFactory,
)
from juloserver.pin.constants import ResetMessage, VerifyPinMsg, CustomerResetCountConstants
from juloserver.pin.models import (
    CustomerPin,
    LoginAttempt,
    PinValidationToken,
    CustomerPinAttempt,
)
from juloserver.pin.tests.factories import (
    CustomerPinChangeFactory,
    CustomerPinFactory,
    TemporarySessionFactory,
    CustomerPinAttemptFactory,
    LoginAttemptFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import OnboardingIdConst, FeatureNameConst
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo_starter.constants import JStarterToggleConst
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.partnership.constants import ErrorMessageConst
from rest_framework import status

from juloserver.api_token.models import ExpiryToken

from juloserver.api_token.constants import EXPIRY_SETTING_KEYWORD
from juloserver.julo.constants import FeatureNameConst

from juloserver.api_token.constants import REFRESH_TOKEN_EXPIRY, REFRESH_TOKEN_MIN_APP_VERSION


def new_julo1_product_line():
    if not ProductLine.objects.filter(product_line_code=1).exists():
        ProductLineFactory(product_line_code=1)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRegisterJuloOneUserApi(APITestCase):
    REGISTER_URL = '/api/pin/v1/register'

    def setUp(self):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )

        # Set onboarding factory
        OnboardingFactory(id=1, description='Longform', status=True)
        OnboardingFactory(id=2, description='Shortform', status=True)
        OnboardingFactory(id=3, description='Longform Shortened', status=True)
        OnboardingFactory(
            id=OnboardingIdConst.LF_REG_PHONE_ID,
            description='Register with phone number AND Long Form',
            status=True,
        )
        OnboardingFactory(
            id=OnboardingIdConst.LFS_REG_PHONE_ID,
            description='Register with phone number AND Long Form Shortened',
            status=True,
        )

        # payload to send registration data
        self.payload = {
            "username": "3998490402199715",
            "pin": "056719",
            "email": "testing@gmail.com",
            "gcm_reg_id": "12313131313",
            "android_id": "c32d6eee0040052v",
            "latitude": -6.9288264,
            "longitude": 107.6253394,
            "is_rooted_device": False,
            "is_suspicious_ip": False,
            "app_version": "7.5.0",
        }

    def generate_customer(self, phone):
        url = '/api/registration-flow/v1/generate-customer'
        data = {'phone': phone}
        return self.client_wo_auth.post(url, data, format='json')

    def test_new_j1_user_invalid_data(self):
        response = self.client_wo_auth.post(self.REGISTER_URL, data={})
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_invalid_email(self, _mock_get_latest_app_version):
        data = {
            "username": "1599110506026781",
            "pin": "123456",
            "email": "minhnha9z@yahoo.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 400

    def test_new_j1_user_invalid_pin(self):
        data = {
            "username": "1599110506026781",
            "pin": "1234565",
            "email": "minhnha9z@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_invalid_username(self, _mock_get_latest_app_version):
        data = {
            "username": "15991105",
            "pin": "123456",
            "email": "minhnha9z@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_with_0_username(self, _mock_get_latest_app_version):
        data = {
            "username": "0599110506026781",
            "pin": "123456",
            "email": "minhnha9z@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 400

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user(
        self,
        _mock_get_latest_app_version,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        data = {
            "username": "1599110506026781",
            "pin": "444672",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 201
        response = self.client_wo_auth.post(self.REGISTER_URL, data=data)
        assert response.status_code == 400

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_onboarding_longform(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case onboarding_id on longform case
        """

        onboarding_id_longform = 1
        self.payload["onboarding_id"] = onboarding_id_longform
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload).json()
        self.assertEqual(
            response["data"]["applications"][0]["onboarding_id"], onboarding_id_longform
        )

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_onboarding_longform_shortened(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case onboarding_id on longform shortened case
        """

        longform_shortened = 3
        self.payload["onboarding_id"] = longform_shortened
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload).json()
        self.assertEqual(response["data"]["applications"][0]["onboarding_id"], longform_shortened)

    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_onboarding_shortform(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
    ):
        """
        For test case onboarding_id shortform case with hit endpoint longform
        expected for result is not allowed.
        """

        onboarding_id_shortform = 2
        self.payload["onboarding_id"] = onboarding_id_shortform
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload).json()
        self.assertEqual(response["errors"][0], "Onboarding is not allowed!")

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_onboarding_default_value(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case onboardind_id with default value
        """

        default_value_onboarding = OnboardingIdConst.ONBOARDING_DEFAULT
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload).json()
        self.assertEqual(
            response["data"]["applications"][0]["onboarding_id"], default_value_onboarding
        )

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_phone_number_is_key_invalid(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case if user register with phone
        """

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        onboarding_id = OnboardingIdConst.LFS_REG_PHONE_ID
        phone = "08398298129831"
        self.payload["onboarding_id"] = onboarding_id
        self.payload["phone"] = phone
        self.generate_customer(phone)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

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
        self.assertEqual(response.json()['errors'][0], "Mohon maaf terjadi kesalahan teknis.")

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_phone_number_is_success(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case if user register with phone
        """

        # delete username and email for registration by phone
        self.payload.pop('email', None)
        self.payload.pop('username', None)

        user = AuthUserFactory()
        customer = CustomerFactory(user=user)

        onboarding_id = OnboardingIdConst.LFS_REG_PHONE_ID
        phone = "08398298129831"
        self.payload["onboarding_id"] = onboarding_id
        self.payload["phone"] = phone
        self.generate_customer(phone)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

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

        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LFS_REG_PHONE_ID,
        )

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_register_with_app_version_check(
        self,
        _mock_get_latest_app_version,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

        data = {
            "username": "1599110506026781",
            "pin": "444672",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }

        self.app_version = '7.21.1'
        response = self.client_wo_auth.post(
            self.REGISTER_URL,
            data=data,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        assert response.status_code == 400

        self.app_version = '8.21.1'
        response = self.client_wo_auth.post(
            self.REGISTER_URL,
            data=data,
            format='json',
            HTTP_X_APP_VERSION=self.app_version,
        )
        assert response.status_code == 201


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRegisterJuloOneUserApiV2(TestRegisterJuloOneUserApi):
    REGISTER_URL = '/api/pin/v2/register'

    def setUp(self):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )

        # Set onboarding factory
        OnboardingFactory(id=1, description='Longform', status=True)
        OnboardingFactory(id=2, description='Shortform', status=True)
        OnboardingFactory(id=3, description='Longform Shortened', status=True)
        OnboardingFactory(
            id=OnboardingIdConst.LF_REG_PHONE_ID,
            description='Register with phone number AND Long Form',
            status=True,
        )
        OnboardingFactory(
            id=OnboardingIdConst.LFS_REG_PHONE_ID,
            description='Register with phone number AND Long Form Shortened',
            status=True,
        )
        OnboardingFactory(
            id=OnboardingIdConst.JULO_STARTER_FORM_ID,
            description='JuloStarter Experiment',
            status=True,
        )

        # payload to send registration data
        self.payload = {
            "username": "3998490402199715",
            "pin": "056719",
            "email": "testing@gmail.com",
            "gcm_reg_id": "12313131313",
            "android_id": "c32d6eee0040052v",
            "latitude": -6.9288264,
            "longitude": 107.6253394,
            "is_rooted_device": False,
            "is_suspicious_ip": False,
            "app_version": "7.5.0",
        }

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_phone_number_is_success(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
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

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

        # for case otp require verification when registration flow
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.CREATED)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LFS_REG_PHONE_ID,
        )

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_j1_user_with_phone_number_is_key_invalid(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
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
        self.generate_customer(phone)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

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

    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_new_user_j1_for_julo_starter_user_with_experiment_is_not_running(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
    ):
        """
        For test case onboarding_id on julostarter case
        Experiment is not running
        """

        experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.JULO_STARTER_EXPERIMENT,
            start_date=timezone.localtime(timezone.now()) - timedelta(days=1),
            end_date=timezone.localtime(timezone.now()) + timedelta(days=5),
            criteria={
                "regular_customer_id": [2, 3, 4, 5, 6, 7, 8, 9],
                "julo_starter_customer_id": [0, 1],
                "target_version": "==7.9.0",
            },
            is_active=False,
            is_permanent=False,
        )

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_FORM_ID
        self.payload["app_version"] = "7.9.0"
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()["errors"][0], "Onboarding is not allowed!")

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_if_email_and_username_already_existing(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):

        self.payload['onboarding_id'] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        # create workflow path
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

        # for case otp require verification when registration flow
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.CREATED)

        # case to register with same nik and email
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], 'Nomor KTP Anda sudah terdaftar')

        # case to register with same nik
        self.payload['email'] = 'testingpurposes@gmail.com'
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], 'Nomor KTP Anda sudah terdaftar')

        # case to register with same email
        self.payload['username'] = '3998490402199716'
        self.payload['email'] = 'testing@gmail.com'
        response = self.client_wo_auth.post(self.REGISTER_URL, data=self.payload)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], 'Nomor KTP / Email Anda sudah terdaftar')

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    def test_register_with_app_version_check(
        self,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        """
        For test case if user register with phone
        """

        # delete username and email for registration by phone
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.APP_MINIMUM_REGISTER_VERSION,
            is_active=True,
            parameters={
                'app_minimum_version': '8.10.0',
                'error_message': 'This is the error message',
            },
        )

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

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

        self.app_version = '7.21.1'
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


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRegisterJuloOneUserWebApi(APITestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.api_pin_web_register_url = '/api/pin/web/v1/register'

    def test_new_j1_user_invalid_data(self):
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data={})
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_invalid_email(self, _mock_get_latest_app_version):
        data = {
            "username": "1588210506026781",
            "pin": "123456",
            "email": "rikki882@yahoo.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400

    def test_new_j1_user_invalid_pin(self):
        data = {
            "username": "1588210506026781",
            "pin": "1234565",
            "email": "rikki882@gmail.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_invalid_username(self, _mock_get_latest_app_version):
        data = {
            "username": "15882105",
            "pin": "123456",
            "email": "rikki882@gmail.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_0_username(self, _mock_get_latest_app_version):
        data = {
            "username": "0599110506026781",
            "pin": "123456",
            "email": "rikki882@gmail.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400

    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user_invalid_lat_and_long(self, _mock_get_latest_app_version):
        data = {
            "username": "1588210506026784",
            "pin": "444672",
            "email": "rikki1234r5@gmail.com",
            "web_version": "0.0.1",
            "latitude": "tytry",
            "longitude": "tytry",
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.NO_LOCATION_DATA]

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def test_new_j1_user(
        self,
        _mock_get_latest_app_version,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        data = {
            "username": "1588210506026781",
            "pin": "444672",
            "email": "rikki12345@gmail.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 201
        response = self.client_wo_auth.post(self.api_pin_web_register_url, data=data)
        assert response.status_code == 400


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginJuloOneWebApi(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                'max_wait_time_mins': 60,
                'max_retry_count': 3,
                'response_message': {
                    'permanent_locked': (
                        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
                        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
                    ),
                    'temporary_locked': (
                        'Akun kamu diblokir sementara selama {eta} '
                        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
                    ),
                    'cs_contact_info': {
                        'phone': ['02150919034', '02150919035'],
                        'email': ['cs@julo.co.id'],
                    },
                },
            },
        )
        data = {
            "username": "1588210506026710",
            "pin": "122351",
            "email": "rikki123444@gmail.com",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/web/v1/register', data=data)
        self.api_pin_web_login_url = '/api/pin/web/v1/login'

    def test_login_invalid_username(self):
        data = {
            "username": "1588210506026711",
            "pin": "123456",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 401
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_invalid_pin(self):
        data = {
            "username": "1588210506026710",
            "pin": "123447",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 401
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_no_pin(self):
        data = {
            "username": "1588210506026710",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.REQUIRED_PIN]

    def test_login_with_no_latitude_and_longitude(self):
        data = {
            "username": "1588210506026710",
            "pin": "122351",
            "web_version": "0.0.1",
            "latitude": "",
            "longitude": "",
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.NO_LOCATION_DATA]

    def test_login_success(self):
        data = {
            "username": "1588210506026710",
            "pin": "122351",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

    @patch.object(
        JuloEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.tasks.send_email_lock_pin')
    @patch('juloserver.pin.tasks.send_email_unlock_pin')
    def test_trying_login_get_lock(
        self, mock_email_unlock_pin, mock_email_lock_pin, mock_send_email
    ):
        data = {
            "username": "1588210506026710",
            "pin": "123457",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 401
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 401
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 403
        assert response.json()['errors'] == [
            VerifyPinMsg.LOCKED_LOGIN_REQUEST_LIMIT.format(eta='1 Jam')
        ]

        mock_email_unlock_pin.apply_async.assert_called_once_with(ANY, countdown=3600)
        mock_email_lock_pin.delay.assert_called_with(ANY, ANY, ANY, ANY, ANY)

        time_now = timezone.localtime(timezone.now())
        customer_pin = CustomerPin.objects.get(user__username='1588210506026710')
        customer_pin.last_failure_time = time_now - timedelta(hours=10)
        customer_pin.save()
        data = {
            "username": "1588210506026710",
            "pin": "122351",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        assert response.status_code == 200

    def test_login_partner_multiple_application(self) -> None:
        data = {
            "username": "1588210506026710",
            "pin": "122351",
            "web_version": "0.0.1",
            "latitude": 0.0,
            "longitude": 0.0,
        }

        # Copy application
        application = Application.objects.get(ktp=data['username'])
        application.pk = None
        application.save()

        applications = Application.objects.filter(ktp=data['username']).order_by('id')
        application1 = applications[0]
        application2 = applications[1]

        application1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        application1.save()

        application2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        application2.save()

        # Test if application status 2 is 190 LOC_APPROVED
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['data']['continue_in_apps'], True)

        application2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        application2.save()

        # Test if application status 2 is 105 FORM_PARTIAL
        response = self.client_wo_auth.post(self.api_pin_web_login_url, data=data)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['continue_in_apps'], False)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginJuloOneApi(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                'max_wait_time_mins': 60,
                'max_retry_count': 3,
                'response_message': {
                    'permanent_locked': (
                        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
                        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
                    ),
                    'temporary_locked': (
                        'Akunn kamu diblokir sementara selama {eta} '
                        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
                    ),
                    'cs_contact_info': {
                        'phone': ['02150919034', '02150919035'],
                        'email': ['cs@julo.co.id'],
                    },
                },
            },
        )
        data = {
            "username": "1599110506026710",
            "pin": "122351",
            "email": "asdf123444@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }
        response = self.client_wo_auth.post('/api/pin/v1/register', data=data)

        self.partner_user = AuthUserFactory(username='1114423219321235')
        partner_customer = CustomerFactory(
            user=self.partner_user,
            nik=self.partner_user.username,
            email='test_3_register@julo.co.id',
        )
        partner_workflow = WorkflowFactory(name='EmployeeFinancingWorkflow')
        product_line_partner = ProductLineFactory(
            product_line_code=ProductLineCodes.EMPLOYEE_FINANCING
        )
        ApplicationFactory(
            customer=partner_customer, workflow=partner_workflow, product_line=product_line_partner
        )

    def test_login_invalid_username(self):
        data = {
            "username": "1599110506026711",
            "pin": "123456",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 401
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_invalid_pin(self):
        data = {
            "username": "1599110506026710",
            "pin": "123447",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 401
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_no_pin(self):
        data = {
            "username": "1599110506026710",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.REQUIRED_PIN]

    def test_login_success(self):
        data = {
            "username": "1599110506026710",
            "pin": "122351",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

    @patch.object(
        JuloEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.tasks.send_email_lock_pin')
    @patch('juloserver.pin.tasks.send_email_unlock_pin')
    def test_trying_login_get_lock(
        self, mock_email_unlock_pin, mock_email_lock_pin, mock_send_email
    ):
        data = {
            "username": "1599110506026710",
            "pin": "123457",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 401
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 401
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 403
        assert response.json()['errors'] == [
            'Akunn kamu diblokir sementara selama {eta} karena salah memasukkan '
            'informasi. Silakan coba masuk kembali nanti.'.format(eta='1 Jam')
        ]

        mock_email_unlock_pin.apply_async.assert_called_once_with(ANY, countdown=3600)
        mock_email_lock_pin.delay.assert_called_with(ANY, ANY, ANY, ANY, ANY)

        time_now = timezone.localtime(timezone.now())
        customer_pin = CustomerPin.objects.get(user__username='1599110506026710')
        customer_pin.last_failure_time = time_now - timedelta(hours=10)
        customer_pin.save()
        data = {
            "username": "1599110506026710",
            "pin": "122351",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.status_code == 200

    def test_non_julo_one(self):
        user = AuthUserFactory(password='123457')
        customer = CustomerFactory(user=user)
        data = {
            "username": customer.email,
            "pin": "123457",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_ef_user_login_julo_one(self):
        data = {
            "username": self.partner_user.username,
            "pin": "122351",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        msg = [
            'Lanjutkan login pada web partner JULO sesuai akun yang terdaftar'
            '\nMengalami kesulitan login? hubungi cs@julo.co.id'
        ]
        response = self.client_wo_auth.post('/api/pin/v1/login', data=data)

        # return 400, should be restricted employee financing login using J1
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], msg)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginApi(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                'max_wait_time_mins': 90,
                'max_retry_count': 3,
                'response_message': {
                    'permanent_locked': (
                        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
                        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
                    ),
                    'temporary_locked': (
                        'Akun kamu diblokir sementara selama {eta} '
                        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
                    ),
                    'cs_contact_info': {
                        'phone': ['02150919034', '02150919035'],
                        'email': ['cs@julo.co.id'],
                    },
                },
            },
        )
        data = {
            "username": "1599110506026710",
            "pin": "865399",
            "email": "asdf123444@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }
        response = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf123444@gmail.com')
        self.customer.phone = '21312312132'

    def test_login_j1_invalid_username(self):
        data = {
            "username": "1599110506026711",
            "password": "123456",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_j1_0_username(self):
        data = {
            "username": "0599110506026711",
            "password": "123456",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_invalid_password(self):
        # julo one
        data = {
            "username": "1599110506026710",
            "password": "123447",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]
        # second login
        user = User.objects.get(username="1599110506026710")
        data['username'] = '1234567890'
        data['password'] = 'sdsadasewq'
        user.customer.email = '1234567890'
        user.customer.save()
        # user.customer.user.set_password('123447')
        # user.customer.user.save()
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [
            VerifyPinMsg.LOGIN_ATTEMP_FAILED.format(attempt_count=2, max_attempt=3)
        ]

        # mtl
        data['username'] = '0123456789121777'
        customer = CustomerFactory(nik=data['username'])
        customer.save()
        customer.user.set_password('test123')
        # first time failed
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]
        # second time failed
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    def test_login_no_password(self):
        data = {
            "username": "1599110506026710",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.LOGIN_FAILED]

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    def test_login_invalid_otp(self, mock_validate_login_otp):
        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            "otp_token": '123123',
        }
        msf = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time': 180},
        )

        mock_validate_login_otp.return_value = False, 'failed'
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 419

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_login_success(self, mock_send_sms_otp, mock_validate_login_otp):
        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']
        # send otp
        user = User.objects.get(username="1599110506026710")
        application = ApplicationFactory(customer=user.customer)
        application.application_status_id = 120
        application.save()
        AddressGeolocationFactory(application=application)
        msf = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time': 180},
        )
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 203
        assert response.json()['data']['otp_wait_seconds'] == 400
        mock_send_sms_otp.assert_called()

        # customer has no phone number
        application.mobile_phone_1 = None
        application.save()
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 200

        # with otp
        data['otp_token'] = '123123'
        mock_validate_login_otp.return_value = True, 'success'
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

    @patch.object(
        JuloEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.tasks.send_email_lock_pin')
    @patch('juloserver.pin.tasks.send_email_unlock_pin')
    def test_trying_login_get_lock(
        self, mock_email_unlock_pin, mock_email_lock_pin, mock_send_email
    ):
        data = {
            "username": "1599110506026710",
            "password": "123888",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 400
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 403
        assert response.json()['errors'] == [
            VerifyPinMsg.LOCKED_LOGIN_REQUEST_LIMIT.format(eta='1 Jam 30 menit')
        ]

        mock_email_unlock_pin.apply_async.assert_called_once_with(ANY, countdown=5400)
        mock_email_lock_pin.delay.assert_called_with(ANY, ANY, ANY, ANY, ANY)

        time_now = timezone.localtime(timezone.now())
        customer_pin = CustomerPin.objects.get(user__username='1599110506026710')
        customer_pin.last_failure_time = time_now - timedelta(hours=10)
        customer_pin.save()
        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        response = self.client_wo_auth.post('/api/pin/v2/login', data=data)
        assert response.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestResetPinAPI(APITestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()

    def test_outdated(self):
        response = self.client_wo_auth.post('/api/pin/v1/reset/request', data={})
        assert response.status_code == 400
        assert response.json()['errors'][0] == (
            "Fitur Ubah PIN hanya dapat diakses dengan aplikasi versi terbaru. Update JULO "
            "dulu, yuk! Untuk info lebih lanjut hubungi CS: \n\n"
            "Telepon: \n"
            "021-5091 9034/021-5091 9035 \n\n"
            "Email: \n"
            "cs@julo.co.id"
        )


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestResetPasswordAPI(APITestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()

    def test_outdated(self):
        response = self.client_wo_auth.post('/api/pin/v2/reset/request', data={})
        assert response.status_code == 400
        assert response.json()['errors'][0] == (
            "Fitur Ubah PIN hanya dapat diakses dengan aplikasi versi terbaru. Update JULO "
            "dulu, yuk! Untuk info lebih lanjut hubungi CS: \n\n"
            "Telepon: \n"
            "021-5091 9034/021-5091 9035 \n\n"
            "Email: \n"
            "cs@julo.co.id"
        )


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestResetPinConfirmAPI(APITestCase):
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.client_wo_auth = APIClient()
        data = {
            "username": "1599110506026770",
            "pin": "122452",
            "email": "asdf1233457@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN,
            is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days": 0, "hours": 24, "minutes": 0},
                "pin_users_link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )
        res = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf1233457@gmail.com')
        self.customer.phone = '081234567890'
        self.customer.save()
        session = TemporarySessionFactory(user=self.customer.user)
        data = {"customer_xid": self.customer.customer_xid, "session_token": session.access_key}
        self.client_wo_auth.post('/api/pin/v5/reset/request', data=data)
        self.customer.refresh_from_db()
        self.url_confirm_pin = f"/api/pin/v1/reset/confirm/{self.customer.reset_password_key}/"

    def test_get_cornfirm_pin_request_wrong_key(self):
        response = self.client_wo_auth.get('/api/pin/v1/reset/confirm/asd3432/')

        assert response.status_code == 400

    def test_get_confirm_pin_request(self):
        response = self.client_wo_auth.get(self.url_confirm_pin)

        assert response.status_code == 200

    def test_confirm_pin_wrong_pass(self):
        data = {'pin1': None, 'pin2': None}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_invalid_pass(self):
        data = {'pin1': 'asdf', 'pin2': 'asdf'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_is_weakness(self):
        reset_password_key = self.customer.reset_password_key
        data = {'pin1': '123456', 'pin2': '123456'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_is_same_with_dob(self):
        data = {'pin1': '050602', 'pin2': '050602'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_2_pass_diff(self):
        data = {'pin1': '133446', 'pin2': '123454'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_wrong_key(self):
        data = {'pin1': '133446', 'pin2': '133446'}
        response = self.client_wo_auth.post('/api/pin/v1/reset/confirm/wrongkey/', data=data)
        assert response.status_code == 400

    def test_confirm_pin_same_as_old_pin(self):
        data = {'pin1': '122452', 'pin2': '122452'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_invalid_payload_attribute(self):
        data = {'invalidpin1': '122452', 'invalidpin2': '122332'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_success(self):
        data = {'pin1': '133446', 'pin2': '133446'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 200

    def test_get_confirm_pin_julover_get(self):
        app_julover = ApplicationFactory.julover()
        customer = app_julover.customer
        customer.reset_password_key = 'open_the_pod_bay_doors_HAL'
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        customer.save()
        CustomerPinFactory(user=customer.user)
        reset_link = f"/api/pin/v1/reset/confirm/{customer.reset_password_key}/?julover=true"
        # get
        response = self.client_wo_auth.get(reset_link)
        self.assertEqual(response.template_name, 'julovers/reset_pin_failed.html')
        print(vars(response))
        self.assertEqual(
            response.request['QUERY_STRING'],
            'julover=true',
        )

    def test_get_confirm_pin_julover_post(self):
        reset_key = "im_sorry_i_cant_do_that"
        app_julover = ApplicationFactory.julover()
        customer = app_julover.customer
        customer.reset_password_key = reset_key
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        customer.save()
        pin = CustomerPinFactory(user=customer.user)
        CustomerPinChangeFactory(
            customer_pin=pin,
            email=customer.email,
            reset_key=reset_key,
        )
        reset_link = f"/api/pin/v1/reset/confirm/{customer.reset_password_key}/?julover=true"

        data = {'pin1': '123456', 'pin2': '123456'}

        # first, should be expired
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )
        self.assertEqual(response.template_name, 'julovers/reset_pin_failed.html')

        # fixed
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) + timedelta(days=1)
        customer.save()

        # second, it's weak pin
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )

        self.assertEqual(response.template_name, 'julovers/reset_pin_failed.html')

        # fixed
        data = {'pin1': '133446', 'pin2': '133446'}

        # success
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )
        self.assertEqual(response.template_name, 'julovers/reset_pin_success.html')

    def test_get_confirm_pin_grab_get(self):
        app_grab = ApplicationFactory.grab()
        customer = app_grab.customer
        customer.reset_password_key = 'open_the_pod_bay_doors_HAL'
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        customer.save()
        CustomerPinFactory(user=customer.user)
        reset_link = f"/api/pin/v1/reset/confirm/{customer.reset_password_key}/?grab=true"
        # get
        response = self.client_wo_auth.get(reset_link)
        self.assertEqual(response.template_name, 'web/reset_pin_failed_grab.html')
        print(vars(response))
        self.assertEqual(
            response.request['QUERY_STRING'],
            'grab=true',
        )

    def test_get_confirm_pin_grab_post(self):
        reset_key = "im_sorry_i_cant_do_that"
        app_grab = ApplicationFactory.grab()
        customer = app_grab.customer
        customer.reset_password_key = reset_key
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        customer.save()
        pin = CustomerPinFactory(user=customer.user)
        CustomerPinChangeFactory(
            customer_pin=pin,
            email=customer.email,
            reset_key=reset_key,
        )
        reset_link = f"/api/pin/v1/reset/confirm/{customer.reset_password_key}/?grab=true"

        data = {'pin1': '123456', 'pin2': '123456'}

        # first, should be expired
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )
        self.assertEqual(response.template_name, 'web/reset_pin.html')

        # fixed
        customer.reset_password_exp_date = timezone.localtime(timezone.now()) + timedelta(days=1)
        customer.save()

        # second, it's weak pin
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )

        self.assertEqual(response.template_name, 'web/reset_pin.html')

        # fixed
        data = {'pin1': '133446', 'pin2': '133446'}

        # success
        response = self.client_wo_auth.post(
            reset_link,
            data=data,
        )
        self.assertEqual(response.template_name, 'web/reset_pin_success_grab.html')


class TestChecksStrongPinAPI(APITestCase):
    def setUp(self):
        self.client_wo_auth = APIClient()

    def test_empty_data(self):
        response = self.client_wo_auth.post('/api/pin/v1/check-strong-pin', data={})
        assert response.status_code == 400

    def test_pin_is_weakness(self):
        response = self.client_wo_auth.post(
            '/api/pin/v1/check-strong-pin', data={'nik': '3173051512900111', 'pin': '111111'}
        )
        assert response.status_code == 400

    def test_pin_is_same_with_dob(self):
        response = self.client_wo_auth.post(
            '/api/pin/v1/check-strong-pin', data={'nik': '3173051512900111', 'pin': '121590'}
        )
        assert response.status_code == 400

    def test_pin_is_strong(self):
        response = self.client_wo_auth.post(
            '/api/pin/v1/check-strong-pin', data={'nik': '3173051512900111', 'pin': '219323'}
        )
        assert response.status_code == 200

    def test_pin_is_strong_with_auth(self):
        self.client = APIClient()
        self.user = AuthUserFactory(username="3173051512900111")
        data = {
            "username": self.user.username,
            "pin": "676533",
            "email": self.user.email,
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        self.client.post('/api/pin/v1/register', data=data)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        response = self.client.post(
            '/api/pin/v1/check-strong-pin', data={'nik': '3173051512900111', 'pin': '060995'}
        )
        assert response.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestChangePinAPI(APITestCase):
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.client = APIClient()
        data = {
            "username": "1599110506206779",
            "pin": "676533",
            "email": "asdf123345@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        res = self.client.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf123345@gmail.com')
        token = self.customer.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_change_pin_empty_data(self):
        response = self.client.post('/api/pin/v1/change_pin', data={})
        assert response.status_code == 400

    def test_new_pin_is_weakness(self):
        response = self.client.post(
            '/api/pin/v1/change_pin',
            data={"username": "1599110506206779", "pin": "676533", 'new_pin': '111111'},
        )
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.PIN_IS_TOO_WEAK]

    def test_new_pin_is_the_same_with_dob(self):
        response = self.client.post(
            '/api/pin/v1/change_pin',
            data={"username": "1599110506206779", "pin": "676533", 'new_pin': '060520'},
        )
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.PIN_IS_DOB]

    def test_new_pin_is_the_same_as_old_pin(self):
        response = self.client.post(
            '/api/pin/v1/change_pin',
            data={"username": "1599110506206779", "pin": "676533", 'new_pin': '676533'},
        )
        assert response.status_code == 400
        assert response.json()['errors'] == [VerifyPinMsg.PIN_SAME_AS_OLD_PIN_FOR_CHANGE_PIN]


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginApiV2(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                'max_wait_time_mins': 60,
                'max_retry_count': 3,
                'response_message': {
                    'permanent_locked': (
                        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
                        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
                    ),
                    'temporary_locked': (
                        'Akun kamu diblokir sementara selama {eta} '
                        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
                    ),
                    'cs_contact_info': {
                        'phone': ['02150919034', '02150919035'],
                        'email': ['cs@julo.co.id'],
                    },
                },
            },
        )
        data = {
            "username": "1599110506026710",
            "pin": "865399",
            "email": "asdf123444@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }
        response = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf123444@gmail.com')
        self.customer.phone = '21312312132'

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_login_with_session_token(self, mock_send_sms_otp, mock_validate_login_otp):
        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        # otp feature is off
        response = self.client_wo_auth.post(
            '/api/pin/v3/login', data=data, **{'HTTP_X_APP_VERSION': '7.0.0'}
        )
        assert response.status_code == 200
        assert response.json()['data']['token']
        last_login_attempt = LoginAttempt.objects.filter(customer=self.customer).last()
        assert last_login_attempt.app_version == '7.0.0'

        # otp_feature is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        # customer without phone
        response = self.client_wo_auth.post('/api/pin/v3/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

        # invalid session
        application = ApplicationFactory(customer=self.customer)
        AddressGeolocationFactory(application=application)
        data['session_token'] = 'sdasdasdsagjdsajdgsajd'
        response = self.client_wo_auth.post('/api/pin/v3/login', data=data)
        assert response.status_code == 403

        # success
        otp_request = OtpRequestFactory()
        session = TemporarySessionFactory(user=self.customer.user, otp_request=otp_request)
        data['session_token'] = session.access_key
        response = self.client_wo_auth.post('/api/pin/v3/login', data=data)
        assert response.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginApiV3(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={
                'max_wait_time_mins': 60,
                'max_retry_count': 3,
                'response_message': {
                    'permanent_locked': (
                        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
                        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
                    ),
                    'temporary_locked': (
                        'Akun kamu diblokir sementara selama {eta} '
                        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
                    ),
                    'cs_contact_info': {
                        'phone': ['02150919034', '02150919035'],
                        'email': ['cs@julo.co.id'],
                    },
                },
            },
        )
        data = {
            "username": "1599110506026710",
            "pin": "865399",
            "email": "asdf123444@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
        }
        response = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf123444@gmail.com')
        self.customer.phone = '21312312132'

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_suspicious_login(self, mock_send_sms_otp, mock_validate_login_otp):
        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        # otp feature is off
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

        # otp_feature is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        # customer without phone
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 200
        assert response.json()['data']['token']

        # invalid session
        application = ApplicationFactory(customer=self.customer)
        AddressGeolocationFactory(application=application)
        data['session_token'] = 'sdasdasdsagjdsajdgsajd'
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 403

        # suspicious login
        otp_request = OtpRequestFactory()
        session = TemporarySessionFactory(user=self.customer.user, otp_request=otp_request)
        data['session_token'] = session.access_key
        data['android_id'] = '1234'
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 428

        # suspicious login validate success
        session.refresh_from_db()
        otp_request = OtpRequestFactory(
            otp_service_type='email', action_type='verify_suspicious_login'
        )
        session.otp_request = otp_request
        session.save()
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 200

        # suspicious login without email
        otp_request = OtpRequestFactory()
        session.update_safely(
            is_locked=False, require_multilevel_session=False, otp_request=otp_request
        )
        data['session_token'] = session.access_key
        data['android_id'] = '1234'
        self.customer.email = None
        self.customer.save()
        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        assert response.status_code == 200

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_partner_login_without_login_attempt_geolocation(
        self, mock_send_sms_otp: MagicMock, mock_validate_login_otp: MagicMock
    ) -> None:
        partner = PartnerFactory(name=PartnerNameConstant.LINKAJA)
        ApplicationFactory(
            customer=self.customer,
            partner=partner,
        )

        # Customer login using webview and not have geolocation
        customer_pin_attempt = CustomerPinAttemptFactory(reason='WebviewLogin')
        LoginAttemptFactory(
            customer=self.customer, is_success=True, customer_pin_attempt=customer_pin_attempt
        )

        data = {
            "username": "1599110506026710",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }

        response = self.client_wo_auth.post('/api/pin/v4/login', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['token'])

        # Loggin Attempt will be 2
        total_login_attempts = LoginAttempt.objects.filter(customer=self.customer).count()
        self.assertEqual(total_login_attempts, 2)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestResetPinv3(APITestCase):
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.client_wo_auth = APIClient()
        data = {
            "username": "1599110506026779",
            "pin": "676533",
            "email": "asdf123345@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN,
            is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days": 0, "hours": 24, "minutes": 0},
                "pin_users_link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )
        res = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.client = APIClient()
        # self.user = AuthUserFactory(password='18273612311')
        self.customer = Customer.objects.get(email='asdf123345@gmail.com')
        self.customer.phone = '085216193165'
        self.customer.save()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    def test_reset_pasword_empty_data(self):
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data={})
        assert response.status_code == 400

    def test_reset_pasword_invalid_email(self):
        data = {"email": "asdf123345@sdfgmail.cosdfm"}
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        assert response.json()['data'] == ResetMessage.PASSWORD_RESPONSE

    def test_reset_pasword_email_not_found(self):
        data = {"email": "asdf123345234@gmail.com"}
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        assert response.json()['data'] == ResetMessage.PASSWORD_RESPONSE

    @patch.object(
        JuloEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}]
    )
    @patch('juloserver.pin.tasks.send_reset_pin_email')
    def test_reset_pasword_by_email(self, mock_send_reset_password_email, mock_email):
        data = {"email": "asdf123345@gmail.com"}
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        assert response.json()['data']['message'] == ResetMessage.RESET_PIN_BY_EMAIL

        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        mock_send_reset_password_email.delay.assert_called()

        # mtl user
        customer = CustomerFactory()
        data['email'] = customer.email
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200

    @patch.object(JuloSmsClient, 'send_sms', return_value=['status', {'message': {'status': 0}}])
    @patch('juloserver.pin.tasks.send_reset_pin_sms')
    def test_reset_pasword_by_sms(self, mock_send_reset_pin_sms, mock_send_sms):
        data = {"email": None, "phone_number": '085216193'}
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        assert response.json()['data']['message'] == ResetMessage.FAILED
        data = {"email": None, "phone_number": '085216193165'}
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200
        mock_send_reset_pin_sms.delay.assert_called()

        # [customer, phone_number, reset_pin_key]

        # mtl user
        customer = CustomerFactory()
        data['email'] = customer.email
        response = self.client_wo_auth.post('/api/pin/v3/reset/request', data=data)
        assert response.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestResetPinConfirmByPhoneNumberAPI(APITestCase):
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.client_wo_auth = APIClient()
        data = {
            "username": "1599110506026770",
            "pin": "122452",
            "email": "asdf1233457@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
        }
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN,
            is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days": 0, "hours": 24, "minutes": 0},
                "pin_users_link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )
        res = self.client_wo_auth.post('/api/pin/v1/register', data=data)
        self.customer = Customer.objects.get(email='asdf1233457@gmail.com')
        session = TemporarySessionFactory(user=self.customer.user)
        data = {"customer_xid": self.customer.customer_xid, "session_token": session.access_key}
        self.client_wo_auth.post('/api/pin/v5/reset/request', data=data)
        self.customer.refresh_from_db()
        self.url_confirm_pin = (
            f"/api/pin/v1/reset-by-phone-number/confirm/{self.customer.reset_password_key}/"
        )

    def test_get_cornfirm_pin_request_wrong_key(self):
        response = self.client_wo_auth.get('/api/pin/v1/reset-by-phone-number/confirm/asd3432/')

        assert response.status_code == 400

    def test_get_confirm_pin_request(self):
        response = self.client_wo_auth.get(self.url_confirm_pin)

        assert response.status_code == 200

    def test_confirm_pin_wrong_pass(self):
        data = {'pin1': None, 'pin2': None}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_invalid_pass(self):
        data = {'pin1': 'asdf', 'pin2': 'asdf'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_is_weakness(self):
        reset_password_key = self.customer.reset_password_key
        data = {'pin1': '123456', 'pin2': '123456'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_is_same_with_dob(self):
        data = {'pin1': '050602', 'pin2': '050602'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_2_pass_diff(self):
        data = {'pin1': '133446', 'pin2': '123454'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_wrong_key(self):
        data = {'pin1': '133446', 'pin2': '133446'}
        response = self.client_wo_auth.post(
            '/api/pin/v1/reset-by-phone-number/confirm/wrongkey/', data=data
        )
        assert response.status_code == 400

    def test_confirm_pin_same_as_old_pin(self):
        data = {'pin1': '122452', 'pin2': '122452'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_invalid_payload_attribute(self):
        data = {'invalidpin1': '122452', 'invalidpin2': '122332'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 400

    def test_confirm_pin_success(self):
        data = {'pin1': '133446', 'pin2': '133446'}
        response = self.client_wo_auth.post(self.url_confirm_pin, data=data)
        assert response.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckCurrentPinV2(APITestCase):
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()

    def test_check_pin_success(self):
        data = {"pin": '123456'}
        response = self.client.post('/api/pin/v2/check-pin', data=data)
        assert response.status_code == 200
        self.assertIsNotNone(response.json()['data']['pin_validation_token'])
        pin_token = PinValidationToken.objects.filter(user=self.user).last()
        self.assertEqual(pin_token.is_active, True)

    def test_check_pin_fail(self):
        data = {"pin": '213123'}
        response = self.client.post('/api/pin/v2/check-pin', data=data)
        assert response.status_code == 401
        assert response.json()['errors'] == ['PIN yang kamu ketik tidak sesuai']


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestLoginV4(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):

        self.client = APIClient()
        self.endpoint = '/api/pin/v4/login'
        self.j1_workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        self.path_to_100 = WorkflowStatusPathFactory(
            status_previous=0, status_next=100, type='happy', workflow=self.j1_workflow
        )
        self.onboarding_jstarter = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_FORM_ID)
        self.app_version = AppVersionFactory(status='latest', app_version='8.0.0')

        self.key_toggle = JStarterToggleConst.KEY_PARAM_TOGGLE
        self.data = {
            "username": "1599110506026711",
            "password": "865399",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            self.key_toggle: JStarterToggleConst.GO_TO_PRODUCT_PICKER,
        }

    def create_account_customer(self):

        nik = '1599110506026711'
        email = 'user_register_v3@gmail.com'
        password = make_password(self.data['password'])
        self.user = AuthUserFactory(username=nik, password=password)
        self.customer = CustomerFactory(email=email, nik=nik, user=self.user)

    def login_process(self):

        response = self.client.post(self.endpoint, data=self.data)
        return response

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_login_without_application(self, mock_send_sms_otp, mock_validate_login_otp):
        """
        Test for Jstarter toggle is will go to Product Picker Screen.
        """

        self.create_account_customer()
        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']

        # otp_feature is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {'otp_max_request': 3, 'otp_resend_time': 180},
                'wait_time_seconds': 400,
            },
        )
        # customer without phone
        self.customer.phone = None
        self.customer.save()
        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']

        # suspicious login
        otp_request = OtpRequestFactory()
        session = TemporarySessionFactory(user=self.customer.user, otp_request=otp_request)

        # suspicious login validate success
        session.refresh_from_db()
        otp_request = OtpRequestFactory(
            otp_service_type='email', action_type='verify_suspicious_login'
        )
        session.otp_request = otp_request
        session.save()
        response = self.login_process()
        assert response.status_code == 200

        # suspicious login without email
        otp_request = OtpRequestFactory()
        session.update_safely(
            is_locked=False, require_multilevel_session=False, otp_request=otp_request
        )
        self.data['session_token'] = session.access_key
        self.data['android_id'] = '1234'
        self.customer.email = None
        self.customer.save()
        response = self.login_process()
        assert response.status_code == 200

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_login_without_app_and_toggle(self, mock_send_sms_otp, mock_validate_login_otp):
        """
        Test case if jstar_toogle not available and will be to create application
        (Like existing flow)
        """

        self.create_account_customer()
        self.data.pop(self.key_toggle)
        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_login_without_app_and_toggle_is_j1(
        self, mock_send_sms_otp, mock_validate_login_otp
    ):
        """
        Test case if jstar_toogle available with J1 Flow
        """

        self.create_account_customer()
        self.data['jstarter_toggle'] = JStarterToggleConst.GO_TO_APPLICATION_FORM
        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_login_without_app_jturbo_is_no_active(
        self, mock_send_sms_otp, mock_validate_login_otp
    ):
        """
        Should be not send in response application JTurbo x192
        """

        # create application JTurbo with x192
        self.create_account_customer()

        # application for J1 x190
        application_j1 = ApplicationFactory(
            workflow=self.j1_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            customer=self.customer,
        )
        application_j1.update_safely(application_status=StatusLookupFactory(status_code=190))

        # application for JTurbo x192
        application_jturbo = ApplicationFactory(
            workflow=self.jstarter_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER),
            customer=self.customer,
        )
        application_jturbo.update_safely(application_status=StatusLookupFactory(status_code=192))

        # Create data in application_upgrade table
        application_upgrade_table = ApplicationUpgradeFactory(
            application_id=application_j1.id,
            application_id_first_approval=application_jturbo.id,
            is_upgrade=1,
        )

        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']
        self.assertEqual(len(response.json()['data']['applications']), 1)
        self.assertEqual(response.json()['data']['applications'][0]['status'], 190)
        self.assertEqual(response.json()['data']['applications'][0]['product_line_code'], 1)
        self.assertTrue(response.json()['data']['is_upgrade_application'])

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_login_with_is_upgrade_false(self, mock_send_sms_otp, mock_validate_login_otp):
        """
        Should be is_upgrade_application is False
        """

        # create application JTurbo with x192
        self.create_account_customer()

        # application for J1 x190
        application_j1 = ApplicationFactory(
            workflow=self.j1_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            customer=self.customer,
        )
        application_j1.update_safely(application_status=StatusLookupFactory(status_code=190))

        # Create data in application_upgrade table
        application_upgrade_table = ApplicationUpgradeFactory(
            application_id=application_j1.id,
            application_id_first_approval=application_j1.id,
            is_upgrade=0,
        )

        response = self.login_process()
        assert response.status_code == 200
        assert response.json()['data']['token']
        self.assertEqual(len(response.json()['data']['applications']), 1)
        self.assertEqual(response.json()['data']['applications'][0]['status'], 190)
        self.assertEqual(response.json()['data']['applications'][0]['product_line_code'], 1)
        self.assertFalse(response.json()['data']['is_upgrade_application'])


class TestCustomerResetCount(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user, customer_xid='46835226736644', is_active=True
        )
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        CustomerPinFactory(user=self.user)
        pin = '159357'
        self.user.set_password(pin)
        self.user.save()
        self.pin = self.user.pin
        self.url = '/api/pin/v1/reset-count'

    def test_customer_customer_reset_invalid_serializer(self):
        data = None
        response = self.client.post(self.url, data)

        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data['errors'], ['Silakan periksa input kembali'])

    def test_customer_dosent_exists(self):
        data = {'customer_xid': '8990651301953827'}
        response = self.client.post(self.url, data)

        self.assertEquals(response.status_code, 400)
        self.assertEquals(
            response.data['errors'], [CustomerResetCountConstants.CUSTOMER_NOT_EXISTS]
        )

    def test_customer_reset_count_in_24_hrs(self):
        data = {'customer_xid': self.customer.customer_xid}

        # 1st time
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.data['data']['reset_count'], 0)

        # 2nd time
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.data['data']['reset_count'], 1)

        # 3nd time
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.data['data']['reset_count'], 2)

        # 4nd time
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.data['data']['reset_count'], 3)

        # 5nd time
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.data['data']['reset_count'], 4)

        # 6nd time
        CustomerPinChangeFactory(customer_pin=self.pin, email=self.customer.email)
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data['errors'], [CustomerResetCountConstants.MAXIMUM_EXCEEDED])

class TestLoginV5(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):

        self.client = APIClient()
        self.endpoint = '/api/pin/v5/login'
        self.j1_workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        self.data = {
            "android_id": "12b56c4365a56d6c",
            "app_version": "8.11.1",
            "gcm_reg_id": "9DftTH9u3kZf4fFcQY9cwthI",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "jstar_toggle": 1,
            "latitude": 10.054054054054054,
            "longitude": 76.32524239434301,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "password": "159357",
            "require_expire_session_token": True,
            "username": "1599110506026711"
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={
                EXPIRY_SETTING_KEYWORD: 10,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0'
            },
        )

    def create_account_customer(self):

        nik = '1599110506026711'
        email = 'user_register_v3@gmail.com'
        self.password = make_password(self.data['password'])
        self.user = AuthUserFactory(username=nik, password=self.password)
        self.customer = CustomerFactory(email=email, nik=nik, user=self.user,phone='08999999999')

    def login_process(self):
        response = self.client.post(self.endpoint, data=self.data)
        return response

    @patch('juloserver.otp.views.validate_otp')
    def test_case_success_for_new_app_version(self, mock_validate_otp):

        self.create_account_customer()
        # for case otp require verification when registration flow
        self.otp_request = OtpRequestFactory(
            customer=self.customer,
            phone_number= '08999999999',
            otp_service_type='sms',
            is_used=True,
            action_type='verify_phone_number',
        )
        otp_request_data = {
            "action_type": "login",
            "android_id": '12b56c4365a56d6c',
            "customer_xid": self.customer.customer_xid,
            "otp_token": self.otp_request.otp_token,
            "password": self.password,
            "username": self.user.username
        }
        mock_validate_otp.return_value = 'success', 'badhabhdahjgahgd'
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token,  HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/otp/v2/validate', data=otp_request_data)
        self.client.credentials(HTTP_X_APP_VERSION=self.feature_setting.parameters.get(
            REFRESH_TOKEN_MIN_APP_VERSION))
        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.otp.views.validate_otp')
    def test_case_login_for_older_app_version(self, mock_validate_otp):
        self.create_account_customer()
        # for case otp require verification when registration flow
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
            "password": self.password,
            "username": self.user.username
        }
        mock_validate_otp.return_value = 'success', 'badhabhdahjgahgd'
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token,  HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/otp/v2/validate', data=otp_request_data)
        self.client.credentials(HTTP_X_APP_VERSION='8.10.0')
        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)
        self.assertEquals(response.data['data']['auth']['token_expires_in'], None)


class TestLoginV6(APITestCase):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):

        self.client = APIClient()
        self.endpoint = '/api/pin/v6/login'
        self.j1_workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )

        self.data = {
            "android_id": "12b56c4365a56d6c",
            "app_version": "8.11.1",
            "gcm_reg_id": "9DftTH9u3kZf4fFcQY9cwthI",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "jstar_toggle": 1,
            'latitude': -6.175499,
            'longitude': 106.820512,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "password": "159357",
            "require_expire_session_token": True,
            "username": "1599110506026711",
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=False,
            parameters={
                EXPIRY_SETTING_KEYWORD: 10,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0',
            },
        )

    def create_account_customer(self, set_wrong_password=False):

        nik = '1599110506026711'
        email = 'user_register_v3@gmail.com'
        self.password = make_password(self.data['password'])
        password = self.password
        if set_wrong_password:
            password = 'testing'
        self.user = AuthUserFactory(username=nik, password=password)
        self.customer = CustomerFactory(email=email, nik=nik, user=self.user, phone='08999999999')

    def login_process(self):
        response = self.client.post(self.endpoint, data=self.data)
        return response

    @patch('juloserver.otp.views.validate_otp')
    def test_case_success_for_new_app_version(self, mock_validate_otp):

        self.create_account_customer()
        # for case otp require verification when registration flow
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
            "password": self.password,
            "username": self.user.username,
        }
        mock_validate_otp.return_value = 'success', 'badhabhdahjgahgd'
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token, HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/otp/v2/validate', data=otp_request_data)
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )
        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.otp.views.validate_otp')
    def test_case_login_for_older_app_version(self, mock_validate_otp):
        self.create_account_customer()
        # for case otp require verification when registration flow
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
            "password": self.password,
            "username": self.user.username,
        }
        mock_validate_otp.return_value = 'success', 'badhabhdahjgahgd'
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token, HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/otp/v2/validate', data=otp_request_data)
        self.client.credentials(HTTP_X_APP_VERSION='8.10.0')
        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)
        self.assertEquals(response.data['data']['auth']['token_expires_in'], None)

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_login_attempt(self, mock_sms_validate_otp, mock_login_otp):

        self.create_account_customer()

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )
        self.data.pop('latitude')
        self.data.pop('longitude')
        response = self.login_process()
        self.assertEqual(response.status_code, 200)

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 1)
        self.assertIsNone(login_attempt.last().latitude)
        self.assertIsNone(login_attempt.last().longitude)
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_login_attempt_and_latitude_longitude(
        self, mock_sms_validate_otp, mock_login_otp
    ):

        self.create_account_customer()

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )

        response = self.login_process()
        self.assertEqual(response.status_code, 200)

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 1)
        self.assertEqual(login_attempt.last().latitude, self.data['latitude'])
        self.assertEqual(login_attempt.last().longitude, self.data['longitude'])
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_login_attempt_with_wrong_password(
        self, mock_sms_validate_otp, mock_login_otp
    ):

        self.create_account_customer(set_wrong_password=True)

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )

        response = self.login_process()
        self.assertEqual(response.status_code, 400)

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 1)
        self.assertEqual(login_attempt.last().latitude, self.data['latitude'])
        self.assertEqual(login_attempt.last().longitude, self.data['longitude'])
        self.assertIsNone(login_attempt.last().is_success)

    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_login_attempt_with_have_application_data(
        self, mock_sms_validate_otp, mock_login_otp
    ):

        self.create_account_customer()

        # application for J1 x190
        application = ApplicationFactory(
            workflow=self.j1_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            customer=self.customer,
        )
        application.update_safely(application_status=StatusLookupFactory(status_code=100))

        # Create data in application_upgrade table
        application_upgrade_table = ApplicationUpgradeFactory(
            application_id=application.id,
            application_id_first_approval=application.id,
            is_upgrade=0,
        )

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )

        response = self.login_process()
        self.assertEqual(response.status_code, 200)

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 1)
        self.assertEqual(login_attempt.last().latitude, self.data['latitude'])
        self.assertEqual(login_attempt.last().longitude, self.data['longitude'])
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

        # Double check with feature setting expiry is active
        self.feature_setting.update_safely(is_active=True)

        response = self.login_process()
        self.assertEqual(response.status_code, 200)

        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 2)
        self.assertEqual(login_attempt.last().latitude, self.data['latitude'])
        self.assertEqual(login_attempt.last().longitude, self.data['longitude'])
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_last_login_attempt_null_latitude_longitude(
        self,
        mock_sms_validate_otp,
        mock_login_otp,
        mock_address_geolocation,
    ):
        self.create_account_customer()

        customer_pin_attempt = CustomerPinAttemptFactory(reason='LoginV6')
        LoginAttemptFactory(
            customer=self.customer,
            latitude=None,
            longitude=None,
            is_success=True,
            customer_pin_attempt=customer_pin_attempt,
        )

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )

        # application for J1 x190
        application = ApplicationFactory(
            workflow=self.j1_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            customer=self.customer,
        )
        application.update_safely(application_status=StatusLookupFactory(status_code=100))

        # Create data in application_upgrade table
        application_upgrade_table = ApplicationUpgradeFactory(
            application_id=application.id,
            application_id_first_approval=application.id,
            is_upgrade=0,
        )

        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        assert mock_address_geolocation.called

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 2)
        self.assertEqual(login_attempt.last().latitude, self.data['latitude'])
        self.assertEqual(login_attempt.last().longitude, self.data['longitude'])
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_condition_address_geolocation(
        self,
        mock_sms_validate_otp,
        mock_login_otp,
        mock_address_geolocation,
    ):
        self.create_account_customer()

        # application for J1 x190
        application = ApplicationFactory(
            workflow=self.j1_workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            customer=self.customer,
        )
        application.update_safely(application_status=StatusLookupFactory(status_code=100))

        # Create data in application_upgrade table
        application_upgrade_table = ApplicationUpgradeFactory(
            application_id=application.id,
            application_id_first_approval=application.id,
            is_upgrade=0,
        )

        # for case otp require verification when registration flow
        self.client.credentials(
            HTTP_X_APP_VERSION=self.feature_setting.parameters.get(REFRESH_TOKEN_MIN_APP_VERSION)
        )

        self.data.pop('latitude')
        self.data.pop('longitude')

        response = self.login_process()
        self.assertEqual(response.status_code, 200)
        assert not mock_address_geolocation.called

        # check login attempt
        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 1)
        self.assertIsNone(login_attempt.last().latitude)
        self.assertIsNone(login_attempt.last().longitude)
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

        # Double check with feature setting expiry is active
        self.feature_setting.update_safely(is_active=True)

        response = self.login_process()
        self.assertEqual(response.status_code, 200)

        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id)
        self.assertEqual(login_attempt.count(), 2)
        self.assertIsNone(login_attempt.last().latitude)
        self.assertIsNone(login_attempt.last().longitude)
        self.assertTrue(login_attempt.last().is_success)

        # for version refresh token
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEquals(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)


class TestLoginV7(TestLoginV6):
    @patch('juloserver.pin.services.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):

        self.client = APIClient()
        self.endpoint = '/api/pin/v7/login'
        self.j1_workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        self.j1_ios_workflow = WorkflowFactory(
            name='JuloOneIOSWorkflow', handler='JuloOneIOSWorkflowHandler'
        )
        self.data = {
            "android_id": "",
            "app_version": "8.11.1",
            "gcm_reg_id": "9DftTH9u3kZf4fFcQY9cwthI",
            "is_rooted_device": False,
            "is_suspicious_ip": True,
            "jstar_toggle": 1,
            'latitude': -6.175499,
            'longitude': 106.820512,
            "manufacturer": "Redmi",
            "model": "Redmi",
            "password": "159357",
            "require_expire_session_token": True,
            "username": "1599110506026711",
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=False,
            parameters={
                EXPIRY_SETTING_KEYWORD: 10,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0',
            },
        )

        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'

        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0.0',
            'HTTP_X_APP_VERSION': '1.0.1',
        }
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.j1_ios_workflow,
        )

    def _login_process(self, header={}):
        response = self.client.post(self.endpoint, format='json', data=self.data, **header)
        return response

    @patch('juloserver.otp.views.validate_otp')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    def test_case_success_login_with_ios_device(
        self,
        mock_sms_validate_otp,
        mock_login_otp,
        mock_address_geolocation,
        mock_validate_otp,
    ):

        self.create_account_customer()

        # for case otp require verification when registration flow
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
            "password": self.password,
            "username": self.user.username,
        }

        mock_validate_otp.return_value = 'success', 'badhabhdahjgahgd'
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token, HTTP_TOKEN_VERSION=1.0)
        response = self.client.post('/api/otp/v2/validate', data=otp_request_data)

        # try to login
        response = self._login_process(self.new_device_header)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth", 1)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertEqual(response.data['data']['auth']['refresh_token'], expiry_token.refresh_key)

        device = Device.objects.filter(pk=response.json()['data']['device_id']).last()
        self.assertIsNotNone(device)
        self.assertEqual(device.ios_id, self.ios_id)

        login_attempt = LoginAttempt.objects.filter(customer_id=self.customer.id).last()
        self.assertIsNotNone(login_attempt)
        self.assertEqual(login_attempt.ios_id, self.ios_id)
