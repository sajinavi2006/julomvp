from datetime import timedelta, datetime
from juloserver.fraud_security.tests.factories import FraudBlacklistedASNFactory
from juloserver.application_flow.factories import ApplicationRiskyCheckFactory

from mock import patch, ANY

from django.test import TestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta

import juloserver.julo_starter.tasks
from juloserver.bpjs.tests.factories import BpjsApiLogFactory
from juloserver.julo.constants import (
    WorkflowConst,
    FeatureNameConst,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    CustomerFactory,
    DeviceIpHistoryFactory,
    VPNDetectionFactory,
    WorkflowFactory,
    ApplicationFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
    OnboardingEligibilityCheckingFactory,
    FDCInquiryFactory,
    AuthUserFactory,
    DeviceFactory,
    FeatureSettingFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    ApplicationUpgradeFactory,
)
from juloserver.julo.models import Application
from juloserver.julo_starter.tasks.app_tasks import (
    run_application_expired_subtask,
    trigger_form_partial_expired_julo_starter,
    enable_reapply_for_rejected_external_check,
    trigger_revert_application_upgrade,
    handle_julo_starter_binary_check_result,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory

from juloserver.julo_starter.constants import NotificationSetJStarter
from juloserver.julo_starter.tasks.app_tasks import trigger_push_notif_check_scoring
from juloserver.julo_starter.workflow import JuloStarterWorkflowAction
from juloserver.account.tests.factories import (
    AffordabilityHistoryFactory,
    AccountLookupFactory,
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.fraud_security.binary_check import BlacklistedCompanyHandler
import pytest


class TestTaskApplicationExpired(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=105, status_next=106, type='detour', workflow=self.workflow_jstarter
        )
        self.workflow_status_path_100_106 = WorkflowStatusPathFactory(
            status_previous=100, status_next=106, type='detour', workflow=self.workflow_jstarter
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_jstarter,
        )
        self.application.application_status = StatusLookupFactory(status_code=105)
        self.application.save()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.FORM_PARTIAL
        )

    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_case_for_expired_application(self, process_reapply, trigger_ana):
        """
        To check application stay on x105
        Should be moved to x106
        """

        update_time = timezone.now() - relativedelta(days=90)
        self.application_history.cdate = update_time
        self.application_history.save()
        run_application_expired_subtask(
            self.application.id, update_time, self.application.application_status_id
        )
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        )

    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_case_for_not_expired_application(self, process_reapply, trigger_ana):
        """
        To check application stay on x105
        Should be not moved to x106
        """

        update_time = timezone.now()
        self.application_history.cdate = update_time
        self.application_history.save()
        run_application_expired_subtask(
            self.application.id, update_time, self.application.application_status_id
        )
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL
        )

    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    @patch('juloserver.julo_starter.tasks.app_tasks.run_application_expired_subtask')
    def test_call_task_expired_application(self, run_expired, process_reapply, trigger_ana):
        """
        To check call the async task
        """

        update_time = timezone.now() - relativedelta(days=5)
        self.application_history.cdate = update_time
        self.application_history.save()
        trigger_form_partial_expired_julo_starter()
        assert run_expired.delay.called

    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_case_for_not_expired_application_x100(self, process_reapply, trigger_ana):
        """
        To check application stay on x100
        Should be not moved to x106
        """

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()
        update_time = timezone.now()
        self.application_history.cdate = update_time
        self.application_history.save()
        run_application_expired_subtask(
            self.application.id, update_time, self.application.application_status_id
        )
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_CREATED
        )

    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_case_for_expired_application_x100(self, process_reapply, trigger_ana):
        """
        To check application stay on x100
        Should be moved to x106
        """

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()
        update_time = timezone.now() - relativedelta(days=90)
        self.application_history.cdate = update_time
        self.application_history.save()
        run_application_expired_subtask(
            self.application.id, update_time, self.application.application_status_id
        )
        self.application.refresh_from_db()
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        )


