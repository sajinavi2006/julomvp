from datetime import timedelta
from unittest.mock import MagicMock

import mock
import pytest
from django.test import TestCase
from django.utils import timezone

from juloserver.julo.models import FeatureSetting, VendorDataHistory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.grab.models import GrabCustomerData
from juloserver.grab.tests.factories import GrabLoanDataFactory, GrabCustomerDataFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tasks import update_payment_status_subtask
from juloserver.julo.tests.factories import (
    CustomerFactory,
    WorkflowFactory,
    ApplicationFactory,
    ProductLineFactory,
    ProductLookupFactory,
    PartnerFactory,
    StatusLookupFactory,
    LoanFactory,
    CommsBlockedFactory
)
from juloserver.julo.services2.voice import (
    mark_voice_account_payment_reminder_grab, send_voice_payment_reminder_grab,
    trigger_account_payment_reminder_grab
)
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.test.factories import StreamlinedCommunicationFactory


class TestGrabRobocall(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.mobile_phone = '6281245789184'
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            phone_number=self.mobile_phone,
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            token='906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71'
                  '054f915752a69d0220619dfsdc3fc1f27f7b4934a6a4b2baa2f85b6533c'
                  '663ca6d98f976328625f756e79a7cc543770b6945c1a5aaafd066ceed10'
                  '204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d8971764c12b9'
                  'fb912c7d1c3b1db1f931'
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            customer=self.customer, account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.partner = PartnerFactory(name="grab")
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.application_status_code = StatusLookupFactory(code=190)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        self.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6))
        )
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
        )
        payments = self.loan.payment_set.all()

        for idx, payment in enumerate(payments):
            payment.due_date = timezone.localtime(timezone.now()) + timedelta(
                days=idx - 3)
            update_payment_status_subtask(payment.id)
            payment.is_restructured = False
            payment.account_payment = AccountPaymentFactory(
                due_date=timezone.localtime(timezone.now()) + timedelta(days=idx + 3),
                account=self.account
            )
            payment.account_payment.is_restructured = True
            payment.save()

        self.streamlined_comms = StreamlinedCommunicationFactory(
            dpd=3,
            is_automated=True,
            template_code='nexmo_grab_med_dpd_6',
            product='nexmo_grab',
            communication_platform=CommunicationPlatform.ROBOCALL,
            is_active=True,
            type='Payment Reminder'
        )

        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key, decode):
        return self.redis_data[key]

    @mock.patch('juloserver.julo.services2.voice.connection')
    def test_success_mark_robocall_active(self, mock_connection):
        payments = self.loan.payment_set.all().order_by('due_date')
        oldest_payment = payments[0]
        mocked_cursor = mock.MagicMock()
        mocked_cursor.__enter__().execute.return_value = None
        mocked_cursor.__enter__().fetchall.return_value = [(self.loan, oldest_payment.id, 1)]
        mock_connection.cursor.return_value = mocked_cursor
        mark_voice_account_payment_reminder_grab([3])
        oldest_payment.refresh_from_db()
        self.assertTrue(oldest_payment.account_payment.is_robocall_active)

    @mock.patch('juloserver.julo.services2.voice.connection')
    def test_failed_mark_robocall_active(self, mock_connection):
        payments = self.loan.payment_set.all().order_by('due_date')
        oldest_payment = payments[0]
        mocked_cursor = mock.MagicMock()
        mocked_cursor.__enter__().execute.return_value = None
        mocked_cursor.__enter__().fetchall.return_value = [(self.loan, oldest_payment.id, 1)]
        mock_connection.cursor.return_value = mocked_cursor
        mark_voice_account_payment_reminder_grab([1])
        oldest_payment.refresh_from_db()
        self.assertFalse(oldest_payment.account_payment.is_robocall_active)

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.julo.services2.voice.get_voice_client_v2')
    @mock.patch('juloserver.julo.services2.voice.logger.info')
    @mock.patch('juloserver.julo.services2.voice.trigger_account_payment_reminder_grab.delay')
    @mock.patch('juloserver.grab.services.robocall_services.get_redis_client')
    @mock.patch('juloserver.grab.services.robocall_services.connection')
    def test_success_send_voice_payment_reminder_grab(self, mock_connection, mock_redis_client,
                                                      mock_trigger_account_payment_reminder_grab,
                                                      mocked_logger, mock_voice_client):
        mock_trigger_account_payment_reminder_grab = MagicMock()
        mock_voice_client = MagicMock()
        self.application.update_safely(address_kodepos=23000)
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
            is_active=True,
            parameters={}
        )
        mock_redis_client.return_value.set.side_effect = self.set_redis(
            key='payment_set_for_grab_robocall', val=None)
        mock_redis_client.return_value.get.side_effect = self.get_redis

        payments = self.loan.payment_set.all().order_by('due_date')
        oldest_payment = payments[0]
        account_payment = oldest_payment.account_payment
        account_payment.update_safely(is_robocall_active=True)
        mocked_cursor = mock.MagicMock()
        mocked_cursor.__enter__().execute.return_value = None
        mocked_cursor.__enter__().fetchall.return_value = [(self.loan, oldest_payment.id, 1)]
        mock_connection.cursor.return_value = mocked_cursor

        attempt = 2
        attempt_hour = timezone.localtime(timezone.now()).hour
        product_lines = ProductLineCodes.grab()
        streamlined_id = self.streamlined_comms.id

        send_voice_payment_reminder_grab(attempt, attempt_hour, product_lines, streamlined_id)
        mocked_logger.assert_called_with({
            'message': 'finish send_voice_account_payment_reminder',
            'total_account_payments': 1,
            'action': 'send_voice_account_payment_reminder',
            'hour': attempt_hour,
            'attempt': attempt,
            'attempt_hour': attempt_hour,
            'product_lines': product_lines,
            'streamlined_id': streamlined_id
        })

        trigger_account_payment_reminder_grab(oldest_payment.id, streamlined_id)
        reminder_history = VendorDataHistory.objects.last()
        self.assertEqual(reminder_history.customer, self.customer)
        self.assertEqual(reminder_history.account_payment, oldest_payment.account_payment)
        self.assertEqual(reminder_history.reminder_type, 'robocall')

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.julo.services2.voice.logger.exception')
    def test_failed_not_nexmo_grab(self, mocked_logger):
        new_streamlined_comms = StreamlinedCommunicationFactory(
            dpd=3,
            is_automated=True,
            template_code='nexmo_grab_med_dpd_6',
            product='not_nexmo_grab',
            communication_platform=CommunicationPlatform.ROBOCALL,
            is_active=True,
            type='Payment Reminder'
        )

        self.application.update_safely(address_kodepos=23000)
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
            is_active=True,
            parameters={}
        )

        attempt = 2
        attempt_hour = timezone.localtime(timezone.now()).hour
        product_lines = ProductLineCodes.grab()

        send_voice_payment_reminder_grab(attempt, attempt_hour, product_lines,
                                         new_streamlined_comms.id)
        mocked_logger.assert_called_with({
            'action': 'send_voice_payment_reminder_grab',
            'streamlined': new_streamlined_comms.id,
            'message': 'Product is not grab Product'
        })

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.julo.services2.voice.logger.info')
    @mock.patch('juloserver.julo.services2.voice.trigger_account_payment_reminder_grab.delay')
    @mock.patch('juloserver.grab.services.robocall_services.get_redis_client')
    @mock.patch('juloserver.grab.services.robocall_services.connection')
    def test_failed_robocall_feature_setting_not_active(self, mock_connection, mock_redis_client,
                                                        mock_trigger_account_payment_reminder_grab,
                                                        mocked_logger):
        mock_trigger_account_payment_reminder_grab = MagicMock()
        mock_voice_client = MagicMock()
        self.application.update_safely(address_kodepos=23000)
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
            is_active=False,
            parameters={}
        )
        mock_redis_client.return_value.set.side_effect = self.set_redis(
            key='payment_set_for_grab_robocall', val=None)
        mock_redis_client.return_value.get.side_effect = self.get_redis

        payments = self.loan.payment_set.all().order_by('due_date')
        oldest_payment = payments[0]
        account_payment = oldest_payment.account_payment
        account_payment.update_safely(is_robocall_active=True)
        mocked_cursor = mock.MagicMock()
        mocked_cursor.__enter__().execute.return_value = None
        mocked_cursor.__enter__().fetchall.return_value = [(self.loan, oldest_payment.id, 1)]
        mock_connection.cursor.return_value = mocked_cursor

        attempt = 2
        attempt_hour = timezone.localtime(timezone.now()).hour
        product_lines = ProductLineCodes.grab()
        streamlined_id = self.streamlined_comms.id

        send_voice_payment_reminder_grab(attempt, attempt_hour, product_lines, streamlined_id)
        mocked_logger.assert_called_with({
            'message': 'finish send_voice_account_payment_reminder',
            'total_account_payments': 0,
            'action': 'send_voice_account_payment_reminder',
            'hour': attempt_hour,
            'attempt': attempt,
            'attempt_hour': attempt_hour,
            'product_lines': product_lines,
            'streamlined_id': streamlined_id
        })

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.account_payment.services.pause_reminder.logger.info')
    @mock.patch('juloserver.julo.services2.voice.get_voice_client_v2')
    @mock.patch('juloserver.julo.services2.voice.logger.info')
    @mock.patch('juloserver.julo.services2.voice.trigger_account_payment_reminder_grab.delay')
    @mock.patch('juloserver.grab.services.robocall_services.get_redis_client')
    @mock.patch('juloserver.grab.services.robocall_services.connection')
    def test_failed_comm_blocked(self, mock_connection, mock_redis_client,
                                 mock_trigger_account_payment_reminder_grab, mocked_logger,
                                 mock_voice_client, mocked_logger_pause_reminder):
        mock_trigger_account_payment_reminder_grab = MagicMock()
        mock_voice_client = MagicMock()
        self.application.update_safely(address_kodepos=23000)
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
            is_active=True,
            parameters={}
        )
        mock_redis_client.return_value.set.side_effect = self.set_redis(
            key='payment_set_for_grab_robocall', val=None)
        mock_redis_client.return_value.get.side_effect = self.get_redis

        payments = self.loan.payment_set.all().order_by('due_date')
        oldest_payment = payments[0]
        account_payment = oldest_payment.account_payment
        account_payment.update_safely(is_robocall_active=True)

        comm_block = CommsBlockedFactory(account=account_payment.account,
                            is_email_blocked=True,
                            is_robocall_blocked=True,
                            impacted_payments=[account_payment.id])

        mocked_cursor = mock.MagicMock()
        mocked_cursor.__enter__().execute.return_value = None
        mocked_cursor.__enter__().fetchall.return_value = [(self.loan, oldest_payment.id, 1)]
        mock_connection.cursor.return_value = mocked_cursor

        attempt = 2
        attempt_hour = timezone.localtime(timezone.now()).hour
        product_lines = ProductLineCodes.grab()
        streamlined_id = self.streamlined_comms.id

        send_voice_payment_reminder_grab(attempt, attempt_hour, product_lines, streamlined_id)
        mocked_logger.assert_called_with({
            'message': 'finish send_voice_account_payment_reminder',
            'total_account_payments': 1,
            'action': 'send_voice_account_payment_reminder',
            'hour': attempt_hour,
            'attempt': attempt,
            'attempt_hour': attempt_hour,
            'product_lines': product_lines,
            'streamlined_id': streamlined_id
        })

        trigger_account_payment_reminder_grab(oldest_payment.id, streamlined_id)
        mocked_logger_pause_reminder.assert_called_with(
            'account_payment_id {} comms is blocked by comms_block_id {}'.format(account_payment.pk,
                                                                                 comm_block.pk))
