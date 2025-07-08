import ulid

from datetime import timedelta
from mock import patch

from django.test import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv2.models import PdWebModelResult
from juloserver.apiv2.services import check_iti_repeat, get_customer_category
from juloserver.apiv2.tests.factories import PdWebModelResultFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import (
    AddressGeolocation,
    OtpRequest,
    FeatureSetting,
    ITIConfiguration,
    CreditScore,
    HighScoreFullBypass,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    PartnerFactory,
    WorkflowFactory,
    ProductLineFactory,
    CustomerFactory,
    AuthUserFactory,
    OtpRequestFactory,
    ApplicationFactory,
    CreditScoreFactory,
    StatusLookupFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.otp.constants import OTPType, SessionTokenAction, OTPRequestStatus
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.partnership.leadgenb2b.onboarding.services import process_register, leadgen_generate_otp
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.partnership.liveness_partnership.constants import (
    LivenessType,
)
from juloserver.partnership.tests.factories import LivenessResultsMappingFactory
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.partnership.liveness_partnership.constants import (
    LivenessResultMappingStatus,
)
from juloserver.partnership.liveness_partnership.tests.factories import (
    LivenessConfigurationFactory,
    LivenessResultFactory,
)
from juloserver.partnership.liveness_partnership.utils import generate_api_key
from juloserver.julo.services2.high_score import feature_high_score_full_bypass


class TestLeadgenStandardRegister(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.customer_data = {
            'nik': "5171042804630001",
            'pin': "456789",
            'email': "prod.only@julofinance.com",
            'latitude': '6.12',
            'longitude': '12.6',
            'partnerName': self.partner_name,
        }

        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.path = WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
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
    def test_success_process_register(
        self,
        mock_process_application_status_change,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
    ):
        result = process_register(self.customer_data)
        self.assertIsNotNone(result.user)
        self.assertIsNotNone(result.customer)
        self.assertIsNotNone(result.application)

        res_geolocation = AddressGeolocation.objects.filter(
            application_id=result.application.id
        ).last()
        self.assertIsNotNone(res_geolocation)

        mock_process_application_status_change.assert_called_once_with(
            result.application.id,
            ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered',
        )

        # Check if async tasks generated
        mock_create_application_checklist_async.delay.assert_called_once_with(result.application.id)
        mock_generate_address_from_geolocation_async.delay.assert_called_once_with(
            res_geolocation.id
        )


class TestLeadgenStandardGenerateOtp(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')

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

        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    def get_redis_ttl(self):
        return 120

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_feature_inactive(self, mock_get_redis_client):
        otp_settings = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS
        )
        otp_settings.update(is_active=False)

        result, otp_data = leadgen_generate_otp(
            True, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert OTPRequestStatus.FEATURE_NOT_ACTIVE == result

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_feature_email_not_available(self, mock_get_redis_client):
        otp_settings = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS
        )
        otp_settings.update(
            parameters={
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
            }
        )

        result, otp_data = leadgen_generate_otp(
            True, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert OTPRequestStatus.FEATURE_NOT_ACTIVE == result

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.send_email_otp_token.delay')
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.leadgen_send_sms_otp_token.delay')
    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_success_generate_otp(self, mock_get_redis_client, send_sms_otp_token, mock_send_email):
        mock_get_redis_client.return_value.get_list.side_effect = {}
        result, otp_data = leadgen_generate_otp(
            False, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert OTPRequestStatus.SUCCESS == result
        mock_send_email.assert_called_once()

        old_otp = OtpRequest.objects.filter(
            action_type=SessionTokenAction.LOGIN, customer=self.customer, otp_service_type="email"
        ).last()
        old_otp.cdate = timezone.localtime(old_otp.cdate) - timedelta(seconds=60)
        old_otp.save()

        result, otp_data = leadgen_generate_otp(
            False, self.customer, OTPType.SMS, None, SessionTokenAction.LOGIN
        )
        assert OTPRequestStatus.SUCCESS == result
        send_sms_otp_token.assert_called_once()

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_limit_exceed(self, mock_get_redis_client):
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            'leadgen_otp_request_blocked:{}:{}'.format(self.customer.id, SessionTokenAction.LOGIN),
            True,
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_redis_client.return_value.get_ttl.return_value = 120
        for _ in range(3):
            old_otp = OtpRequestFactory(
                action_type=SessionTokenAction.LOGIN,
                is_active=True,
                customer=self.customer,
                otp_service_type="email",
            )
            old_otp.cdate = timezone.localtime(old_otp.cdate) - timedelta(seconds=60)
            old_otp.save()

        result, otp_data = leadgen_generate_otp(
            True, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert result == OTPRequestStatus.LIMIT_EXCEEDED

        old_otp_list = OtpRequest.objects.filter(
            action_type=SessionTokenAction.LOGIN, customer=self.customer, otp_service_type="email"
        )
        for old_otp in old_otp_list:
            old_otp.is_used = True
            old_otp.save()

        result2, otp_data = leadgen_generate_otp(
            False, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert result2 == OTPRequestStatus.SUCCESS

    @patch('juloserver.partnership.leadgenb2b.onboarding.services.get_redis_client')
    def test_otp_resend_time_insufficient(self, mock_get_redis_client):
        OtpRequestFactory(
            action_type=SessionTokenAction.LOGIN,
            is_active=True,
            customer=self.customer,
            otp_service_type="email",
        )
        result, otp_data = leadgen_generate_otp(
            True, self.customer, OTPType.EMAIL, None, SessionTokenAction.LOGIN
        )
        assert result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT


# unit testing sonic bypass
class TestCheckItiRepeatPartnership(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            partner=self.partner,
            monthly_income=100,
            workflow=self.workflow,
        )

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        # setup iti configuration
        self.pgood = 0.9
        self.inside_premium_area = True
        self.is_salaried = True

        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            inside_premium_area=self.inside_premium_area,
        )
        self.pd_web_model_result = PdWebModelResultFactory(
            application_id=self.application.id, pgood=self.pgood
        )
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=123,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(self.application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=self.application.monthly_income,
            max_income=self.application.monthly_income + 1,
            parameters={"partner_ids": [str(self.partner.id)]},
        )

    # test happy case leadgen user, test non leadgen users
    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_happy_flow_check_iti_partnership(self, mock_check_app_cs_v20b, mock_get_salaried):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried

        result = check_iti_repeat(self.application.id)
        assert result != None

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_another_iti_configuration_version_exists_with_not_partner(
        self, mock_check_app_cs_v20b, mock_get_salaried
    ):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=124,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(self.application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=self.application.monthly_income,
            max_income=self.application.monthly_income + 1,
        )

        result = check_iti_repeat(self.application.id)
        assert result != None

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_partnership_but_non_leadgen_user(self, mock_check_app_cs_v20b, mock_get_salaried):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried
        partner_name = PartnerNameConstant.CERMATI
        partner = PartnerFactory(name=partner_name, is_active=True)
        new_non_leadgen_application = ApplicationFactory(
            partner=partner,
            monthly_income=100,
            workflow=self.workflow,
        )
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=124,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(new_non_leadgen_application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=new_non_leadgen_application.monthly_income,
            max_income=new_non_leadgen_application.monthly_income + 1,
        )

        CreditScore.objects.create(
            application_id=new_non_leadgen_application.id,
            inside_premium_area=self.inside_premium_area,
            score='C',
        )
        PdWebModelResult.objects.create(
            id=1,
            application_id=new_non_leadgen_application.id,
            customer_id=0,
            pgood=self.pgood,
            probability_fpd=self.pgood,
        )

        result = check_iti_repeat(new_non_leadgen_application.id)
        assert result != None


class TestPartnershipLeadgenCheckLivenessResult(TestCase):
    def setUp(self):
        self.client_id = ulid.new().uuid
        self.phone_number = '081912344444'
        self.user_auth = AuthUserFactory()
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=134,
            type='graveyard',
            is_active=True,
            workflow=self.workflow,
        )
        product_line_code = ProductLineCodes.J1
        self.product_line = ProductLineFactory(product_line_code=product_line_code)
        self.customer = CustomerFactory(user=self.user_auth, email='prod.only@julofinance.com')
        self.account = AccountFactory(customer=self.customer)

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            email='prod.only@julofinance.com',
            workflow=self.workflow,
        )
        status_lookup_105 = StatusLookupFactory(status_code=105)
        self.application.update_safely(application_status=status_lookup_105)
        self.application_id = self.application.id

        self.partnership_feature_setting = PartnershipFeatureSetting.objects.create(
            feature_name=PartnershipFeatureNameConst.LEADGEN_LIVENESS_SETTINGS,
            is_active=True,
            parameters={
                'smile': {
                    'score_threshold': 1.0,
                    'max_retry': 3,
                },
                'passive': {
                    'score_threshold': 0.86,
                    'max_retry': 3,
                },
            },
            description='partnership ledgen liveness settings',
            category='partnership',
        )

    @patch('juloserver.partnership.services.services.logger')
    def test_partnership_pass_liveness_result(self, mock_logger):
        from juloserver.partnership.services.services import (
            partnership_leadgen_check_liveness_result,
        )

        mock_passive_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'neutral': 3},
            platform='web',
            detection_types=LivenessType.PASSIVE,
            score=0.9,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_passive_liveness_result.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type=LivenessType.PASSIVE,
        )
        mock_smile_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types=LivenessType.SMILE,
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_smile_liveness_result.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type=LivenessType.SMILE,
        )
        partnership_leadgen_check_liveness_result(self.application_id, 105, 'customer_triggered')
        mock_logger.info.assert_called_once()
        log_call_args = mock_logger.info.call_args[0][0]
        self.assertEqual(log_call_args.get('action'), 'partnership_check_liveness_result')
        self.assertEqual(log_call_args.get('message'), 'pass liveness check')

    @patch('juloserver.partnership.services.services.process_application_status_change')
    @patch('juloserver.partnership.services.services.logger')
    def test_partnership_failed_liveness_result(
        self, mock_logger, mock_process_application_status_change
    ):
        from juloserver.partnership.services.services import (
            partnership_leadgen_check_liveness_result,
        )

        mock_passive_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'neutral': 3},
            platform='web',
            detection_types=LivenessType.PASSIVE,
            score=0.5,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_passive_liveness_result.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type=LivenessType.PASSIVE,
        )
        mock_smile_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types=LivenessType.SMILE,
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=mock_smile_liveness_result.reference_id,
            application_id=self.application_id,
            status='active',
            detection_type=LivenessType.SMILE,
        )
        partnership_leadgen_check_liveness_result(self.application_id, 105, 'customer_triggered')
        mock_logger.info.assert_called_with(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'manual check liveness from ops, move to 134',
                'application_id': self.application_id,
                'is_pass_passive_liveness': False,
                'is_pass_smile_liveness': True,
            }
        )
        mock_process_application_status_change.assert_called_with(
            self.application_id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            change_reason='Manual image verification by ops',
        )


