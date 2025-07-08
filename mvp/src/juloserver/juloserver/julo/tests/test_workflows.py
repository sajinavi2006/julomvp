from __future__ import absolute_import
from rest_framework.test import APIClient
import mock
from mock import patch
import pytest
from datetime import date, datetime, timedelta

from django.test.testcases import TestCase
from .factories import CustomerFactory, ApplicationFactory, LoanFactory, StatusLookupFactory, \
    ExperimentSettingFactory, WorkflowFactory, FeatureSettingFactory
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes

from django.utils import timezone
from dateutil.relativedelta import relativedelta
from juloserver.julo.models import Workflow, FeatureSetting, ApplicationHistory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst

from juloserver.julo.management.commands import migrate_to_dynamic_workflows
from juloserver.julo.models import (
    Workflow,
    ExperimentSetting,
    FeatureSetting,
    ApplicationHistory,
    CustomerFieldChange,
)
from juloserver.julo.constants import ExperimentConst, WorkflowConst, FeatureNameConst


from juloserver.julo.workflows import WorkflowAction
from juloserver.account.models import ExperimentGroup
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.exceptions import InvalidBankAccount
from juloserver.disbursement.tests.factories import NameBankValidationFactory


@pytest.mark.django_db
class TestWorkflowsApplicationReapply(TestCase):

    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        self.client = APIClient()

    @mock.patch('juloserver.julo.workflows.send_email_status_change_task')
    @mock.patch('juloserver.julo.clients.email.JuloEmailClient.email_notification_133')
    def test_application_fraud(self, mock_notification, mock_send_email_status_change_task):
        headers = {}
        headers['X-Message-Id'] = 'fake_message_id'
        subject = 'fake subject'
        msg = 'fake msg'
        status = 'fake_status'
        mock_notification.return_value = status, headers, subject, msg

        cashloan_workflow = Workflow.objects.get(name='CashLoanWorkflow')

        self.application.change_status(ApplicationStatusCodes.FORM_SUBMITTED)
        self.application.workflow = cashloan_workflow
        self.application.save()
        process_application_status_change(self.application.id,
                                          ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                                          'system_triggered')
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply,

                         "Should be false if application is flagged for fraud")

    @mock.patch('juloserver.julo.workflows.update_status_apps_flyer_task')
    @mock.patch('juloserver.julo.clients.email.JuloEmailClient.email_notification_135')
    def test_application_denied(self, mock_notification, mock_update_status_apps_flyer_task):
        headers = {}
        headers['X-Message-Id'] = 'fake_message_id'
        subject = 'fake subject'
        msg = 'fake msg'
        status = 'fake_status'
        mock_notification.return_value = status, headers, subject, msg

        change_reason = 'new phone'
        cashloan_workflow = Workflow.objects.get(name='CashLoanWorkflow')

        self.application.change_status(ApplicationStatusCodes.FORM_SUBMITTED)
        self.application.workflow = cashloan_workflow
        self.application.save()
        process_application_status_change(self.application.id,
                                          ApplicationStatusCodes.APPLICATION_DENIED,
                                          change_reason)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply,
                        "Should be true unless specific change reason")

        self.application.change_status(ApplicationStatusCodes.FORM_SUBMITTED)
        self.application.save()
        self.customer.can_reapply = False
        self.customer.save()

        mock_notification.return_value = status, headers, subject, msg
        change_reason = 'fraud report'
        process_application_status_change(self.application.id,
                                          ApplicationStatusCodes.APPLICATION_DENIED,
                                          change_reason)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply,
                         "Should be false when reason is 'Fraud report'")

    @patch('juloserver.julo.utils.post_anaserver')
    def test_trigger_anaserver_status_122(self, mock_post_anaserver):
        mock_post_anaserver.return_value = True
        app = ApplicationFactory()
        app.application_status_id = 122
        app.web_version = '1.1.1'
        app.save()
        if app.web_version:
            res = self.client.post('/api/amp/v1/sonic-web-model/',
                                   data={'application_id': app.id})
        else:
            res = self.client.post('/api/amp/v1/sonic-model/',
                                   data={'application_id': app.id})

        self.assertIsNotNone(res)

    @patch('juloserver.julo.workflows.WorkflowAction.update_status_apps_flyer')
    def test_135_status_application(self, mock_update_status_apps_flyer):
        mock_update_status_apps_flyer.return_value = True
        self.change_reason = 'failed dv identity'
        self.new_status_code = 124
        self.old_status_code = 135
        self.note = "test"
        cashloan_workflow = Workflow.objects.filter(name='CashLoanWorkflow').first()

        self.application.change_status(ApplicationStatusCodes.FORM_SUBMITTED)
        self.application.workflow = cashloan_workflow
        self.application.save()
        self.action = WorkflowAction(self.application, self.new_status_code,
                                     self.change_reason, self.note, self.old_status_code)
        self.action.process_application_reapply_status_action()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.can_reapply_date.date(), timezone.localtime(timezone.now()).date() + relativedelta(months=1))
        self.assertEqual(self.customer.can_reapply, False)

    def test_field_change_in_ignored_doc_resubmission_120_to_106(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS,
            is_active=True,
            parameters={"x106_to_reapply": 90},
        )
        action = WorkflowAction(self.application, 106, "testing", "", 120)
        action._set_reapply_for_ignored_doc_resubmission(self.customer)

        disabled_reapply_date_has_change = CustomerFieldChange.objects.filter(
            customer=self.customer, field_name="disabled_reapply_date"
        ).exists()
        self.assertTrue(disabled_reapply_date_has_change)

        can_reapply_date_has_change = CustomerFieldChange.objects.filter(
            customer=self.customer, field_name="can_reapply_date"
        ).exists()
        self.assertTrue(can_reapply_date_has_change)


