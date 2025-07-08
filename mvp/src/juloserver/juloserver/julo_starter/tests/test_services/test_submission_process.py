from mock import patch
from rest_framework.test import APITestCase

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    MobileFeatureSettingFactory,
    FDCInquiryFactory,
    OnboardingEligibilityCheckingFactory,
    DeviceFactory,
    ApplicationFactory,
    WorkflowFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo_starter.services.submission_process import (
    run_fraud_check,
    check_fraud_result,
    check_affordability,
    binary_check_result,
)
from juloserver.application_flow.factories import (
    ApplicationRiskyCheckFactory,
    ApplicationRiskyDecisionFactory,
)
from juloserver.apiv2.tests.factories import AutoDataCheckFactory
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo_starter.services.services import is_eligible_bypass_to_x121


class TestRunFraudCheck(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.mfs = MobileFeatureSettingFactory(feature_name='bpjs_direct')
        self.fdc_inquiry = FDCInquiryFactory(customer_id=self.customer.id)
        self.onboarding_check = OnboardingEligibilityCheckingFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)
        self.JuloStarterWorkflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=133,
            type='happy',
            is_active=True,
            workflow=self.JuloStarterWorkflow,
        )
        self.application = ApplicationFactory()
        self.application.workflow = self.JuloStarterWorkflow
        self.application.application_status_id = 105
        self.application.save()

    @patch('juloserver.julo_starter.services.submission_process.check_application_risky')
    @patch(
        'juloserver.julo_starter.services.submission_process'
        '.check_application_liveness_detection_result'
    )
    @patch('juloserver.julo_starter.services.submission_process.trigger_passive_liveness')
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch('juloserver.julo_starter.services.submission_process.is_blacklist_android')
    def test_liveness_detection_failed(
        self,
        mock_is_blacklist_android,
        mock_send_email,
        mock_trigger_passive_liveness,
        mock_check_application_liveness_detection_result,
        mock_check_application_risky,
    ):
        mock_is_blacklist_android.return_value = False
        mock_check_application_liveness_detection_result.return_value = (
            False,
            'Liveness detection failed',
        )
        run_fraud_check(self.application)
        mock_check_application_risky.assert_not_called()

    @patch('juloserver.julo_starter.services.submission_process.check_application_risky')
    @patch(
        'juloserver.julo_starter.services.submission_process.'
        'check_application_liveness_detection_result'
    )
    @patch('juloserver.julo_starter.services.submission_process.trigger_passive_liveness')
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch('juloserver.julo_starter.services.submission_process.is_blacklist_android')
    def test_application_risky_check_failed(
        self,
        mock_is_blacklist_android,
        mock_send_email,
        mock_trigger_passive_liveness,
        mock_check_application_liveness_detection_result,
        mock_check_application_risky,
    ):
        mock_is_blacklist_android.return_value = False
        mock_check_application_liveness_detection_result.return_value = (True, '')
        mock_check_application_risky.return_value = (True, 'Found face similarity')
        result = run_fraud_check(self.application)
        mock_check_application_risky.assert_called_once()