class TestHighScoreFullBypassPartnership(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        product_line_code = ProductLineCodes.J1
        self.application = ApplicationFactory(
            partner=self.partner,
            monthly_income=1_000_000,
            workflow=self.workflow,
        )
        self.application.product_line = ProductLineFactory(product_line_code=product_line_code)
        self.application.save()
        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={'allowed_partner': [self.partner_name]},
            category='partner',
        )
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
            is_active=True,
        )
        self.threshold = 0.8
        self.pgood = 0.9
        self.inside_premium_area = True
        self.is_salaried = True
        self.is_bypass_dv_x121 = True

        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            inside_premium_area=self.inside_premium_area,
            model_version=2,
        )
        self.pd_web_model_result = PdWebModelResultFactory(
            application_id=self.application.id, pgood=self.pgood
        )
        self.high_score_full_bypass_partner = HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
            parameters={"partner_ids": [str(self.partner.id)]},
        )

    @patch('juloserver.apiv2.credit_matrix2.get_salaried')
    def test_success_high_score_full_bypass_partnership(self, mock_get_salaried):
        mock_get_salaried.return_value = self.is_salaried
        result = feature_high_score_full_bypass(self.application)
        self.assertIsNotNone(result)

    @patch('juloserver.apiv2.credit_matrix2.get_salaried')
    def test_success_high_score_full_bypass_partnership_without_partner(self, mock_get_salaried):
        mock_get_salaried.return_value = self.is_salaried
        HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
        )
        result = feature_high_score_full_bypass(self.application)
        self.assertEqual(result.id, self.high_score_full_bypass_partner.id)

    @patch('juloserver.julo.services2.high_score.get_salaried')
    def test_high_score_full_bypass_partnership_not_found_and_use_j1(self, mock_get_salaried):
        self.high_score_full_bypass_partner.delete()
        mock_get_salaried.return_value = self.is_salaried
        high_score_full_bypass = HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
        )
        result = feature_high_score_full_bypass(self.application)
        self.assertEqual(result.id, high_score_full_bypass.id)