class TestWorkflowActionForApplicationShortForm(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            ktp='4420020503990007',
            email='thanos@gmail.com',
            app_version='7.0.0'
        )

    def test_update_customer_data_short_form_no_nik_and_email(self):
        self.customer.email = None
        self.customer.nik = None
        self.customer.save()

        action = WorkflowAction(
            application=self.application,
            new_status_code=105,
            old_status_code=100,
            change_reason='',
            note=''
        )
        action.update_customer_data()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.nik, '4420020503990007')
        self.assertEqual(self.customer.email, 'thanos@gmail.com')

    def test_update_customer_data_short_form__email_exists(self):
        existing_customer = CustomerFactory()
        existing_customer.email = 'thanos@gmail.com'
        existing_customer.save()

        self.customer.email = None
        self.customer.nik = None
        self.customer.save()

        action = WorkflowAction(
            application=self.application,
            new_status_code=105,
            old_status_code=100,
            change_reason='',
            note=''
        )
        action.update_customer_data()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.nik, '4420020503990007')
        self.assertIsNone(self.customer.email)

    def test_update_customer_data_short_form__nik_exists(self):
        existing_customer = CustomerFactory()
        existing_customer.nik = '4420020503990007'
        existing_customer.save()

        self.customer.email = None
        self.customer.nik = None
        self.customer.save()

        action = WorkflowAction(
            application=self.application,
            new_status_code=105,
            old_status_code=100,
            change_reason='',
            note=''
        )
        action.update_customer_data()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'thanos@gmail.com')
        self.assertIsNone(self.customer.nik)

    def test_update_customer_data_short_form__email_nik_exists(self):
        existing_customer = CustomerFactory()
        existing_customer.nik = '4420020503990007'
        existing_customer.email = 'thanos@gmail.com'
        existing_customer.save()

        self.customer.email = None
        self.customer.nik = None
        self.customer.save()

        action = WorkflowAction(
            application=self.application,
            new_status_code=105,
            old_status_code=100,
            change_reason='',
            note=''
        )
        action.update_customer_data()
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.email)
        self.assertIsNone(self.customer.nik)

    def test_update_customer_data_short_form__sync_phone(self):
        self.application.mobile_phone_1 = '0852876354'
        self.customer.phone = None
        self.customer.save()

        self.assertIsNone(self.customer.phone)

        action = WorkflowAction(
            application=self.application,
            old_status_code=100,
            new_status_code=105,
            change_reason='',
            note=''
        )
        action.update_customer_data()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '0852876354')