class TestCheckFraudResult(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.mfs = MobileFeatureSettingFactory(feature_name='bpjs_direct')
        self.fdc_inquiry = FDCInquiryFactory(customer_id=self.customer.id)
        self.onboarding_check = OnboardingEligibilityCheckingFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)
        self.JuloStarterWorkflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=133,
            type='happy',
            is_active=True,
            workflow=self.JuloStarterWorkflow,
        )
        self.application = ApplicationFactory()
        self.application.workflow = self.JuloStarterWorkflow
        self.application.application_status_id = 105
        self.application.save()

    @patch(
        'juloserver.julo_starter.services.submission_process'
        '.check_application_liveness_detection_result'
    )
    @patch('juloserver.julo_starter.services.submission_process.trigger_passive_liveness')
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch('juloserver.julo_starter.services.submission_process.is_blacklist_android')
    def test_liveness_detection_failed(
        self,
        mock_is_blacklist_android,
        mock_send_email,
        mock_trigger_passive_liveness,
        mock_check_application_liveness_detection_result,
    ):
        mock_is_blacklist_android.return_value = False
        # bypass for active liveness
        mock_check_application_liveness_detection_result.return_value = (
            False,
            'failed active liveness',
        )
        result, reason = check_fraud_result(self.application)
        self.assertEqual(result, False)
        self.assertEqual(reason, '')

        # bypass for passive liveness
        mock_check_application_liveness_detection_result.return_value = (
            False,
            'failed passive liveness',
        )
        result, reason = check_fraud_result(self.application)
        self.assertEqual(result, False)
        self.assertEqual(reason, '')

    @patch(
        'juloserver.julo_starter.services.submission_process.'
        'check_application_liveness_detection_result'
    )
    @patch('juloserver.julo_starter.services.submission_process.trigger_passive_liveness')
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch('juloserver.julo_starter.services.submission_process.is_blacklist_android')
    def test_application_risky_check_failed(
        self,
        mock_is_blacklist_android,
        mock_send_email,
        mock_trigger_passive_liveness,
        mock_check_application_liveness_detection_result,
    ):
        mock_is_blacklist_android.return_value = False
        mock_check_application_liveness_detection_result.return_value = (True, '')

        # found face similariry
        application_risky = ApplicationRiskyCheckFactory(
            application=self.application, is_similar_face_suspicious=True
        )
        result, reason = check_fraud_result(self.application)
        self.assertEqual(result, False)

        # failed app risky check but bypass
        decision = ApplicationRiskyDecisionFactory(decision_name='NO DV BYPASS')
        application_risky.is_similar_face_suspicious = False
        application_risky.decision = decision
        application_risky.save()

        result, reason = check_fraud_result(self.application)
        self.assertEqual(result, False)
        self.assertEqual(reason, '')

    @patch(
        'juloserver.julo_starter.services.submission_process.'
        'check_application_liveness_detection_result'
    )
    def test_mock_response(self, mock_check_application_liveness_detection_result):
        FeatureSettingFactory(
            feature_name='app_risky_check_mock',
            is_active=True,
            parameters={
                "product": ["j-starter"],
                "latency": 10,
                "response_value": False,
            },
        )
        mock_check_application_liveness_detection_result.return_value = (True, '')
        result, reason = check_fraud_result(self.application)
        self.assertFalse(result)


class TestCheckAffordability(APITestCase):
    def setUp(self) -> None:
        self.application = ApplicationFactory()
        self.application.application_status_id = 105
        self.application.save()

    def test_wrong_application_status(self):
        self.application.application_status_id = 100
        self.application.save()
        self.assertFalse(check_affordability(self.application))

    @patch('juloserver.julo_starter.services.submission_process.check_black_list_android')
    def test_is_blacklisted_android(self, mock_check_black_list_android):
        mock_check_black_list_android.return_value = True
        self.assertFalse(check_affordability(self.application))

    @patch('juloserver.julo_starter.services.submission_process.binary_check_result')
    @patch('juloserver.julo_starter.services.submission_process.check_black_list_android')
    def test_failed_binary_check(self, mock_check_black_list_android, mock_binary_check_result):
        mock_check_black_list_android.return_value = False
        mock_binary_check_result.return_value = False
        self.assertFalse(check_affordability(self.application))

    @patch('juloserver.julo_starter.services.submission_process.check_is_good_score')
    @patch('juloserver.julo_starter.services.submission_process.check_black_list_android')
    def test_is_not_good_score(self, mock_check_black_list_android, mock_check_is_good_score):
        mock_check_black_list_android.return_value = False
        mock_check_is_good_score.return_value = False
        self.assertFalse(check_affordability(self.application))

    @patch('juloserver.julo_starter.services.submission_process.check_fraud_result')
    @patch('juloserver.julo_starter.services.submission_process.check_is_good_score')
    @patch('juloserver.julo_starter.services.submission_process.check_black_list_android')
    def test_is_fraud(
        self, mock_check_black_list_android, mock_check_is_good_score, mock_check_fraud_result
    ):
        mock_check_black_list_android.return_value = False
        mock_check_is_good_score.return_value = True
        mock_check_fraud_result.return_value = True, ''
        self.assertFalse(check_affordability(self.application))

    @patch('juloserver.julo_starter.services.submission_process.check_fraud_result')
    @patch('juloserver.julo_starter.services.submission_process.check_is_good_score')
    @patch('juloserver.julo_starter.services.submission_process.check_black_list_android')
    def test_success(
        self, mock_check_black_list_android, mock_check_is_good_score, mock_check_fraud_result
    ):
        mock_check_black_list_android.return_value = False
        mock_check_is_good_score.return_value = True
        mock_check_fraud_result.return_value = False, ''
        self.assertTrue(check_affordability(self.application))