class TestEnableReapplyForRejectedExternalCheck(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(can_reapply=False)
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)

        self.fdc_inquiry = FDCInquiryFactory()
        self.bpjs_log = BpjsApiLogFactory()

        # self.dukcapil = DukcapilResponseFactory(application=self.application)
        self.oec = OnboardingEligibilityCheckingFactory(
            customer=self.customer,
            fdc_inquiry_id=self.fdc_inquiry.id,
            bpjs_api_log=self.bpjs_log,
            # dukcapil_response=self.dukcapil,
        )

    def test_do_nothing_when_has_workflow(self):
        # j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)
        application.workflow = self.workflow_jstarter
        application.save()

        month_ago = timezone.now() - timedelta(days=31)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_check = 2
        self.fdc_inquiry.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_already_in_reapply_mode(self):
        month_ago = timezone.now() - timedelta(days=31)

        self.customer.can_reapply = True
        self.customer.save()

        _udate = self.customer.udate

        self.fdc_inquiry.cdate = month_ago
        self.fdc_check = 2
        self.fdc_inquiry.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)
        self.assertEqual(_udate, self.customer.udate)

    def test_do_nothing_when_only_fdc_1_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 1
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_mode_when_only_fdc_2_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)

    def test_do_nothing_when_only_fdc_error_2_less_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=30)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_fdc_error_2_in_34_days(self):
        month_ago = timezone.now() - timedelta(days=34)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_mode_when_only_fdc_3_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)

    def test_do_nothing_when_only_fdc_error_3_less_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=30)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_fdc_error_3_in_34_days(self):
        month_ago = timezone.now() - timedelta(days=34)
        self.fdc_inquiry.cdate = month_ago
        self.fdc_inquiry.save()
        self.oec.fdc_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_bpjs_1_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 1
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_mode_when_only_bpjs_2_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)

    def test_do_nothing_when_only_bpjs_error_2_less_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=30)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_bpjs_error_2_in_34_days(self):
        month_ago = timezone.now() - timedelta(days=34)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 2
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_mode_when_only_bpjs_3_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)

    def test_do_nothing_when_only_bpjs_error_3_less_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=30)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_bpjs_error_3_in_34_days(self):
        month_ago = timezone.now() - timedelta(days=34)
        self.bpjs_log.cdate = month_ago
        self.bpjs_log.save()
        self.oec.bpjs_check = 3
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_dukcapil_1_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)

        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()

        self.oec.dukcapil_response = dukcapil
        self.oec.dukcapil_check = 1
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_mode_when_only_dukcapil_3_more_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=31)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()

        self.oec.dukcapil_check = 3
        self.oec.dukcapil_response = dukcapil
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)

    def test_do_nothing_when_only_dukcapil_error_3_less_than_31_days(self):
        month_ago = timezone.now() - timedelta(days=30)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()
        self.oec.dukcapil_check = 3
        self.oec.dukcapil_response = dukcapil
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_only_dukcapil_error_3_in_34_days(self):
        month_ago = timezone.now() - timedelta(days=34)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()
        self.oec.dukcapil_check = 3
        self.oec.dukcapil_response = dukcapil
        self.oec.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_do_nothing_when_referral_is_blocked(self):
        month_ago = timezone.now() - timedelta(days=31)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()

        self.oec.dukcapil_check = 3
        self.oec.dukcapil_response = dukcapil
        self.oec.save()

        self.application = application
        self.application.referral_code = 'mduckjulo'
        self.application.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)

    def test_change_reapply_when_referral_is_not_blocked(self):
        month_ago = timezone.now() - timedelta(days=31)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)

        dukcapil = DukcapilResponseFactory(application=application)
        dukcapil.cdate = month_ago
        dukcapil.save()

        self.oec.dukcapil_check = 3
        self.oec.dukcapil_response = dukcapil
        self.oec.save()

        self.application = application
        self.application.referral_code = 'SomeOtherCode'
        self.application.save()

        enable_reapply_for_rejected_external_check()

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.can_reapply)


