from __future__ import absolute_import
import mock
import pytest
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import (
    CustomerFactory,
    WorkflowFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    LoanFactory,
    ImageFactory,
    ApplicationJ1Factory
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Workflow
from juloserver.julo.services import process_application_status_change, normal_application_status_change
from juloserver.application_flow.services import ApplicationTagTracking
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory


@pytest.mark.django_db
class TestWorkflowsApplicationReapply(TestCase):

    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application)

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
        change_reason = 'fraud report'
        process_application_status_change(self.application.id,
                                          ApplicationStatusCodes.APPLICATION_DENIED,
                                          change_reason)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply,
                         "Should be false when reason is 'Fraud report'")

    def test_status_should_not_change_when_not_latest_application(self):
        ApplicationFactory(customer=self.customer)
        result = process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.FORM_SUBMITTED,
            'only test'
        )
        self.assertFalse(result)

    def test_status_should_not_change_when_has_no_application(self):
        result = process_application_status_change(
            9537895734897539,
            ApplicationStatusCodes.FORM_SUBMITTED,
            'only test'
        )
        self.assertFalse(result)


class TestChangeStatusTag(TestCase):
    
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='LegacyWorkflow')
        self.application = ApplicationFactory(customer=self.customer,
                                              workflow=self.workflow)
        self.application_history = ApplicationHistoryFactory(application_id=self.application.id)
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type='paystub')

    def test_mandatory_docs_tag_105_106(self):
        tag_tracer = ApplicationTagTracking(self.application, 105, 106)
        tag_tracer._hsfbp = False
        tag_tracer._c_score = False
        tracking = tag_tracer.is_mandatory_docs()

        assert tracking == 0

    def test_dv_tag_121_124(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 124)
        tag_tracer.by_who = 1
        tag_tracer._sonic = True
        tracking = tag_tracer.is_dv()

        assert tracking == 4

    def test_dv_tag_121_124_fail(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 124)
        tag_tracer.by_who = 1
        tag_tracer._sonic = False
        tracking = tag_tracer.is_dv()

        assert tracking == 3

    def test_dv_tag_121_122(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 122)
        tag_tracer.by_who = 1
        tracking = tag_tracer.is_dv()

        assert tracking == 1

    def test_dv_tag_121_131(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 131)
        tag_tracer.by_who = 1
        tracking = tag_tracer.is_dv()

        assert tracking == 0

    def test_dv_tag_121_135(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 135, 'failed pv employer')
        tag_tracer.by_who = 1
        tracking = tag_tracer.is_dv()

        assert tracking == -1

    def test_dv_tag_121_135_blacklisted(self):
        tag_tracer = ApplicationTagTracking(self.application, 121, 135, 'job type blacklisted')
        tag_tracer.by_who = 1
        tracking = tag_tracer.is_dv()

        assert tracking == -2


class TestApplicationStatusChangeMissingEmergencyContact(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)

    def test_missing_emergency_contact(self):
        self.application.application_status_id = 150
        self.application.onboarding_id = 9
        self.application.kin_mobile_phone = None
        self.application.save()
        WorkflowStatusPathFactory(
            status_previous=150,
            status_next=188,
            type='happy',
            is_active=True,
            workflow=self.application.workflow,
        )
        process_application_status_change(
            self.application.id, ApplicationStatusCodes.LOC_APPROVED,
            "Credit limit activated",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 188)

    def test_success_move_to_190(self):
        self.application.application_status_id = 150
        self.application.onboarding_id = 9
        self.application.save()
        WorkflowStatusPathFactory(
            status_previous=150,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.application.workflow,
        )
        process_application_status_change(
            self.application.id, ApplicationStatusCodes.LOC_APPROVED,
            "Credit limit activated",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 190)
