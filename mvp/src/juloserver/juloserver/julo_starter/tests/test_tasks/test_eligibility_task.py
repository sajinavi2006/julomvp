import mock

from mock import patch, ANY

from django.test import TestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.streamlined_communication.services import validate_action
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    WorkflowFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
    ApplicationHistory,
    OnboardingEligibilityCheckingFactory,
    AddressGeolocationFactory,
)
from juloserver.julo_starter.tasks import handle_julo_starter_generated_credit_model
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_starter.tasks.app_tasks import (
    run_application_expired_subtask,
    trigger_form_partial_expired_julo_starter,
)

from juloserver.fraud_security.tests.factories import FraudBlacklistedGeohash5Factory
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory


class TestHandleJuloStarterGeneratedCreditModel(TestCase):
    """
    Test related to these conditions are moved to TestCheckBPJSandDukcapilForTurbo
    - bpjs_check = 3
    - holdout conditions
    """

    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_THRESHOLD,
            parameters={
                "affordability_formula": 0.3,
                "high": {
                    "bottom_threshold": 0.8,
                    "max_limit": 3000000,
                    "min_limit": 1000000,
                    "max_duration": 3,
                },
                "mid": {
                    "bottom_threshold": 0.7,
                    "max_limit": 2000000,
                    "min_limit": 500000,
                    "max_duration": 3,
                },
                "low": {
                    "bottom_threshold": 0.51,
                    "max_limit": 1500000,
                    "min_limit": 500000,
                    "max_duration": 3,
                },
                "partial_limit_dv": 1,
            },
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        status105 = StatusLookupFactory(status_code=105)
        starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application = ApplicationFactory(customer=self.customer, workflow=starter_workflow)
        self.application.application_status = status105
        self.application.save()
        self.credit_model = PdCreditModelResultFactory(application_id=self.application.id)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=107)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=108)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=135)

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_no_sphinx_threshold(self, mock_process_fraud_check):
        self.assertEqual(self.application.status, 105)

        self.setting.delete()
        mock_process_fraud_check.return_value = False

        result = handle_julo_starter_generated_credit_model(self.application.id)

        self.assertIsNone(result)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 105)

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_sphinx_threshold_disabled(self, mock_process_fraud_check):
        self.setting.is_active = False
        self.setting.save()

        mock_process_fraud_check.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertIsNone(result)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 105)

    def test_no_application_found(self):
        result = handle_julo_starter_generated_credit_model(34895673498)
        self.assertIsNone(result)

    def test_application_not_in_julo_starter_workflow(self):
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.workflow = j1_workflow
        self.application.save()

        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertIsNone(result)

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_credit_model_not_found(self, mock_process_fraud_check):
        self.credit_model.delete()
        mock_process_fraud_check.return_value = False

        credit_model = PdCreditModelResult.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(credit_model)

        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertIsNone(result)

    def test_application_not_come_from_x105(self):
        status106 = StatusLookupFactory(status_code=106)
        self.application.application_status = status106
        self.application.save()

        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertIsNone(result)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 106)

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_pgood_below_normal_threshold(
        self, mock_process_fraud_check, mock_trigger_pn_emulator_detection
    ):
        self.credit_model.pgood = 0.3
        self.credit_model.save()

        mock_process_fraud_check.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 107)
        last_app_history = ApplicationHistory.objects.filter(application=self.application).last()
        self.assertEqual(last_app_history.change_reason, 'sphinx_threshold_failed')

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_pgood_above_normal_threshold(
        self, mock_process_fraud_check, mock_trigger_pn_emulator_detection
    ):
        self.credit_model.pgood = 0.63
        self.credit_model.save()

        mock_process_fraud_check.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 105)
        mock_trigger_pn_emulator_detection.delay.assert_called()

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_pgood_above_high_threshold(
        self, mock_process_fraud_check, mock_trigger_pn_emulator_detection
    ):
        self.credit_model.pgood = 0.87
        self.credit_model.save()

        mock_process_fraud_check.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 105)
        mock_trigger_pn_emulator_detection.delay.assert_called()

    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.check_is_good_score')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.binary_check_result')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_check_binary_result(
        self,
        mock_process_fraud_check,
        mock_binary_check_result,
        mock_check_is_good_score,
        mock_trigger_pn_emulator_detection,
    ):
        # binary check failed
        mock_process_fraud_check.return_value = False
        mock_binary_check_result.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 135)
        last_app_history = ApplicationHistory.objects.filter(application=self.application).last()
        self.assertEqual(last_app_history.change_reason, 'binary_check_failed')

        # binary check success
        mock_check_is_good_score.return_value = True
        mock_binary_check_result.return_value = True
        self.application.application_status_id = 105
        self.application.save()
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 105)
        mock_trigger_pn_emulator_detection.delay.assert_called_once()

    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.check_is_good_score')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.binary_check_result')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    def test_check_blacklisted_geohash5_after_binary_check_result(
        self,
        mock_process_fraud_check,
        mock_binary_check_result,
        mock_check_is_good_score,
        mock_trigger_pn_emulator_detection,
        mock_send_email_status_change_task,
    ):
        workflow = WorkflowFactory(name='JuloStarterWorkflow')
        WorkflowStatusPathFactory(workflow=workflow, status_previous=105, status_next=133)

        self.address_geolocation = AddressGeolocationFactory(application=self.application)
        self.address_geolocation_geohash = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation, geohash6='123456'
        )
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_BLACKLISTED_GEOHASH5,
            is_active=True,
        )
        FraudBlacklistedGeohash5Factory(geohash5='12345')

        # binary check failed
        mock_process_fraud_check.return_value = False
        mock_binary_check_result.return_value = False
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.assertEqual(result, 'success')

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 135)
        last_app_history = ApplicationHistory.objects.filter(application=self.application).last()
        self.assertEqual(last_app_history.change_reason, 'binary_check_failed')

        # binary check success
        mock_check_is_good_score.return_value = False
        mock_binary_check_result.return_value = True
        self.application.application_status_id = 105
        self.application.save()
        result = handle_julo_starter_generated_credit_model(self.application.id)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 133)
        mock_trigger_pn_emulator_detection.delay.assert_not_called()



class TestTurboValidateNotification(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            customer=self.customer,
            account=self.account,
        )

    def test_turbo_notification_validity(self):
        data = {}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        assert response.status_code == 400

        pn_list = [
            "julo_starter_eligbility_ok",
            "julo_starter_eligbility_j1_offer",
            "julo_starter_eligbility_rejected",
            "julo_starter_second_check_ok",
            "julo_starter_second_check_rejected",
            "julo_starter_second_check_ok_full_dv",
            "julo_starter_second_check_j1_offer",
            "julo_starter_full_limit",
        ]

        for pn_destination in pn_list:
            data = {'action': pn_destination}
            response = self.client.post(
                '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
            )

            assert response.status_code == 200
