from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv2.models import EtlJob
from juloserver.apiv2.tests.factories import (
    EtlJobFactory,
    PdCreditModelResultFactory,
)
from juloserver.bpjs.tests.factories import BpjsTaskFactory
from juloserver.cfs.constants import (
    CfsActionId,
    GoogleAnalyticsActionTracking,
    EtlJobType,
    CfsProgressStatus,
    VerifyStatus,
)
from juloserver.cfs.models import (
    CfsActionAssignment,
    CfsAssignmentVerification,
)
from juloserver.cfs.services import core_services
from juloserver.cfs.services.core_services import process_post_connect_bank
from juloserver.cfs.tests.factories import (
    CfsTierFactory,
    AgentFactory,
    CfsAssignmentVerificationFactory,
    CfsActionFactory,
    CfsActionAssignmentFactory,
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    ApplicationJ1Factory,
)

PACKAGE_NAME = 'juloserver.cfs.services.core_services'


@patch(f'{PACKAGE_NAME}.send_cfs_ga_event')
class TestProcessPostConnectBpjsSuccess(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.bpjs_task = BpjsTaskFactory()
        self.action = CfsActionFactory(
            id=3,
            is_active=True,
            action_code='connect_bpjs',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )

    def test_no_assignment(self, mock_send_cfs_ga_event):
        ret_val = core_services.process_post_connect_bpjs_success(self.application.id, self.customer.id, self.bpjs_task)
        self.assertFalse(ret_val)
        mock_send_cfs_ga_event.assert_called_once_with(self.customer, CfsActionId.CONNECT_BPJS, GoogleAnalyticsActionTracking.REFUSE)

    def test_assignment(self, mock_send_cfs_ga_event):
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.START
        )
        self.bpjs_task.update_safely(application=self.application)
        ret_val = core_services.process_post_connect_bpjs_success(
            self.application.id, self.customer.id, self.bpjs_task
        )
        self.assertTrue(ret_val)
        action_assignment = CfsActionAssignment.objects.filter(
            customer=self.application.customer, action_id=CfsActionId.CONNECT_BPJS
        )
        verification = CfsAssignmentVerification.objects.get(
            cfs_action_assignment=action_assignment
        )
        self.assertIsNotNone(verification)