class TestBinaryCheckResult(APITestCase):
    def setUp(self) -> None:
        self.application = ApplicationFactory()
        self.application.application_status_id = 105
        self.application.save()

    def test_failed(self):
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=False, data_to_check='test_failed'
        )
        result = binary_check_result(application=self.application)
        self.assertFalse(result)

    def test_success(self):
        # success
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check='test_failed'
        )
        result = binary_check_result(application=self.application)
        self.assertTrue(result)

        # failed but bypass
        AutoDataCheckFactory(
            id=999, application_id=self.application.id, is_okay=False, data_to_check='basic_savings'
        )
        result = binary_check_result(application=self.application)
        self.assertTrue(result)

        # failed but bypass
        AutoDataCheckFactory(
            id=6969,
            application_id=self.application.id,
            is_okay=False,
            data_to_check='inside_premium_area',
        )

        AutoDataCheckFactory(
            id=6970,
            application_id=self.application.id,
            is_okay=False,
            data_to_check='dynamic_check',
        )
        self.assertTrue(binary_check_result(application=self.application))

    def test_mock_response(self):
        FeatureSettingFactory(
            feature_name='binary_check_mock',
            is_active=True,
            parameters={
                "product": ["j-starter"],
                "latency": 10,
                "response_value": True,
            },
        )
        result = binary_check_result(application=self.application)
        self.assertTrue(result)


class TestByPassForExtraFormJStarter(APITestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.jstarter_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
            ),
            workflow=self.jstarter_workflow,
        )
        StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
        )
        WorkflowStatusPathFactory(
            status_previous=108,
            status_next=109,
            type='happy',
            is_active=True,
            workflow=self.jstarter_workflow,
        )
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            status_new=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
        )

    @patch('juloserver.julo_starter.services.services.binary_check_form_extra')
    def test_some_process_when_reach_x109_execute_binary_check(self, mock_binary_check_form_extra):

        self.application.update_safely(
            job_type='Pegawai swasta',
            job_industry='Admin / Finance / HR',
            job_description='Admin',
            company_name='Jula',
            payday=30,
            marital_status='Lajang',
            close_kin_name='Jack Mo',
            close_kin_mobile_phone='022198939822',
            kin_relationship='Orang tua',
            kin_name='Kin for name',
            kin_mobile_phone='089677537749',
            job_start='2022-12-02',
            last_education='SD',
            monthly_income=2500000,
            spouse_name=None,
            spouse_mobile_phone=None,
        )

        result = is_eligible_bypass_to_x121(self.application.id)
        self.application.refresh_from_db()
        self.assertTrue(result)
        mock_binary_check_form_extra.assert_called()
        self.assertEqual(self.application.job_type, 'Pegawai swasta')
        self.assertEqual(self.application.close_kin_mobile_phone, '022198939822')

    @patch('juloserver.julo_starter.services.services.binary_check_form_extra')
    def test_some_process_when_reach_x109_cannot_execute_binary_check(
        self, mock_binary_check_form_extra
    ):
        self.application.update_safely(
            job_type=None,
            job_industry='Admin / Finance / HR',
            job_description='Admin',
            company_name='Jula',
            payday=30,
            marital_status='Lajang',
            close_kin_name='Jack Mo',
            close_kin_mobile_phone='022198939822',
            kin_relationship='Orang tua',
            kin_name='Kin for name',
            kin_mobile_phone='089677537749',
            job_start='2022-12-02',
            last_education='SD',
            monthly_income=2500000,
        )

        result = is_eligible_bypass_to_x121(self.application.id)
        self.assertFalse(result)
        mock_binary_check_form_extra.assert_not_called()
        self.assertEqual(self.application.job_description, 'Admin')
        self.assertEqual(self.application.close_kin_mobile_phone, '022198939822')

    @patch('juloserver.julo_starter.services.services.binary_check_form_extra')
    def test_some_process_when_reach_x109_with_status_menikah(self, mock_binary_check_form_extra):
        self.application.update_safely(
            job_type='Pegawai swasta',
            job_industry='Admin / Finance / HR',
            job_description='Admin',
            company_name='Jula',
            payday=30,
            marital_status='Menikah',
            close_kin_name='Jack Mo',
            close_kin_mobile_phone='022198939822',
            kin_relationship='Orang tua',
            kin_name='Kin for name',
            kin_mobile_phone='089677537749',
            job_start='2022-12-02',
            last_education='SD',
            monthly_income=2500000,
            spouse_name=None,
            spouse_mobile_phone=None,
        )

        result = is_eligible_bypass_to_x121(self.application.id)
        self.application.refresh_from_db()
        self.assertFalse(result)
        mock_binary_check_form_extra.assert_not_called()

        self.application.update_safely(
            close_kin_name=None,
            close_kin_mobile_phone=None,
            spouse_name='for testing',
            spouse_mobile_phone='08928398322',
        )
        result = is_eligible_bypass_to_x121(self.application.id)
        self.application.refresh_from_db()
        self.assertTrue(result)
        mock_binary_check_form_extra.assert_called()
