import base64
import io
import json

import ulid
import hashlib

from datetime import timedelta, datetime

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone
from mock import patch
from PIL import Image as image_pil
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import MagicMock

from juloserver.account.tests.factories import AccountFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import FeatureSetting, AuthUser, Image, Application, OtpRequest
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ImageFactory,
    ProvinceLookupFactory,
    CityLookupFactory,
    DistrictLookupFactory,
    SubDistrictLookupFactory,
    LoanPurposeFactory,
    BankFactory,
    OtpRequestFactory,
    FeatureSettingFactory,
    ApplicationHistoryFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.otp.constants import OTPRequestStatus, OTPValidateStatus
from juloserver.partnership.constants import (
    PartnershipFlag,
    PartnershipFeatureNameConst,
    PartnershipHttpStatusCode,
    PartnershipTokenType,
)
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.leadgenb2b.constants import (
    LeadgenFeatureSetting,
    LeadgenStandardApplicationFormType,
    LeadgenStandardRejectReason,
)
from juloserver.partnership.models import (
    PartnershipFlowFlag,
    PartnershipFeatureSetting,
    PartnershipUserOTPAction,
)
from juloserver.partnership.constants import (
    PartnershipFlag,
    PartnershipFeatureNameConst,
    PartnershipTokenType,
)
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.partnership.models import (
    PartnershipFlowFlag,
    PartnershipFeatureSetting,
    LivenessResultsMapping,
    PartnershipApplicationFlag,
)
from juloserver.partnership.liveness_partnership.constants import (
    LivenessType,
)
from juloserver.partnership.tests.factories import (
    LivenessResultsMappingFactory,
    PartnershipApplicationFlagFactory,
)
from juloserver.partnership.liveness_partnership.constants import (
    LivenessResultMappingStatus,
)
from juloserver.partnership.liveness_partnership.tests.factories import (
    LivenessConfigurationFactory,
    LivenessResultFactory,
)
from juloserver.partnership.liveness_partnership.utils import generate_api_key
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.pin.models import RegisterAttemptLog
from juloserver.pin.services import CustomerPinService
from juloserver.pin.tests.factories import LoginAttemptFactory, CustomerPinAttemptFactory
from juloserver.otp.constants import SessionTokenAction

from PIL import Image as PilImage


class TestRegisterView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.payload = {
            'nik': "5171042804630001",
            'pin': "456789",
            'email': "prod.only@julofinance.com",
            'latitude': '6.12',
            'longitude': '12.6',
            'partnerName': self.partner_name,
            'tnc': True,
        }
        self.client = APIClient()
        self.endpoint = f'/api/leadgen/register'

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": False}},
        )

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.generate_address_from_geolocation_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.create_application_checklist_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.process_application_status_change'
    )
    def test_success_register(
        self,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        # Check if async tasks generated
        mock_process_application_status_change.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        mock_generate_address_from_geolocation_async.delay.assert_called_once()

    def test_not_leadgen_partner(self):
        self.payload['partnerName'] = 'efishery'
        PartnerFactory(name='efishery', is_active=True)

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)

    def test_user_exists(self):
        User.objects.create(username=self.payload.get('nik'), email=self.payload.get('email'))

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_check_strong_pin(self):
        self.payload['pin'] = '123456'

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response.status_code)

    def test_invalid_data(self):
        self.payload['latitude'] = 'aaaaa'
        self.payload['longitude'] = 'bbb'

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response.status_code)

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.generate_address_from_geolocation_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.create_application_checklist_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.process_application_status_change'
    )
    def test_no_location(
        self,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        del self.payload['latitude']
        del self.payload['longitude']

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(200, response.status_code)

        # Check if async tasks generated
        mock_process_application_status_change.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        assert not mock_generate_address_from_geolocation_async.delay.called

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.generate_address_from_geolocation_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.create_application_checklist_async'
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.process_application_status_change'
    )
    def test_token(
        self,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        jwt = JWTManager()
        jwt_payload = {
            'type': PartnershipTokenType.OTP_REGISTER_VERIFICATION,
            'exp': datetime.now(timezone.utc) + timedelta(seconds=1440),
            'iat': datetime.now(timezone.utc),
            'email': self.payload.get('email'),
            'nik': self.payload.get('nik'),
            'otp_request_id': '1232342',
        }
        PartnershipFeatureSetting.objects.create(
            feature_name=PartnershipFeatureNameConst.LEADGEN_STANDARD_GOOGLE_OAUTH_REGISTER_PARTNER,
            is_active=True,
            parameters={'partners': []},
        )

        # Without token, should return error
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(403, response.status_code)

        # With invalid token, should return error
        self.payload['token'] = '1312132asasa'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response.status_code)

        # With invalid request_id, should return error
        raw_token = jwt.encode_token(jwt_payload)
        self.payload['token'] = raw_token.decode('utf-8')
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        # With partneship otp status not used, should return error
        otp_request = OtpRequestFactory()
        partnership_otp = PartnershipUserOTPAction.objects.create(
            otp_request=otp_request.id,
            request_id='1234aadf2',
            otp_service_type='email',
            action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
            is_used=False,
        )
        jwt_payload['otp_request_id'] = partnership_otp.request_id
        raw_token = jwt.encode_token(jwt_payload)
        self.payload['token'] = raw_token.decode('utf-8')
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        partnership_otp.update_safely(is_used=True)
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        # Check if async tasks generated
        mock_process_application_status_change.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        mock_generate_address_from_geolocation_async.delay.assert_called_once()


class TestLeadgenConfigsView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOGO: {"logoUrl": "https://xxxxxxxxx"},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LONG_FORM: {
                    "formSections": {
                        "ktpAndSelfiePhoto": {
                            "isHideSection": False,
                            "hiddenFields": ["dependent", "occupiedSince", "homeStatus"],
                        },
                        "personalData": {"isHideSection": True, "hiddenFields": []},
                        "domicileInformation": {"isHideSection": False, "hiddenFields": []},
                        "personalContactInformation": {"isHideSection": False, "hiddenFields": []},
                        "partnerContact": {"isHideSection": False, "hiddenFields": []},
                        "parentsContact": {"isHideSection": False, "hiddenFields": []},
                        "emergencyContact": {"isHideSection": False, "hiddenFields": []},
                        "jobInformation": {
                            "isHideSection": False,
                            "hiddenFields": ["companyPhoneNumber"],
                        },
                        "incomeAndExpenses": {"isHideSection": False, "hiddenFields": []},
                        "bankAccountInformation": {"isHideSection": False, "hiddenFields": []},
                        "referralCode": {"isHideSection": False, "hiddenFields": []},
                    }
                },
            },
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/configs'

    def test_success_get_config(self):
        response = self.client.get(self.endpoint, data={'partner_name': self.partner_name})
        leadgen_partner_config = (
            PartnershipFlowFlag.objects.filter(
                partner__name=self.partner_name,
                name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            )
            .values_list("configs", flat=True)
            .last()
        )
        long_form_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LONG_FORM)
        logo_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOGO)
        location_config = leadgen_partner_config.get(PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION)
        expected_result = {}
        expected_result['data'] = {
            'partnerName': self.partner_name,
            'formSections': long_form_config.get("formSections"),
            'logoUrl': logo_config.get("logoUrl"),
            'isRequiredLocation': location_config.get("isRequiredLocation"),
            'isEnableGoogleOAuth': False,
        }
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertDictEqual(expected_result, response.json())

    def test_failed_get_config(self):
        query_params = {'partner_name': 'tes'}
        response = self.client.get(self.endpoint, data={'partner_name': 'tes'}, params=query_params)
        self.assertEqual(response.json(), {'message': 'Data Tidak Ditemukan'})
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_failed_not_allowed_partner(self):
        test_partner_name = 'test'
        query_params = {'partner_name': test_partner_name}
        partner = PartnerFactory(name=test_partner_name, is_active=True)
        PartnershipFlowFlag.objects.get_or_create(
            partner=partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True},
            },
        )
        response = self.client.get(
            self.endpoint, data={'partner_name': test_partner_name}, params=query_params
        )
        self.assertEqual(response.json(), {'message': 'Data Tidak Ditemukan'})
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