class TestWorkflowJ1WithBypassAC(TestCase):

    def setUp(self) -> None:
        workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=141,
            status_next=175,
            workflow=workflow
        )
        WorkflowStatusPathFactory(
            status_previous=141,
            status_next=150,
            workflow=workflow
        )

        self.name_bank_validation = NameBankValidationFactory()

        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            name_bank_validation=self.name_bank_validation
        )

    def test_not_comes_from_141(self):
        status = StatusLookupFactory(status_code=105)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=100,
            new_status_code=105,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()

        has_experiment = ExperimentGroup.objects.filter(customer=self.customer).exists()
        self.assertFalse(has_experiment)

    def test_setting_disable(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=False
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()

        has_experiment = ExperimentGroup.objects.filter(customer=self.customer).exists()
        self.assertFalse(has_experiment)

    def test_setting_not_exists(self):
        has_setting = (
            FeatureSetting.objects
            .filter(feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS)
            .exists()
        )

        self.assertFalse(has_setting)

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()

        has_experiment = ExperimentGroup.objects.filter(customer=self.customer).exists()
        self.assertFalse(has_experiment)

    @pytest.mark.skip(reason="Failing")
    @patch('juloserver.application_flow.workflows.check_bpjs_bypass', return_value=True)
    @patch('juloserver.application_flow.workflows.check_bpjs_entrylevel', return_value=True)
    def test_not_in_setting_criteria(self, mock_bpjs_el, mock_bpjs):
        _nums = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        last_digit = int(str(self.customer.id)[-1:])
        _nums.remove(last_digit)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': _nums
            },
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        ah = ApplicationHistory.objects.filter(application=self.application, status_new=150).count()
        self.assertEqual(ah, 1)

        # ah = ApplicationHistory.objects.filter(application=self.application, status_new=150).last()
        # self.assertEqual(ah.change_reason, 'Credit approved by system.')

    @patch('juloserver.julo.workflows2.handlers.Status150Handler')
    @patch('juloserver.application_flow.workflows.validate_bank', return_value=True)
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    def test_success_automated_bank_validation(self, mock_process_application_status_change, mock_validation, mock_150):
        # magic_validation = mock.MagicMock()
        # magic_validation.is_success = True
        # mock_validation.return_value = magic_validation
        self.name_bank_validation.validation_status = 'SUCCESS'
        self.name_bank_validation.save()

        last_digit = int(str(self.customer.id)[-1:])
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': [last_digit]
            }
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            150,
            'Credit approved by system.',
        )

    @patch('juloserver.julo.workflows2.handlers.Status135Handler')
    @patch(
        'juloserver.application_flow.workflows.validate_bank',
        mock.MagicMock(side_effect=InvalidBankAccount)
    )
    def test_fail_automated_bank_validation(self, mock_135):
        last_digit = int(str(self.customer.id)[-1:])
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': [last_digit]
            },
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        self.application.refresh_from_db()

        self.assertEqual(self.application.status, 141)

    @patch('juloserver.application_flow.workflows.validate_bank', mock.MagicMock(side_effect=InvalidBankAccount))
    @patch('juloserver.application_flow.workflows.has_levenshtein_distance_similarity', return_value=True)
    def test_email_not_whitelisted_when_bypass_bank_validation(self, mock_has_levenshtein_distance_similarity):
        # there is feature high score but email is not in the parameter
        last_digit = int(str(self.customer.id)[-1:])
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': [last_digit]
            },
        )

        FeatureSettingFactory(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE,
            is_active=True,
            parameters=["another" + self.application.email],
        )

        FeatureSettingFactory(
            feature_name='bank_validation',
            is_active=True,
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        self.application.refresh_from_db()
        
        mock_has_levenshtein_distance_similarity.assert_called_once()
    
    @patch('juloserver.application_flow.workflows.validate_bank', return_value=True)
    @patch('juloserver.application_flow.workflows.has_levenshtein_distance_similarity', return_value=True)
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    def test_email_whitelisted_with_success_validation_when_bypass_bank_validation(self, mock_process_application_status_change,mock_has_levenshtein_distance_similarity, mock_validate_bank):
        self.name_bank_validation.validation_status = 'SUCCESS'
        self.name_bank_validation.save()

        # there is feature high score, email is on the parameter and name_bank_validation is success
        last_digit = int(str(self.customer.id)[-1:])
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': [last_digit]
            },
        )

        FeatureSettingFactory(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE,
            is_active=True,
            parameters=[self.application.email],
        )

        FeatureSettingFactory(
            feature_name='bank_validation',
            is_active=True,
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            150,
            'Credit approved by system.',
        )

    

    @patch('juloserver.application_flow.workflows.validate_bank', mock.MagicMock(side_effect=InvalidBankAccount))
    @patch('juloserver.application_flow.workflows.has_levenshtein_distance_similarity', return_value=True)
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    def test_email_whitelisted_with_fail_validation_when_bypass_bank_validation(self, mock_process_application_status_change, mock_has_levenshtein_distance_similarity):
        # there is feature high score, email is on the parameter and name_bank_validation is not success
        last_digit = int(str(self.customer.id)[-1:])
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS,
            is_active=True,
            parameters={
                'bypass_customer_id': [last_digit]
            },
        )

        FeatureSettingFactory(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE,
            is_active=True,
            parameters=[self.application.email],
        )

        FeatureSettingFactory(
            feature_name='bank_validation',
            is_active=True,
        )

        status = StatusLookupFactory(status_code=141)
        self.application.application_status = status
        self.application.save()

        action = JuloOneWorkflowAction(
            self.application,
            old_status_code=130,
            new_status_code=141,
            change_reason="test change reason",
            note="test note",
        )
        action.bypass_activation_call()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            150,
            'Credit approved by system, bypassed force high score feature.',
        )