class TestGetCfsReferralBonusByApplication(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.cfs_tier = CfsTierFactory(id=1, referral_bonus=2000)

    @patch(f'{PACKAGE_NAME}.get_customer_tier_info')
    def test_no_tier(self, mock_get_customer_tier_info):
        mock_get_customer_tier_info.return_value = None, None
        ret_val = core_services.get_cfs_referral_bonus_by_application(self.application)
        self.assertIsNone(ret_val)

    @patch(f'{PACKAGE_NAME}.get_customer_tier_info')
    def test_has_tier(self, mock_get_customer_tier_info):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        ret_val = core_services.get_cfs_referral_bonus_by_application(self.application)
        self.assertEquals(2000, ret_val)


class TestLockAssignmentVerification(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = AgentFactory()

    def test_success_lock(self):
        assignment_verification = CfsAssignmentVerificationFactory()

        is_locked = core_services.lock_assignment_verification(
            assignment_verification.id, self.agent.id)
        assignment_verification.refresh_from_db()

        self.assertTrue(is_locked)
        self.assertEqual(self.agent.id, assignment_verification.locked_by_id)

    def test_fail_lock_because_locked(self):
        other_agent = AgentFactory()
        assignment_verification = CfsAssignmentVerificationFactory(locked_by_id=other_agent.id)

        is_locked = core_services.lock_assignment_verification(
            assignment_verification.id, self.agent.id)
        assignment_verification.refresh_from_db()

        self.assertFalse(is_locked)
        self.assertEqual(other_agent.id, assignment_verification.locked_by_id)

    @patch(f'{PACKAGE_NAME}.CfsAssignmentVerification.objects.select_for_update')
    def test_fail_lock_because_db_locked(self, mock_select_for_update):
        assignment_verification = CfsAssignmentVerificationFactory()
        mock_select_for_update.side_effect = DatabaseError

        is_locked = core_services.lock_assignment_verification(
            assignment_verification.id, self.agent.id)
        assignment_verification.refresh_from_db()

        self.assertFalse(is_locked)


class TestUnlockAssignmentVerification(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = AgentFactory()

    def test_unlocked_assignment_verification(self):
        assignment_verification = CfsAssignmentVerificationFactory(locked_by_id=self.agent.id)

        core_services.unlock_assignment_verification(assignment_verification.id)
        assignment_verification.refresh_from_db()

        self.assertIsNone(assignment_verification.locked_by_id)


class TestGetLockedAssignmentVerifications(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = AgentFactory()

    def test_get_locked_assignment_verifications(self):
        assignment_verifications = CfsAssignmentVerificationFactory.create_batch(
            3,
            locked_by_id=self.agent.id
        )
        _other_verifications = CfsAssignmentVerificationFactory.create_batch(2)

        locked_assignment_verifications = core_services.get_locked_assignment_verifications(
            self.agent.id
        )

        expected_ids = [verification.id for verification in assignment_verifications].sort()
        actual_ids = [verification.id for verification in locked_assignment_verifications].sort()

        self.assertEqual(expected_ids, actual_ids)


class TestProcessPostConnectBank(TestCase):
    def setUp(self):
        self.cfs_tier = CfsTierFactory(id=1, point=0, cashback_multiplier=1.2)
        self.cfs_action = CfsActionFactory(id=CfsActionId.CONNECT_BANK)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)

        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.customer.id, pgood=0.9)

    def test_create_assignment(self):
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.AUTH_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)

        agent_assignment = CfsActionAssignment.objects.filter(customer=self.customer).last()
        self.assertIsNotNone(agent_assignment)
        self.assertEqual(CfsActionId.CONNECT_BANK, agent_assignment.action_id)
        self.assertEqual(CfsProgressStatus.PENDING, agent_assignment.progress_status)

    def test_agent_assignment_start(self):
        agent_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            progress_status=CfsProgressStatus.START)
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.AUTH_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        self.assertEqual(1, CfsActionAssignment.objects.filter(customer=self.customer).count())

    def test_agent_assignment_pending(self):
        agent_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            progress_status=CfsProgressStatus.PENDING)
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.AUTH_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)

    def test_invalid_etl_status(self):
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.AUTH_FAILED)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertFalse(ret_val)
        self.assertEqual(0, CfsActionAssignment.objects.filter(customer=self.customer).count())

    @patch(f'{PACKAGE_NAME}.create_cfs_assignment_verification')
    def test_has_assignment_verification_etl_load_success(self, mock_create_cfs_assignment_verification):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action, extra_data={},
            progress_status=CfsProgressStatus.PENDING)
        CfsAssignmentVerificationFactory(cfs_action_assignment=action_assignment, verify_status=None)
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.LOAD_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        mock_create_cfs_assignment_verification.assert_not_called()

    def test_agent_assignment_etl_load_success(self):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            extra_data={'bank_name': 'mandiri'}, progress_status=CfsProgressStatus.START)
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.LOAD_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        current_action_assignment = CfsActionAssignment.objects.filter(customer=self.customer).get()
        self.assertEqual(action_assignment.id, current_action_assignment.id)
        self.assertEqual(CfsProgressStatus.PENDING, current_action_assignment.progress_status)

        total_assignment_verification = CfsAssignmentVerification.objects.filter(
            cfs_action_assignment=current_action_assignment).count()
        self.assertEqual(1, total_assignment_verification)

    def test_agent_assignment_etl_load_failed(self):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            extra_data={'bank_name': 'mandiri'}, progress_status=CfsProgressStatus.START)
        etl_job = EtlJobFactory(
            data_type='mandiri', job_type=EtlJobType.CFS, status=EtlJob.LOAD_FAILED)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        current_action_assignment = CfsActionAssignment.objects.filter(customer=self.customer).get()
        self.assertEqual(action_assignment.id, current_action_assignment.id)
        self.assertEqual(CfsProgressStatus.START, current_action_assignment.progress_status)

    def test_agent_assignment_etl_load_failed_diff_bank_name(self):
        agent_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            extra_data={'bank_name': 'mandiri'}, progress_status=CfsProgressStatus.PENDING)
        etl_job = EtlJobFactory(
            data_type='bca', job_type=EtlJobType.CFS, status=EtlJob.LOAD_FAILED)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        current_action_assignment = CfsActionAssignment.objects.filter(customer=self.customer).get()
        self.assertEqual(agent_assignment.id, current_action_assignment.id)
        self.assertEqual(CfsProgressStatus.PENDING, current_action_assignment.progress_status)

        self.assertEqual(0, CfsAssignmentVerification.objects.filter(
            cfs_action_assignment=current_action_assignment).count())

    def test_agent_assignment_retry_auth_success(self):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            extra_data={'bank_name': 'mandiri', 'etl_job_id': -1}, progress_status=CfsProgressStatus.START)
        CfsAssignmentVerificationFactory(cfs_action_assignment=action_assignment,
                                         verify_status=VerifyStatus.REFUSE)
        etl_job = EtlJobFactory(
            data_type='bca', job_type=EtlJobType.CFS, status=EtlJob.AUTH_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        action_assignment.refresh_from_db()
        self.assertEqual(CfsProgressStatus.PENDING, action_assignment.progress_status)
        self.assertEqual(etl_job.id, action_assignment.extra_data.get('etl_job_id'))
        self.assertEqual('bca', action_assignment.extra_data.get('bank_name'))

    def test_agent_assignment_retry_load_success(self):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.cfs_action,
            extra_data={'bank_name': 'mandiri', 'etl_job_id': -1}, progress_status=CfsProgressStatus.START)
        CfsAssignmentVerificationFactory(cfs_action_assignment=action_assignment,
                                         verify_status=VerifyStatus.REFUSE)
        etl_job = EtlJobFactory(
            data_type='bca', job_type=EtlJobType.CFS, status=EtlJob.LOAD_SUCCESS)

        ret_val = process_post_connect_bank(self.application, etl_job)

        self.assertTrue(ret_val)
        action_assignment.refresh_from_db()
        self.assertEqual(CfsProgressStatus.PENDING, action_assignment.progress_status)
        self.assertEqual(etl_job.id, action_assignment.extra_data.get('etl_job_id'))
        self.assertEqual('bca', action_assignment.extra_data.get('bank_name'))

        total_assignment_verification = CfsAssignmentVerification.objects.filter(
            cfs_action_assignment=action_assignment).count()
        self.assertEqual(2, total_assignment_verification)