class TestLoginView(TestCase):
    def setUp(self):
        self.redis_data = {}
        self.partner_name = PartnerNameConstant.LINKAJA
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.payload = {
            'username': "5171042804630001",
            'pin': "452123",
            'latitude': "6.12",
            'longitude': "12.6",
            'partnerName': self.partner_name,
        }
        self.client = APIClient()
        self.endpoint = '/api/leadgen/login'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()

        self.customer = CustomerFactory(
            user=self.user_auth, email='prod.only@julofinance.com', nik='5171042804630001'
        )

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True}},
        )
        PartnershipFeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.PIN_CONFIG,
            category="leadgen_standard",
            parameters={
                "max_retry_count": 3,
                "max_block_number": 3,
                "max_wait_time_mins": 180,
            },
            description="FeatureSettings to determine standard leadgen pin config",
        )

    def set_redis(self, key, val, expire_time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data.get(key)

    @patch("juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client")
    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_success_login(self, mock_view_redis, mock_redis):
        mock_redis.return_value.get.return_value = None
        mock_view_redis.return_value.get.return_value = None

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        token = response.json().get('data', {}).get('token')
        self.assertIsNotNone(token)

    def test_no_location(self):
        self.payload['latitude'] = ""
        del self.payload['longitude']

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(400, response.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client")
    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_username(self, mock_view_redis, mock_redis):
        mock_redis.return_value.get.return_value = None
        mock_view_redis.return_value.get.return_value = None

        # Username using email
        self.payload['username'] = "prod.only@julofinance.com"
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        # Username neither NIK or Email
        self.payload['username'] = "wrong username"
        response2 = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response2.status_code)

        # missing mandatory key
        del self.payload['username']
        response3 = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(400, response3.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client")
    def test_customer_not_found(self, mock_redis):
        mock_redis.return_value.get.return_value = None

        # Not registered email
        self.payload['username'] = "not-registered@email.com"
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response.status_code)

        # Customer not active
        self.customer.is_active = False
        self.customer.save()
        self.payload['username'] = "5171042804630001"
        response2 = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response2.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client")
    def test_application(self, mock_redis):
        mock_redis.return_value = self.redis_data

        # Login with J1 Customer, expect to fail
        j1_customer = CustomerFactory(email='j1.only@julofinance.com')
        ApplicationFactory(
            customer=j1_customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
        )

        self.payload['username'] = j1_customer.email
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response.status_code)

        # Login with leadgen customer that have other application with status 105
        # Expect to fail
        self.payload['username'] = '5171042804630001'
        partner = PartnerFactory(name='myim3', is_active=True)
        ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL),
            partner=partner,
        )
        response2 = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(422, response2.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client")
    def test_block_after_three_attempts(self, mock_redis):
        mock_redis.return_value.get.side_effect = self.get_redis
        mock_redis.return_value.set.side_effect = self.set_redis
        self.payload['username'] = "not-registered@email.com"

        for _ in range(3):
            self.client.post(self.endpoint, data=self.payload, format='json')

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(429, response.status_code)


class TestLeadgenLoginOtpRequestView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.payload = {'isRefetchOtp': True}
        self.client = APIClient()
        self.endpoint = f"/api/leadgen/otp/login/request"

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        PartnershipFeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            category="leadgen_standard",
            parameters={
                "email": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
            },
            description="FeatureSettings to determine standard leadgen otp settings",
        )

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.OTP_LOGIN_VERIFICATION

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return 'Bearer {}'.format(access.token)

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token.delay')
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_success_login(self, mock_get_redis_client, mock_send_email):
        self.payload = {'isRefetchOtp': False}
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_send_email.assert_called_once()

    def test_failed_auth(self):
        # no auth
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

        # wrong token
        token = self._create_token(
            self.customer,
            self.partner_name,
            self.application,
            token_type=PartnershipTokenType.ACCESS_TOKEN,
        )
        response2 = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response2.status_code)

    def test_invalid_data(self):
        self.payload = {'isRefetchOtp': ""}
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(400, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_inactive_otp_setting(self, mock_generate_otp):
        mock_generate_otp.return_value = OTPRequestStatus.FEATURE_NOT_ACTIVE, {}
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_otp_request_limit_exceed(self, mock_generate_otp):
        mock_generate_otp.return_value = OTPRequestStatus.LIMIT_EXCEEDED, {}
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token.delay')
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_request_resend_time_insufficient(self, mock_get_redis_client, mock_send_email):
        mock_get_redis_client.return_value.get_list.side_effect = {}
        self.payload = {'isRefetchOtp': False}
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(200, response.status_code)

        self.payload = {'isRefetchOtp': True}
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(PartnershipHttpStatusCode.HTTP_425_TOO_EARLY, response.status_code)
        mock_send_email.assert_called_once()


class TestLeadgenStandardResetPin(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/pin/reset'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()
        self.customer = CustomerFactory(user=self.user_auth)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        jwt = JWTManager(
            user=self.user_auth,
            partner_name=self.partner.name,
            application_xid=self.application.application_xid,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.RESET_PIN_TOKEN)
        self.query_params = {
            'token': access.token,
        }

    def test_success_change_pin(self):
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        payload = {
            'pin': "452125",
            'confirmPin': "452125",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

    def test_user_has_no_pin(self):
        payload = {
            'pin': "452125",
            'confirmPin': "452125",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_incorrect_confirmation_pin(self):
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        payload = {
            'pin': "452125",
            'confirmPin': "452124",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_user_pin_is_same_as_old_one(self):
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        payload = {
            'pin': "452123",
            'confirmPin': "452123",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )


class TestLeadgenLoginOtpVerifyView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.client = APIClient()
        self.endpoint = f"/api/leadgen/otp/login/verify"

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        self.partnership_flow_flag, _ = PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": False}},
        )
        PartnershipFeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            category="leadgen_standard",
            parameters={
                "email": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
            },
            description="FeatureSettings to determine standard leadgen otp settings",
        )

        self.otp = OtpRequestFactory(
            action_type=SessionTokenAction.LOGIN,
            is_active=True,
            customer=self.customer,
            otp_service_type="email",
        )
        self.payload = {
            "otp": self.otp.otp_token,
            "latitude": "-6.2455808",
            "longitude": "106.8302336",
        }
        customer_pin_attempt = CustomerPinAttemptFactory(reason='LeadgenLoginView')
        LoginAttemptFactory(
            customer=self.customer,
            latitude=self.payload["latitude"],
            longitude=self.payload["longitude"],
            customer_pin_attempt=customer_pin_attempt,
        )

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.OTP_LOGIN_VERIFICATION

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return 'Bearer {}'.format(access.token)

    def test_success_verify_otp(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_failed_auth(self):
        # no auth
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response.status_code)

        # wrong token
        token = self._create_token(
            self.customer,
            self.partner_name,
            self.application,
            token_type=PartnershipTokenType.ACCESS_TOKEN,
        )
        response2 = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(status.HTTP_401_UNAUTHORIZED, response2.status_code)

    def test_invalid_data(self):
        self.payload['otp'] = ""
        self.payload['latitude'] = "aaa"

        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(400, response.status_code)

    def test_no_location(self):
        self.payload['latitude'] = ""
        del self.payload['longitude']

        # location not required
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(200, response.status_code)

        # location required
        self.partnership_flow_flag.configs = {
            PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True}
        }
        self.partnership_flow_flag.save()
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(400, response.status_code)

    def test_used_otp_token(self):
        self.otp.is_used = True
        self.otp.save()

        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(422, response.status_code)
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

    def test_expired_otp_token(self):
        self.otp.cdate = self.otp.cdate - relativedelta(seconds=1440)
        self.otp.save()

        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        self.assertEqual(422, response.status_code)
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_EXPIRED

    def test_otp_failed(self):
        self.payload['otp'] = '341423'

        # 1st try
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        assert 422 == response.status_code
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

        # 2nd try
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        message = response.json().get('message')
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_ATTEMPT_FAILED
        assert message == err_message.format(attempt_left=1)

        # 3rd try
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        message = response.json().get('message')
        assert 422 == response.status_code
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        assert message == err_message.format(max_attempt=3)

        # 4th try
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        assert 429 == response.status_code
        message = response.json().get('message')
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        assert message == err_message.format(max_attempt=3)

    def test_otp_is_used(self):
        # No otp request record
        customer = CustomerFactory(email='failed-prod.only@julofinance.com')
        ApplicationFactory(
            customer=customer,
        )
        customer_pin_attempt = CustomerPinAttemptFactory(reason='LeadgenLoginView')
        LoginAttemptFactory(
            customer=customer,
            latitude=self.payload["latitude"],
            longitude=self.payload["longitude"],
            customer_pin_attempt=customer_pin_attempt,
        )

        token = self._create_token(customer, self.partner_name, self.application)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        assert 422 == response.status_code
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

        # OTP is used
        self.otp.update_safely(is_used=True)
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=token)
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR


class TestChangePinVerification(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/pin/verify'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()
        self.customer = CustomerFactory(user=self.user_auth)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        jwt = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = 'Bearer {}'.format(access.token)

    def test_success_pin_verification(self):
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

    def test_user_has_no_pin(self):
        self.payload = {
            'pin': "123123",
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(422, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.sliding_window_rate_limit')
    def test_wrong_pin(self, mock_sliding_window_rate_limit):
        mock_sliding_window_rate_limit.return_value = False
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "123123",
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(422, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.sliding_window_rate_limit')
    def test_max_attempt_pin(self, mock_sliding_window_rate_limit):
        mock_sliding_window_rate_limit.return_value = True
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "123123",
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)


class TestLeadgenSubmitMandatoryDocsView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.client = APIClient()
        self.endpoint = "/api/leadgen/additional-documents/submit"

        self.customer = CustomerFactory()

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=120,
            status_next=121,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            ),
            partner=self.partner,
        )
        self.application.update_safely(application_status_id=120)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        self.payslip = ImageFactory(
            image_type='payslip', image_status=-1, image_source=self.application.id
        )
        self.bank_statement = ImageFactory(
            image_type='bank_statement', image_status=-1, image_source=self.application.id
        )
        self.payload = {"payslip": self.payslip.id, "bankStatement": self.bank_statement.id}

        # Create JWT token
        jwt = JWTManager(
            user=self.customer.user,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = 'Bearer {}'.format(access.token)

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.views.fraud_bpjs_or_bank_scrape_checking.apply_async'
    )
    def test_success_submit_mandocs(self, mock_fraud_checking):
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

        payslip = Image.objects.filter(id=self.payslip.id).last()
        assert payslip.image_status == 0

        bank_statement = Image.objects.filter(id=self.bank_statement.id).last()
        assert bank_statement.image_status == 0

        mock_fraud_checking.assert_called_once()

        application = Application.objects.filter(id=self.application.id).last()
        assert application.status == 121

    def test_invalid_data(self):

        # invalid image id
        self.payload['payslip'] = "qaaa"
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        # image not found
        self.payload['payslip'] = 2312321
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        # empty data
        self.payload['payslip'] = None
        self.payload['bankStatement'] = None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        # Invalid application status
        self.application.update_safely(application_status_id=105)
        self.payload['payslip'] = self.payslip.id
        self.payload['bankStatement'] = self.bank_statement.id
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


class TestLeadgenRegisterOtpVerifyView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.SMARTFREN
        self.client = APIClient()
        self.endpoint = "/api/leadgen/otp/register/verify"

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        self.feature_settings, _ = PartnershipFeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            category="leadgen_standard",
            parameters={
                "email": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 300,
                    "otp_expired_time": 1440,
                },
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 300,
                    "otp_expired_time": 1440,
                },
            },
            description="FeatureSettings to determine standard leadgen otp settings",
        )

        data_request_id = "{}:{}".format("prod.only@julofinance.com", "5171042804630001")
        hashing_request_id = hashlib.sha256(data_request_id.encode()).digest()
        self.request_id = base64.urlsafe_b64encode(hashing_request_id).decode()

        self.otp = OtpRequest.objects.create(
            request_id=self.request_id,
            otp_token="123456",
            email="prod.only@julofinance.com",
            otp_service_type="email",
            action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
        )

        self.partnership_otp = PartnershipUserOTPAction.objects.create(
            otp_request=self.otp.id,
            request_id=self.request_id,
            otp_service_type='email',
            action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
            is_used=False,
        )

        self.payload = {
            'requestId': self.request_id,
            'nik': "5171042804630001",
            'email': "prod.only@julofinance.com",
            'otp': self.otp.otp_token,
        }

    def test_success_verify_otp(self):
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        response_body = response.json()
        self.assertIsNotNone(response_body.get('data', {}).get('token'))

        otp = OtpRequest.objects.get_or_none(request_id=self.request_id)
        self.assertTrue(otp.is_used)

        partnership_otp = PartnershipUserOTPAction.objects.filter(request_id=self.request_id).last()
        self.assertTrue(partnership_otp.is_used)

    def test_invalid_data(self):

        # Invalid OTP token
        self.payload['otp'] = ""
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

        # Invalid requestId
        self.payload['otp'] = self.otp.otp_token
        self.payload['requestId'] = "13sdadsfu213132"
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

        # Invalid email
        self.payload['requestId'] = self.request_id
        self.payload['email'] = "prod.only@"
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

    def test_used_otp_token(self):
        self.otp.update_safely(is_used=True)
        self.partnership_otp.update_safely(is_used=True)
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(422, response.status_code)
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

    def test_expired_otp_token(self):
        self.otp.cdate = self.otp.cdate - relativedelta(seconds=1440)
        self.otp.save()

        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(422, response.status_code)
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_EXPIRED

    def test_otp_failed(self):
        self.payload['otp'] = '341423'

        # 1st try
        response = self.client.post(self.endpoint, data=self.payload)
        assert 422 == response.status_code
        message = response.json().get('message')
        assert message == LeadgenStandardRejectReason.OTP_VALIDATE_GENERAL_ERROR

        # 2nd try
        response = self.client.post(self.endpoint, data=self.payload)
        message = response.json().get('message')
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_ATTEMPT_FAILED
        assert message == err_message.format(attempt_left=1)

        # 3rd try
        response = self.client.post(self.endpoint, data=self.payload)
        message = response.json().get('message')
        assert 422 == response.status_code
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        assert message == err_message.format(max_attempt=3)

        # 4th try
        response = self.client.post(self.endpoint, data=self.payload)
        assert 429 == response.status_code
        message = response.json().get('message')
        err_message = LeadgenStandardRejectReason.OTP_VALIDATE_MAX_ATTEMPT
        assert message == err_message.format(max_attempt=3)