class TestAppNotificationTask(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application = ApplicationFactory(customer=self.customer, workflow=starter_workflow)
        self.device = DeviceFactory(gcm_reg_id="djP4BDXjQe6oZ_nYhIHp9V", customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE,
            category='application',
            description='testing',
            parameters={
                "dukcapil_true_heimdall_true": {
                    "title": "Selamat Akun Kamu Sudah Aktif!",
                    "body": "Testing bodyr",
                    "destination": "julo_starter_second_check_ok",
                },
                "dukcapil_false": {
                    "title": "Pembuatan Akun JULO Starter Gagal",
                    "body": "Testing body",
                    "destination": "julo_starter_second_check_rejected",
                },
                "dukcapil_true_heimdall_false": {
                    "title": "Pembuatan Akun JULO Starter Gagal",
                    "body": "Testing body",
                    "destination": "julo_starter_second_check_j1_offer",
                },
            },
        )

        self.feature_setting_sphinx = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_THRESHOLD,
            category='application',
            description='testing',
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

        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.action = JuloStarterWorkflowAction(
            application=self.application,
            old_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            new_status_code=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            change_reason='Testing',
            note='',
        )
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.pd_credit_model = PdCreditModelResultFactory(
            pgood=0.95,
            application_id=self.application.id,
            customer_id=self.customer.id,
            probability_fpd=0.9275418594,
            credit_score_type='A',
        )
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000
        )
        self.account_lookup = AccountLookupFactory(
            name='JULOSTARTER',
            payment_frequency='monthly',
            moengage_mapping_number='1',
            workflow=starter_workflow,
        )
        self.workflow_path_109 = WorkflowStatusPathFactory(
            type='happy',
            status_next=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
            status_previous=ApplicationStatusCodes.FORM_PARTIAL,
            workflow=starter_workflow,
        )
        self.workflow_path_121 = WorkflowStatusPathFactory(
            type='happy',
            status_next=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            status_previous=ApplicationStatusCodes.FORM_PARTIAL,
            workflow=starter_workflow,
        )
        self.workflow_path_135 = WorkflowStatusPathFactory(
            type='happy',
            status_next=ApplicationStatusCodes.APPLICATION_DENIED,
            status_previous=ApplicationStatusCodes.FORM_PARTIAL,
            workflow=starter_workflow,
        )
        self.status_121 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.status_109 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        )
        self.status_135 = StatusLookupFactory(status_code=ApplicationStatusCodes.APPLICATION_DENIED)

    @pytest.mark.skip(reason="Flaky")
    @patch("juloserver.julo.clients.get_julo_pn_client")
    def test_result_true_for_notification(self, mock_pn):
        result = trigger_push_notif_check_scoring(
            self.application.id, NotificationSetJStarter.KEY_MESSAGE_OK
        )
        self.assertTrue(result)

    @patch("juloserver.julo.clients.get_julo_pn_client")
    def test_result_false_for_notification(self, mock_pn):
        self.device.delete()
        result = trigger_push_notif_check_scoring(
            self.application.id, NotificationSetJStarter.KEY_MESSAGE_OK
        )
        self.assertFalse(result)