class TestLeadgenRegisterOtpRequestView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.SMARTFREN

        self.payload = {
            'isRefetchOtp': False,
            'nik': "5171042804630001",
            'email': "prod.only@julofinance.com",
        }
        self.client = APIClient()
        self.endpoint = "/api/leadgen/otp/register/request"

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        self.feature_settings, _ = PartnershipFeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            category="leadgen_standard",
            parameters={
                "email": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 300,
                    "otp_expired_time": 1440,
                },
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 300,
                    "otp_expired_time": 1440,
                },
            },
            description="FeatureSettings to determine standard leadgen otp settings",
        )

        self.redis_data = {}

        data_request_id = "{}:{}".format(self.payload['email'], self.payload['nik'])
        hashing_request_id = hashlib.sha256(data_request_id.encode()).digest()
        self.request_id = base64.urlsafe_b64encode(hashing_request_id).decode()

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token_register.delay'
    )
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_success_otp_request(self, mock_get_redis_client, mock_send_email):
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_get_redis_client.assert_called_once()
        mock_send_email.assert_called_once()

        otp_request = OtpRequest.objects.filter(
            email=self.payload['email'],
            action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
        )
        self.assertTrue(otp_request.exists())

        otp_request_id = otp_request.last().id
        partnership_user_otp_action = PartnershipUserOTPAction.objects.filter(
            otp_request=otp_request_id,
            action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
        ).exists()
        self.assertTrue(partnership_user_otp_action)

    def test_invalid_data(self):
        # Invalid isRefetchOtp
        self.payload['isRefetchOtp'] = ""
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

        # Invalid nik
        self.payload['isRefetchOtp'] = False
        self.payload['nik'] = "aaaaa"
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

        # Invalid email
        self.payload['nik'] = "5171042804630001"
        self.payload['email'] = "budi.leadgen"
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(400, response.status_code)

    def test_inactive_otp_setting(self):
        self.feature_settings.is_active = False
        self.feature_settings.save()
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token_register.delay'
    )
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_request_resend_time_insufficient(self, mock_get_redis_client, mock_send_email):
        mock_get_redis_client.return_value.get_list.side_effect = {}
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(200, response.status_code)

        self.payload['isRefetchOtp'] = True
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(PartnershipHttpStatusCode.HTTP_425_TOO_EARLY, response.status_code)

        self.assertEqual(2, mock_get_redis_client.call_count)
        mock_send_email.assert_called_once()

    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token_register.delay'
    )
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_request_limit_exceed(self, mock_get_redis_client, mock_send_email):
        for _ in range(3):
            old_otp = OtpRequestFactory(request_id=self.request_id)
            old_partnership_otp = PartnershipUserOTPAction.objects.create(
                otp_request=old_otp.id,
                request_id=self.request_id,
                otp_service_type="email",
                action_type=SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
                is_used=False,
            )
            old_partnership_otp.cdate = timezone.localtime(old_partnership_otp.cdate) - timedelta(
                seconds=60
            )
            old_partnership_otp.save()

        redis_key = 'leadgen_otp_request_register_blocked:{}:{}'.format(
            self.payload['email'], SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL
        )
        self.set_redis(redis_key, True)
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        self.payload['isRefetchOtp'] = True
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

        mock_send_email.assert_not_called()


class TestChangePinOTPRequestView(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/otp/change-pin/request'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()
        self.customer = CustomerFactory(user=self.user_auth)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        jwt = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = 'Bearer {}'.format(access.token)
        self.otp_data = {}

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_success_request_change_pin(self, mock_leadgen_generate_otp):
        mock_leadgen_generate_otp.return_value = (None, self.otp_data)
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        self.payload = {
            'pin': "452123",
            'isRefetchOtp': True,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_user_has_no_pin(self):
        self.payload = {
            'pin': "123123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.sliding_window_rate_limit')
    def test_wrong_pin(self, mock_sliding_window_rate_limit):
        mock_sliding_window_rate_limit.return_value = False
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "123123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.sliding_window_rate_limit')
    def test_wrong_pin_max_attempt(self, mock_sliding_window_rate_limit):
        mock_sliding_window_rate_limit.return_value = True
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "123123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_feature_setting_not_active(self, mock_leadgen_generate_otp):
        mock_leadgen_generate_otp.return_value = (
            OTPRequestStatus.FEATURE_NOT_ACTIVE,
            self.otp_data,
        )
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)

        self.payload = {
            'pin': "452123",
            'isRefetchOtp': True,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_otp_request_limit_exceed(self, mock_leadgen_generate_otp):
        mock_leadgen_generate_otp.return_value = (OTPRequestStatus.LIMIT_EXCEEDED, self.otp_data)
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

        self.payload = {
            'pin': "452123",
            'isRefetchOtp': True,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_otp_request_insufficient_time(self, mock_leadgen_generate_otp):
        mock_leadgen_generate_otp.return_value = (
            OTPRequestStatus.RESEND_TIME_INSUFFICIENT,
            self.otp_data,
        )
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(PartnershipHttpStatusCode.HTTP_425_TOO_EARLY, response.status_code)

        self.payload = {
            'pin': "452123",
            'isRefetchOtp': True,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(PartnershipHttpStatusCode.HTTP_425_TOO_EARLY, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_generate_otp')
    def test_otp_request_invalid_path(self, mock_leadgen_generate_otp):
        mock_leadgen_generate_otp.return_value = (
            'INVALID_OTP_PATH',
            self.otp_data,
        )
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        self.payload = {
            'pin': "452123",
            'isRefetchOtp': False,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

        self.payload = {
            'pin': "452123",
            'isRefetchOtp': True,
        }
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


@override_settings(
    PARTNERSHIP_LIVENESS_ENCRYPTION_KEY='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
)
class TestLeadgenSubmitLivenessView(TestCase):
    def setUp(self):
        client_id = ulid.new()
        self.liveness_configuration = LivenessConfigurationFactory(
            client_id=client_id.uuid,
            partner_id=1,
            detection_types={
                LivenessType.PASSIVE: True,
                LivenessType.SMILE: True,
            },
            platform='web',
            is_active=True,
        )
        self.liveness_configuration.cdate = datetime(2022, 11, 29, 4, 15, 0)
        # generate API Key
        cdate_timestamp = int(self.liveness_configuration.cdate.timestamp())
        data = "{}:{}".format(cdate_timestamp, self.liveness_configuration.client_id)
        api_key = generate_api_key(data)
        self.liveness_configuration.api_key = api_key
        self.liveness_configuration.whitelisted_domain = ['example.com']
        self.liveness_configuration.save()
        # set token
        self.client = APIClient()
        self.hashing_client_id = hashlib.sha1(
            str(self.liveness_configuration.client_id).encode()
        ).hexdigest()
        set_token_format = "{}:{}".format(
            self.hashing_client_id, self.liveness_configuration.api_key
        )
        self.token_liveness = base64.b64encode(set_token_format.encode("utf-8")).decode("utf-8")

        self.phone_number = '081912344444'
        self.user_auth = AuthUserFactory()
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        product_line_code = ProductLineCodes.J1
        self.product_line = ProductLineFactory(product_line_code=product_line_code)

        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')
        self.account = AccountFactory(customer=self.customer)
        status_lookup = StatusLookupFactory(status_code=100)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            email='prod.only@julofinance.com',
            application_status=status_lookup,
        )
        self.application_id = self.application.id

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        PilImage.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return 'Bearer {}'.format(access.token)

    @patch('juloserver.partnership.liveness_partnership.views.process_smile_liveness')
    def test_success_ledgen_submit_smile_liveness(self, mock_process_smile_liveness):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue(), content_type='image/png')

        mock_liveness_result = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types='smile',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_smile_liveness.return_value = mock_liveness_result, True
        url_check_liveness = '/api/partnership/liveness/v1/smile/check'
        expected_result = {
            'id': str(mock_liveness_result.reference_id),
            'score': mock_liveness_result.score,
        }
        response = self.client.post(
            url_check_liveness,
            {'smile': image_file_1, 'neutral': image_file_2},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token_liveness),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

        # submit liveness to application
        url_submit_liveness = '/api/leadgen/liveness/submit'
        token = self._create_token(self.customer, self.partner_name, self.application)
        liveness_payload = {
            'id': str(mock_liveness_result.reference_id),
        }
        response = self.client.post(
            url_submit_liveness, HTTP_AUTHORIZATION=token, data=liveness_payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        liveness_results_mapping = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).last()
        self.assertEqual(liveness_results_mapping.status, LivenessResultMappingStatus.ACTIVE)

    @patch('juloserver.partnership.liveness_partnership.views.process_smile_liveness')
    def test_success_ledgen_submit_smile_liveness_have_last_record(
        self, mock_process_smile_liveness
    ):
        image_1 = self.create_image()
        image_2 = self.create_image(size=(150, 150))
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')
        image_file_2 = SimpleUploadedFile('test2.png', image_2.getvalue(), content_type='image/png')

        mock_liveness_result_1 = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types='smile',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_liveness_result_1.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type='smile',
        )

        mock_liveness_result_2 = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types='smile',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_smile_liveness.return_value = mock_liveness_result_2, True
        url_check_liveness = '/api/partnership/liveness/v1/smile/check'
        expected_result = {
            'id': str(mock_liveness_result_2.reference_id),
            'score': mock_liveness_result_2.score,
        }
        response = self.client.post(
            url_check_liveness,
            {'smile': image_file_1, 'neutral': image_file_2},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token_liveness),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

        # submit liveness to application
        url_submit_liveness = '/api/leadgen/liveness/submit'
        token = self._create_token(self.customer, self.partner_name, self.application)
        liveness_payload = {
            'id': str(mock_liveness_result_2.reference_id),
        }
        response = self.client.post(
            url_submit_liveness, HTTP_AUTHORIZATION=token, data=liveness_payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        liveness_results_mapping_1 = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).first()
        self.assertEqual(liveness_results_mapping_1.status, LivenessResultMappingStatus.INACTIVE)
        liveness_results_mapping_2 = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).last()
        self.assertEqual(liveness_results_mapping_2.status, LivenessResultMappingStatus.ACTIVE)

    @patch('juloserver.partnership.liveness_partnership.views.process_passive_liveness')
    def test_success_ledgen_submit_passive_liveness(self, mock_process_passive_liveness):
        image_1 = self.create_image()
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')

        mock_liveness_result = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'neutral': 2},
            platform='web',
            detection_types='passive',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_passive_liveness.return_value = mock_liveness_result, True
        url = '/api/partnership/liveness/v1/passive/check'
        expected_result = {
            'id': str(mock_liveness_result.reference_id),
            'score': mock_liveness_result.score,
        }
        response = self.client.post(
            url,
            {'neutral': image_file_1},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token_liveness),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

        # submit liveness to application
        url_submit_liveness = '/api/leadgen/liveness/submit'
        token = self._create_token(self.customer, self.partner_name, self.application)
        liveness_payload = {
            'id': str(mock_liveness_result.reference_id),
        }
        response = self.client.post(
            url_submit_liveness, HTTP_AUTHORIZATION=token, data=liveness_payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        liveness_results_mapping = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).last()
        self.assertEqual(liveness_results_mapping.status, LivenessResultMappingStatus.ACTIVE)

    @patch('juloserver.partnership.liveness_partnership.views.process_passive_liveness')
    def test_success_ledgen_submit_passive_liveness_have_last_record(
        self, mock_process_passive_liveness
    ):
        image_1 = self.create_image()
        image_file_1 = SimpleUploadedFile('test1.png', image_1.getvalue(), content_type='image/png')

        mock_liveness_result_1 = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'neutral': 2},
            platform='web',
            detection_types='passive',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_liveness_result_1.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type='passive',
        )
        mock_liveness_result_2 = LivenessResultFactory(
            liveness_configuration_id=self.liveness_configuration.id,
            client_id=str(self.liveness_configuration.client_id),
            image_ids={'neutral': 2},
            platform='web',
            detection_types='passive',
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        mock_process_passive_liveness.return_value = mock_liveness_result_2, True
        url = '/api/partnership/liveness/v1/passive/check'
        expected_result = {
            'id': str(mock_liveness_result_2.reference_id),
            'score': mock_liveness_result_2.score,
        }
        response = self.client.post(
            url,
            {'neutral': image_file_1},
            format='multipart',
            HTTP_ORIGIN='https://example.com',
            HTTP_AUTHORIZATION='Token {}'.format(self.token_liveness),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json()['data'], expected_result)

        # submit liveness to application
        url_submit_liveness = '/api/leadgen/liveness/submit'
        token = self._create_token(self.customer, self.partner_name, self.application)
        liveness_payload = {
            'id': str(mock_liveness_result_2.reference_id),
        }
        response = self.client.post(
            url_submit_liveness, HTTP_AUTHORIZATION=token, data=liveness_payload, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        liveness_results_mapping_1 = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).first()
        self.assertEqual(liveness_results_mapping_1.status, LivenessResultMappingStatus.INACTIVE)
        liveness_results_mapping_2 = LivenessResultsMapping.objects.filter(
            application_id=self.application_id,
        ).last()
        self.assertEqual(liveness_results_mapping_2.status, LivenessResultMappingStatus.ACTIVE)

    def test_fail_ledgen_submit_liveness_id_not_found(self):
        random_id = ulid.new().uuid
        # submit liveness to application
        url_submit_liveness = '/api/leadgen/liveness/submit'
        token = self._create_token(self.customer, self.partner_name, self.application)
        liveness_payload = {
            'id': str(random_id),
        }
        response = self.client.post(
            url_submit_liveness, HTTP_AUTHORIZATION=token, data=liveness_payload, format='json'
        )
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


class TestLeadgenSubmitApplicationView(TestCase):
    def setUp(self):
        self.phone_number = '081912344444'
        self.user_auth = AuthUserFactory()
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = "/api/leadgen/form/submit"

        product_line_code = ProductLineCodes.J1
        self.product_line = ProductLineFactory(product_line_code=product_line_code)

        self.customer = CustomerFactory(
            user=self.user_auth,
            email='prod.only@julofinance.com',
            nik='3271065902890002',
        )
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            email='prod.only@julofinance.com',
            ktp='3271065902890002',
        )
        self.application_id = self.application.id
        status_lookup = StatusLookupFactory(status_code=100)
        self.application.update_safely(application_status=status_lookup)
        self.data = {'currentStep': -1}

        PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": True},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LOGO: {"logoUrl": "https://xxxxxxxxx"},
                PartnershipFlag.LEADGEN_SUB_CONFIG_LONG_FORM: {
                    "formSections": {
                        "ktpAndSelfiePhoto": {
                            "isHideSection": False,
                            "hiddenFields": ["dependent", "occupiedSince", "homeStatus"],
                        },
                        "personalData": {"isHideSection": False, "hiddenFields": []},
                        "domicileInformation": {"isHideSection": False, "hiddenFields": []},
                        "personalContactInformation": {"isHideSection": False, "hiddenFields": []},
                        "partnerContact": {"isHideSection": False, "hiddenFields": []},
                        "parentsContact": {"isHideSection": False, "hiddenFields": []},
                        "emergencyContact": {"isHideSection": False, "hiddenFields": []},
                        "jobInformation": {"isHideSection": False, "hiddenFields": []},
                        "incomeAndExpenses": {"isHideSection": False, "hiddenFields": []},
                        "bankAccountInformation": {"isHideSection": False, "hiddenFields": []},
                        "referralCode": {"isHideSection": False, "hiddenFields": []},
                    }
                },
            },
        )
        self.province = ProvinceLookupFactory(province='Jakarta')
        self.city = CityLookupFactory(city='Jakarta Selatan', province=self.province)
        self.district = DistrictLookupFactory(district='Menteng', city=self.city)
        SubDistrictLookupFactory(
            sub_district='Menteng Selatan', zipcode='12345', district=self.district
        )
        self.loan_purpose = LoanPurposeFactory()
        self.bank = BankFactory(bank_name='Bank Central Asia (BCA)')
        self.image_ktp = ImageFactory(
            image_type='ktp_self', image_source=self.application.id, image_status=0
        )
        self.image_ktp_selfie = ImageFactory(
            image_type='selfie', image_source=self.application.id, image_status=0
        )
        OtpRequestFactory(
            customer=self.customer,
            is_used=True,
            application=self.application,
            phone_number='086618031502',
            action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=ulid.new().uuid,
            application_id=self.application_id,
            status='active',
        )

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return 'Bearer {}'.format(access.token)

    def test_submit_application_pre_register_confirmation(self):
        # Invalid upload document form - ktp/selfie not uploaded
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.patch(
            self.endpoint, data=self.data, HTTP_AUTHORIZATION=token, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name,
            LeadgenStandardApplicationFormType.PRE_REGISTER_CONFIRMATION,
        )

    def test_submit_application_personal_identity(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=LeadgenStandardApplicationFormType.PRE_REGISTER_CONFIRMATION,
        )
        # Identity information form
        self.data.update(
            {
                "currentStep": 0,
                "ktpSelfieImageId": self.image_ktp_selfie.id,
                "ktpImageId": self.image_ktp.id,
                "nik": self.application.ktp,
                "email": self.application.email,
                "fullname": "Jimmy Axiata",
                "birthPlace": "Jakarta",
                "dob": "2001-03-13T00:00:00+07:00",
                "gender": "Pria",
                "motherMaidenName": "Jhon Doe Mother",
                "address": "Casablanca Lt 5",
                "addressProvince": "Jakarta",
                "addressRegency": "Jakarta Selatan",
                "addressDistrict": "Menteng",
                "addressSubdistrict": "Menteng Selatan",
                "occupiedSince": "2001-03-13T00:00:00+07:00",
                "homeStatus": "Milik sendiri, lunas",
                "maritalStatus": "Lajang",
                "dependent": 2,
                "phoneNumber": "086618031502",
                "otherPhoneNumber": "086618031503",
            }
        )

        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.application.refresh_from_db()
        # Check data is updated in application table
        self.assertEqual(self.data['fullname'], self.application.fullname)
        self.assertIsNotNone(self.application.dob)
        self.assertIsNotNone(self.application.occupied_since)
        self.assertEqual(self.data['birthPlace'], self.application.birth_place)
        self.assertEqual(self.data['gender'], self.application.gender)
        self.assertEqual(self.data['dependent'], self.application.dependent)
        self.assertEqual(self.data['maritalStatus'], self.application.marital_status)
        self.assertEqual(self.data['phoneNumber'], self.application.mobile_phone_1)
        self.assertEqual(self.data['otherPhoneNumber'], self.application.mobile_phone_2)
        self.assertEqual(self.data['address'], self.application.address_street_num)
        self.assertEqual(self.data['addressProvince'], self.application.address_provinsi)
        self.assertEqual(self.data['addressRegency'], self.application.address_kabupaten)
        self.assertEqual(self.data['addressDistrict'], self.application.address_kecamatan)
        self.assertEqual(self.data['addressSubdistrict'], self.application.address_kelurahan)
        self.assertEqual(self.data['homeStatus'], self.application.home_status)
        # Check data is updated in customer table
        self.customer.refresh_from_db()
        self.assertEqual(self.data['motherMaidenName'], self.customer.mother_maiden_name)
        self.assertIsNotNone(self.customer.dob)
        self.assertEqual(self.data['birthPlace'], self.customer.birth_place)
        self.assertEqual(self.data['gender'], self.customer.gender)
        self.assertEqual(self.data['maritalStatus'], self.customer.marital_status)
        self.assertEqual(self.data['phoneNumber'], self.customer.phone)
        self.assertEqual(self.data['address'], self.customer.address_street_num)
        self.assertEqual(self.data['addressProvince'], self.customer.address_provinsi)
        self.assertEqual(self.data['addressRegency'], self.customer.address_kabupaten)
        self.assertEqual(self.data['addressDistrict'], self.customer.address_kecamatan)
        self.assertEqual(self.data['addressSubdistrict'], self.customer.address_kelurahan)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name, LeadgenStandardApplicationFormType.PERSONAL_IDENTITY
        )

    def test_submit_application_emergency_contact(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=LeadgenStandardApplicationFormType.PERSONAL_IDENTITY,
        )
        self.application.marital_status = "Lajang"
        self.application.save()
        # Identity information form
        self.data.update(
            {
                "currentStep": 1,
                "kinName": "Jhon Doe Mother",
                "kinPhoneNumber": "086618031505",
                "closeKinRelationship": "Saudara kandung",
                "closeKinName": "Jhon Doe Brother",
                "closeKinPhoneNumber": "086618031506",
            }
        )

        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.application.refresh_from_db()
        # Check data is updated in application table
        self.assertEqual('Orang tua', self.application.kin_relationship)
        self.assertEqual(self.data['kinName'], self.application.kin_name)
        self.assertEqual(self.data['kinPhoneNumber'], self.application.kin_mobile_phone)
        self.assertEqual(self.data['closeKinRelationship'], self.application.close_kin_relationship)
        self.assertEqual(self.data['closeKinName'], self.application.close_kin_name)
        self.assertEqual(self.data['closeKinPhoneNumber'], self.application.close_kin_mobile_phone)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name, LeadgenStandardApplicationFormType.EMERGENCY_CONTACT
        )

    def test_submit_application_job_information(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=LeadgenStandardApplicationFormType.EMERGENCY_CONTACT,
        )
        self.application.marital_status = "Lajang"
        self.application.save()
        # Identity information form
        self.data.update(
            {
                "currentStep": 2,
                "jobType": "Pegawai swasta",
                "jobIndustry": "Service",
                "jobPosition": "Koki",
                "companyName": "PT. Julo Teknologi Finansial",
                "companyPhoneNumber": "072999022121",
                "jobStart": "2001-03-13T00:00:00+07:00",
                "payday": 1,
            }
        )

        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.application.refresh_from_db()
        # Check data is updated in application table
        self.assertEqual(self.data['jobType'], self.application.job_type)
        self.assertEqual(self.data['jobIndustry'], self.application.job_industry)
        self.assertEqual(self.data['jobPosition'], self.application.job_description)
        self.assertEqual(self.data['companyName'], self.application.company_name)
        self.assertEqual(self.data['companyPhoneNumber'], self.application.company_phone_number)
        self.assertIsNotNone(self.application.job_start)
        self.assertEqual(self.data['payday'], self.application.payday)
        # case if jobType are jobless
        self.data.update(
            {
                "currentStep": 2,
                "jobType": "Mahasiswa",
            }
        )
        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.application.refresh_from_db()
        self.assertEqual(self.data['jobType'], self.application.job_type)
        self.assertIsNone(self.application.job_industry)
        self.assertIsNone(self.application.job_description)
        self.assertEqual(self.application.company_name, '')
        self.assertIsNone(self.application.company_phone_number)
        self.assertIsNone(self.application.job_start)
        self.assertIsNone(self.application.payday)
        # validation partnership_application_flag
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name, LeadgenStandardApplicationFormType.JOB_INFORMATION
        )

    def test_submit_application_personal_finance_information(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=LeadgenStandardApplicationFormType.JOB_INFORMATION,
        )
        self.application.marital_status = "Lajang"
        self.application.save()
        # Identity information form
        self.data.update(
            {
                "currentStep": 3,
                "monthlyIncome": 1000000,
                "monthlyExpenses": 100000,
                "totalCurrentDebt": 0,
                "bankName": "Bank Central Asia (BCA)",
                "bankAccountNumber": "72212312121",
                "loanPurpose": "bayar utang",
                "referralCode": None,
            }
        )

        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.application.refresh_from_db()
        # Check data is updated in application table
        self.assertEqual(self.data['monthlyIncome'], self.application.monthly_income)
        self.assertEqual(self.data['monthlyExpenses'], self.application.monthly_expenses)
        self.assertEqual(self.data['totalCurrentDebt'], self.application.total_current_debt)
        self.assertEqual(self.data['bankName'], self.application.bank_name)
        self.assertEqual(self.data['bankAccountNumber'], self.application.bank_account_number)
        self.assertEqual(self.data['loanPurpose'], self.application.loan_purpose)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name,
            LeadgenStandardApplicationFormType.PERSONAL_FINANCE_INFORMATION,
        )

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.process_application_status_change')
    def test_submit_application_review(self, mock_process_application_status_change):
        token = self._create_token(self.customer, self.partner_name, self.application)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=LeadgenStandardApplicationFormType.PERSONAL_FINANCE_INFORMATION,
        )
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=j1_workflow,
        )
        self.application.workflow = j1_workflow
        self.application.marital_status = "Lajang"
        self.application.save()
        # Identity information form
        self.data.update(
            {
                "currentStep": 4,
                "ktpSelfieImageId": self.image_ktp_selfie.id,
                "ktpImageId": self.image_ktp.id,
                "nik": self.application.ktp,
                "email": self.application.email,
                "fullname": "Jimmy Axiata",
                "birthPlace": "Jakarta",
                "dob": "2001-03-13T00:00:00+07:00",
                "gender": "Pria",
                "motherMaidenName": "Jhon Doe Mother",
                "address": "Casablanca Lt 5",
                "addressProvince": "Jakarta",
                "addressRegency": "Jakarta Selatan",
                "addressDistrict": "Menteng",
                "addressSubdistrict": "Menteng Selatan",
                "occupiedSince": "2001-03-13T00:00:00+07:00",
                "homeStatus": "Milik sendiri, lunas",
                "maritalStatus": "Lajang",
                "dependent": 2,
                "phoneNumber": "086618031502",
                "otherPhoneNumber": "086618031503",
                "kinName": "Jhon Doe Mother",
                "kinPhoneNumber": "086618031505",
                "closeKinRelationship": "Saudara kandung",
                "closeKinName": "Jhon Doe Brother",
                "closeKinPhoneNumber": "086618031506",
                "jobType": "Pegawai swasta",
                "jobIndustry": "Service",
                "jobPosition": "Koki",
                "companyName": "PT. Julo Teknologi Finansial",
                "companyPhoneNumber": "02199022121",
                "jobStart": "2001-03-13T00:00:00+07:00",
                "payday": 1,
                "monthlyIncome": 1000000,
                "monthlyExpenses": 100000,
                "totalCurrentDebt": 0,
                "bankName": "Bank Central Asia (BCA)",
                "bankAccountNumber": "72212312121",
                "loanPurpose": "bayar utang",
                "referralCode": None,
                "hasAgreedToTermsAndPrivacy": True,
                "hasAgreedToDataVerification": True,
            }
        )

        response = self.client.patch(
            self.endpoint, HTTP_AUTHORIZATION=token, data=self.data, format='json'
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        partnership_application_flag = PartnershipApplicationFlag.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(
            partnership_application_flag.name, LeadgenStandardApplicationFormType.FORM_SUBMISSION
        )
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='customer_triggered',
        )