class TestRevertApplicationUpgrade(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

        starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)

        self.j1_application = ApplicationFactory(customer=self.customer, workflow=self.j1_workflow)
        self.turbo_application = ApplicationFactory(
            customer=self.customer, workflow=starter_workflow
        )

        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.turbo_application.id,
            is_upgrade=1,
        )

        self.today = datetime(2023, 6, 28)

        WorkflowStatusPathFactory(
            status_previous=191,
            status_next=190,
            type='detour',
            is_active=True,
            workflow=starter_workflow,
        )

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo_starter.tasks.timezone.localtime')
    def test_x106_case(self, mock_today, mock_application_change):
        self.customer.can_reapply = False
        self.customer.save()

        self.j1_application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        self.j1_application.save()

        self.turbo_application.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.turbo_application.save()

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            cdate=self.today - relativedelta(days=13),
        )
        self.j1_application_history.save()
        self.assertEqual(
            self.turbo_application.application_status_id,
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        )

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        self.j1_application_history.cdate = self.today - relativedelta(days=13)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()

        self.j1_application_history.cdate = self.today - relativedelta(days=15)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()
        self.customer.refresh_from_db()
        mock_application_change.called_once_with(
            self.turbo_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'upgrade_grace_period_end',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo_starter.tasks.timezone.localtime')
    def test_x135_one_month_case(self, mock_today, mock_application_change):
        self.customer.can_reapply = False
        self.customer.save()

        self.j1_application.application_status_id = ApplicationStatusCodes.APPLICATION_DENIED
        self.j1_application.save()

        self.turbo_application.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.turbo_application.save()

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='failed dv expired ktp',
        )
        self.j1_application_history.cdate = self.today - relativedelta(days=29)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()

        mock_today.return_value = self.today
        self.j1_application_history.cdate = self.today - relativedelta(days=31)
        self.j1_application_history.save()
        trigger_revert_application_upgrade()

        self.turbo_application.refresh_from_db()
        self.customer.refresh_from_db()
        mock_application_change.called_once_with(
            self.turbo_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'upgrade_grace_period_end',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo_starter.tasks.timezone.localtime')
    def test_x135_three_month_case(self, mock_today, mock_application_change):
        self.customer.can_reapply = False
        self.customer.save()

        self.j1_application.application_status_id = ApplicationStatusCodes.APPLICATION_DENIED
        self.j1_application.save()

        self.turbo_application.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.turbo_application.save()

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='cannot afford loan',
        )
        self.j1_application_history.cdate = self.today - relativedelta(days=89)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()

        self.j1_application_history.cdate = self.today - relativedelta(days=91)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()
        self.customer.refresh_from_db()
        mock_application_change.called_once_with(
            self.turbo_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'upgrade_grace_period_end',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo_starter.tasks.timezone.localtime')
    def test_x135_one_year_case(self, mock_today, mock_application_change):
        self.customer.can_reapply = False
        self.customer.save()

        self.j1_application.application_status_id = ApplicationStatusCodes.APPLICATION_DENIED
        self.j1_application.save()

        self.turbo_application.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.turbo_application.save()

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='negative payment history with julo',
        )
        self.j1_application_history.cdate = self.today - relativedelta(years=+1, days=-1)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()

        self.j1_application_history.cdate = self.today - relativedelta(years=+1, days=1)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()
        self.customer.refresh_from_db()
        mock_application_change.called_once_with(
            self.turbo_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'upgrade_grace_period_end',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo_starter.tasks.timezone.localtime')
    def test_more_than_one_application_upgrade(self, mock_today, mock_application_change):
        self.customer.can_reapply = False
        self.customer.save()

        # create one more application upgrade
        j1_application_2 = ApplicationFactory(customer=self.customer, workflow=self.j1_workflow)
        ApplicationUpgradeFactory(
            application_id_first_approval=self.turbo_application.id,
            application_id=self.j1_application.id,
        )

        self.j1_application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        self.j1_application.save()

        self.turbo_application.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.turbo_application.save()

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            cdate=self.today - relativedelta(days=13),
        )
        self.j1_application_history.save()
        self.assertEqual(
            self.turbo_application.application_status_id,
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        )

        self.j1_application_history = ApplicationHistoryFactory(
            application_id=self.j1_application.id,
            status_new=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        self.j1_application_history.cdate = self.today - relativedelta(days=13)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()

        self.j1_application_history.cdate = self.today - relativedelta(days=15)
        self.j1_application_history.save()

        mock_today.return_value = self.today
        trigger_revert_application_upgrade()
        self.turbo_application.refresh_from_db()
        self.customer.refresh_from_db()
        mock_application_change.assert_not_called()

        Application.objects.filter(id=j1_application_2.id).delete()

        trigger_revert_application_upgrade()
        mock_application_change.called_once_with(
            self.turbo_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'upgrade_grace_period_end',
        )

    @patch("juloserver.julo.clients.get_julo_pn_client")
    def test_revert_x190_does_not_trigger_pn(self, mock_pn):
        self.turbo_application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.turbo_application.save()

        self.turbo_application_history = ApplicationHistoryFactory(
            application_id=self.turbo_application.id,
            status_old=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
            status_new=ApplicationStatusCodes.LOC_APPROVED,
        )
        result = trigger_push_notif_check_scoring(
            self.turbo_application.id, NotificationSetJStarter.KEY_MESSAGE_FULL_LIMIT
        )
        self.assertFalse(result)


class TestHandleJuloStarterBinaryCheckResult(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

        starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)

        self.turbo_application = ApplicationFactory(
            customer=self.customer,
            workflow=starter_workflow,
        )
        self.turbo_application.application_status = StatusLookupFactory(status_code=109)
        self.turbo_application.application_status_id = 109
        self.turbo_application.save()

        self.today = datetime(2023, 6, 28)

        WorkflowStatusPathFactory(
            status_previous=109,
            status_next=133,
            type='graveyard',
            is_active=True,
            workflow=starter_workflow,
        )

    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch(
        'juloserver.customer_module.views.views_api_v3.determine_js_workflow',
        return_value='partial_limit',
    )
    @patch('juloserver.julo_starter.services.submission_process.binary_check_result')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_fraud_binary_check')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_application_status_change')
    def test_handle_julo_starter_binary_check_result_for_blacklisted_company(
        self,
        mock_process_application_status_change,
        mock_process_fraud_binary_check,
        mock_binary_check_result,
        mock_determine_js_worflow,
        mock_send_email_status_change_task,
    ):
        mock_binary_check_result.return_value = True
        mock_process_fraud_binary_check.return_value = False, BlacklistedCompanyHandler(
            self.turbo_application
        )
        handle_julo_starter_binary_check_result(self.turbo_application.id)
        mock_process_application_status_change.assert_called_once_with(
            application_id=self.turbo_application.id,
            new_status_code=133,
            change_reason='Fail to pass fraud binary check. [BlacklistedCompany]',
        )

    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch(
        'juloserver.customer_module.views.views_api_v3.determine_js_workflow',
        return_value='partial_limit',
    )
    @patch('juloserver.julo_starter.services.submission_process.binary_check_result')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_fraud_binary_check')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_application_status_change')
    def test_handle_julo_starter_binary_check_result_for_not_blacklisted_company(
        self,
        mock_process_application_status_change,
        mock_process_fraud_binary_check,
        mock_binary_check_result,
        mock_determine_js_worflow,
        mock_send_email_status_change_task,
    ):
        FeatureSettingFactory(
            feature_name="antifraud_api_onboarding",
            is_active=True,
            parameters={
                'turbo_109': False,
                'j1_x105': True,
                'j1_x120': True,
            },
        )
        mock_binary_check_result.return_value = True
        mock_process_fraud_binary_check.return_value = True, None
        handle_julo_starter_binary_check_result(self.turbo_application.id)
        mock_process_application_status_change.assert_called_once_with(
            self.turbo_application.id,
            121,
            change_reason='Julo Starter Verified',
        )

    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch(
        'juloserver.customer_module.views.views_api_v3.determine_js_workflow',
        return_value='partial_limit',
    )
    @patch('juloserver.julo_starter.services.submission_process.binary_check_result')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_fraud_binary_check')
    @patch('juloserver.julo_starter.tasks.app_tasks.process_application_status_change')
    def test_handle_julo_starter_binary_check_result_for_asn_blacklisted_user(
        self,
        mock_process_application_status_change,
        mock_process_fraud_binary_check,
        mock_binary_check_result,
        mock_determine_js_worflow,
        mock_send_email_status_change_task,
    ):

        application_risky_check = ApplicationRiskyCheckFactory(application=self.turbo_application)
        device_ip_history = DeviceIpHistoryFactory(customer=self.turbo_application.customer)
        vpn_detection = VPNDetectionFactory(
            ip_address='127.0.0.1', is_vpn_detected=True, extra_data={'org': 'testing_org'}
        )
        blocked_asn = FraudBlacklistedASNFactory(asn_data='testing_org')
        feature_blocked_asn = FeatureSettingFactory(feature_name=FeatureNameConst.BLACKLISTED_ASN)

        mock_binary_check_result.return_value = True
        mock_process_fraud_binary_check.return_value = True, None
        handle_julo_starter_binary_check_result(self.turbo_application.id)
        mock_process_application_status_change.assert_called_once_with(
            self.turbo_application.id,
            133,
            'Blacklisted ASN detected',
        )