class TestLeadgenResubmissionApplicationView(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()
        self.partner_name = "cermati"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSettingFactory(
            is_active=True,
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            parameters={
                'allowed_partner': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
            partner=self.partner,
        )
        self.application_status_131 = StatusLookupFactory(status_code=131)
        self.application.application_status = self.application_status_131
        self.application.save()
        self.endpoint = '/api/leadgen/resubmission/request'
        self.application_history = ApplicationHistoryFactory(application_id=self.application.id)
        WorkflowStatusPathFactory(
            status_previous=131,
            status_next=132,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt_token.create_or_update_token(
            token_type=PartnershipTokenType.ACCESS_TOKEN,
        )
        self.access_token = 'Bearer {}'.format(access.token)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.process_application_status_change')
    def test_ledgen_success_resubmission_application(self, mock_process_application_status_change):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            change_reason='KTP needed, Selfie blurry, Mutasi Rekening needed, Salary doc needed',
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        )
        ktp = ImageFactory(
            image_type='ktp_self', image_status=Image.DELETED, image_source=self.application.id
        )
        selfie = ImageFactory(
            image_type='selfie', image_status=Image.DELETED, image_source=self.application.id
        )
        payslip = ImageFactory(
            image_type='payslip', image_status=Image.DELETED, image_source=self.application.id
        )
        bank_statement = ImageFactory(
            image_type='bank_statement',
            image_status=Image.DELETED,
            image_source=self.application.id,
        )
        payload = {
            "dataConfirmation": True,
            "ktp": ktp.id,
            "ktpSelfie": selfie.id,
            "payslip": payslip.id,
            "bankStatement": bank_statement.id,
        }
        response = self.client.patch(
            self.endpoint, data=payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        ktp.refresh_from_db()
        selfie.refresh_from_db()
        payslip.refresh_from_db()
        bank_statement.refresh_from_db()

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertEqual(ktp.image_status, Image.CURRENT)
        self.assertEqual(selfie.image_status, Image.CURRENT)
        self.assertEqual(payslip.image_status, Image.CURRENT)
        self.assertEqual(bank_statement.image_status, Image.CURRENT)
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            change_reason='customer_triggered',
        )

    def test_ledgen_failed_resubmission_application_invalid_data(self):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            change_reason='KTP needed, Selfie blurry',
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        )
        ktp = ImageFactory(
            image_type='ktp', image_status=Image.DELETED, image_source=self.application.id
        )
        selfie = ImageFactory(
            image_type='ktp_self', image_status=Image.DELETED, image_source=self.application.id
        )
        payload = {
            "dataConfirmation": True,
            "ktp": ktp.id,
            "ktpSelfie": 123,
        }
        response = self.client.patch(
            self.endpoint, data=payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_ledgen_failed_resubmission_application_required_field(self):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            change_reason='KTP needed, Selfie blurry',
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        )
        ktp = ImageFactory(
            image_type='ktp', image_status=Image.DELETED, image_source=self.application.id
        )
        selfie = ImageFactory(
            image_type='ktp_self', image_status=Image.DELETED, image_source=self.application.id
        )
        payload = {"dataConfirmation": True, "ktp": ktp.id}
        response = self.client.patch(
            self.endpoint, data=payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_ledgen_failed_resubmission_application_invalid_type(self):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            change_reason='KTP needed, Selfie blurry',
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        )
        ktp = ImageFactory(
            image_type='ktp_self', image_status=Image.DELETED, image_source=self.application.id
        )
        selfie = ImageFactory(
            image_type='selfie', image_status=Image.DELETED, image_source=self.application.id
        )
        payload = {"dataConfirmation": True, "ktp": selfie.id, "ktpSelfie": ktp.id}
        response = self.client.patch(
            self.endpoint, data=payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )


class TestLeadgenStandardChangePinOTPVerification(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/otp/change-pin/verify'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.otp = OtpRequestFactory(
            action_type=SessionTokenAction.PRE_LOGIN_RESET_PIN,
            is_active=True,
            customer=self.customer,
            otp_service_type="email",
        )
        self.payload = {
            "otp": self.otp.otp_token,
        }

        jwt = JWTManager(
            user=self.user_auth,
            partner_name=self.partner.name,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = 'Bearer {}'.format(access.token)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_validate_otp')
    def test_success_verify_otp(self, mock_leadgen_validate_otp):
        mock_leadgen_validate_otp.return_value = OTPValidateStatus.SUCCESS, None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_validate_otp')
    def test_failed_feature_setting_is_off(self, mock_leadgen_validate_otp):
        mock_leadgen_validate_otp.return_value = OTPValidateStatus.FEATURE_NOT_ACTIVE, None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_validate_otp')
    def test_failed_otp_rate_limit_exceed(self, mock_leadgen_validate_otp):
        mock_leadgen_validate_otp.return_value = OTPValidateStatus.LIMIT_EXCEEDED, None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_validate_otp')
    def test_failed_otp_expired(self, mock_leadgen_validate_otp):
        mock_leadgen_validate_otp.return_value = OTPValidateStatus.EXPIRED, None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.leadgen_validate_otp')
    def test_failed_otp_expired(self, mock_leadgen_validate_otp):
        mock_leadgen_validate_otp.return_value = OTPValidateStatus.FAILED, None
        response = self.client.post(self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )


class TestLeadgenStandardPreRegister(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.payload = {
            'nik': "5171042804630001",
            'email': "prod.only@julofinance.com",
            'partnerName': self.partner_name,
        }
        self.client = APIClient()
        self.endpoint = f'/api/leadgen/pre-check/register'
        self.redis_data = {}

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )

        PartnershipFlowFlag.objects.get_or_create(
            partner=self.partner,
            name=PartnershipFlag.LEADGEN_PARTNER_CONFIG,
            configs={PartnershipFlag.LEADGEN_SUB_CONFIG_LOCATION: {"isRequiredLocation": False}},
        )

    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_success_register_check(self, mock_redis):
        mock_redis.set.return_value = True
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

    def test_invalid_data(self):
        self.payload['nik'] = 'test_nik'
        self.payload['email'] = 'test_email'

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_not_sended_data(self):
        payload = {
            'partnerName': self.partner_name,
        }

        response = self.client.post(self.endpoint, data=payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_null_data(self):
        payload = {
            'nik': "",
            'email': "",
            'partnerName': self.partner_name,
        }

        response = self.client.post(self.endpoint, data=payload, format='json')
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_registered_user(self, mock_redis):
        mock_redis.set.return_value = True
        AuthUserFactory(username=self.payload['nik'])
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_too_many_attempt(self, mock_get_redis):
        mock_redis = mock_get_redis.return_value
        mock_redis.set.return_value = True
        mock_redis.get.return_value = b'10'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    @patch("juloserver.partnership.leadgenb2b.onboarding.views.get_redis_client")
    def test_too_many_attempt_registered_user(self, mock_get_redis):
        mock_redis = mock_get_redis.return_value
        mock_redis.set.return_value = True
        mock_redis.get.return_value = b'3'
        AuthUserFactory(username=self.payload['nik'])
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)


class LeadgenStandardReapply(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()

        self.partner_name = "cermati"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSettingFactory(
            is_active=True,
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            parameters={
                'allowed_partner': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.customer = CustomerFactory(
            user=self.user_auth,
            can_reapply=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
            partner=self.partner,
        )
        self.application_status_106 = StatusLookupFactory(status_code=106)
        self.application_status_190 = StatusLookupFactory(status_code=190)
        self.application.application_status = self.application_status_106
        self.application.save()
        self.payload = {
            'latitude': -6.2244855,
            'longitude': 106.8392242,
        }
        self.endpoint = '/api/leadgen/reapply'
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt_token.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.access_token = 'Bearer {}'.format(access.token)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.execute_after_transaction_safely')
    @patch('juloserver.partnership.leadgenb2b.onboarding.views.create_application_checklist_async')
    @patch('juloserver.partnership.leadgenb2b.onboarding.views.process_application_status_change')
    def test_success_reapply(
        self,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        response = self.client.post(
            self.endpoint, data=self.payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

        # Check if async tasks generated
        mock_process_application_status_change.assert_called_once()
        mock_create_application_checklist_async.delay.assert_called_once()
        mock_generate_address_from_geolocation_async.assert_called_once()

    def test_failed_reapply(self):
        self.application.application_status = self.application_status_190
        self.application.save()
        self.payload = None
        response = self.client.post(
            self.endpoint, data=self.payload, format='json', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(422, response.status_code)


class LeadgenStandardUploadMandatoryDocs(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.client = APIClient()

        self.partner_name = "cermati"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSettingFactory(
            is_active=True,
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            parameters={
                'allowed_partner': [self.partner_name],
            },
        )

        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
            partner=self.partner,
        )
        self.application_status_120 = StatusLookupFactory(status_code=120)
        self.application_status_190 = StatusLookupFactory(status_code=190)
        self.application.application_status = self.application_status_120
        self.application.save()
        jwt_token = JWTManager(
            user=self.user_auth,
            partner_name=self.partner_name,
            product_id=self.application.product_line_code,
        )
        access = jwt_token.create_or_update_token(
            token_type=PartnershipTokenType.ACCESS_TOKEN,
        )
        self.access_token = 'Bearer {}'.format(access.token)

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        image_pil.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.get_oss_presigned_url')
    @patch('juloserver.partnership.leadgenb2b.onboarding.views.process_image_upload_partnership')
    def test_success_upload_mandatory_docs(
        self, mock_upload_image: MagicMock, image_url_mock: MagicMock
    ):
        image_url_mock.return_value = 'https://image-url-mock.com'
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        url = '/api/leadgen/mandatory-docs/ktp/upload'
        response = self.client.post(
            url, {'image': image_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        mock_upload_image.assert_called_once()
        file_id = response.data.get('data').get('fileId')
        document_exists = Image.objects.filter(pk=file_id).last()
        self.assertTrue(document_exists)
        self.assertEqual(document_exists.image_status, Image.DELETED)

    @patch('juloserver.partnership.leadgenb2b.onboarding.views.process_image_upload_partnership')
    def test_failed_upload_mandatory_docs(
        self,
        mock_upload_image: MagicMock,
    ):
        self.application.application_status = self.application_status_190
        self.application.save()

        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        url = '/api/leadgen/mandatory-docs/bank-statement/upload'
        response = self.client.post(
            url, {'image': image_file}, format='multipart', HTTP_AUTHORIZATION=self.access_token
        )
        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)


class TestLeadgenStandardChangePinSubmission(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.CERMATI
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        self.client = APIClient()
        self.endpoint = '/api/leadgen/pin/change'

        self.user_auth = AuthUser(username='5171042804630001', email='prod.only@julofinance.com')
        self.user_auth.set_password("452123")
        self.user_auth.save()
        self.customer = CustomerFactory(user=self.user_auth)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        jwt = JWTManager(
            user=self.user_auth,
            partner_name=self.partner.name,
            application_xid=self.application.application_xid,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.RESET_PIN_TOKEN)
        self.query_params = {
            'token': access.token,
        }

    def test_success_change_pin(self):
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user_auth)
        payload = {
            'pin': "452125",
            'confirmPin': "452125",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

    def test_user_has_no_pin(self):
        payload = {
            'pin': "452125",
            'confirmPin': "452125",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_incorrect_confirmation_pin(self):
        payload = {
            'pin': "452125",
            'confirmPin': "452124",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )

    def test_user_pin_is_same_as_old_one(self):
        payload = {
            'pin': "452123",
            'confirmPin': "452123",
        }
        url_with_params = f"{self.endpoint}?token={self.query_params.get('token')}"
        response = self.client.post(url_with_params, data=payload)
        self.assertEqual(
            PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code
        )
