from unittest.mock import MagicMock

from mock import patch

from dateutil.relativedelta import relativedelta
from django.test.utils import override_settings
from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.email_delivery.services import (
    create_email_history_for_payment,
    get_payment_info_for_email_reminder,
    get_payment_info_for_email_reminder_for_unsent_moengage,
)
from juloserver.email_delivery.tasks import (
    send_email_and_track_history,
    send_email_is_5_days_unreachable,
    send_email_payment_reminder,
    trigger_all_email_payment_reminders,
    update_email_history_status,
)
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.models import (
    EmailHistory,
    StatusLookup,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tasks import send_automated_comms
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    EmailHistoryFactory,
    FeatureSettingFactory,
    LoanFactory,
    PaymentFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.streamlined_communication.constant import (
    CardProperty,
    CommunicationPlatform,
)
from juloserver.streamlined_communication.models import (
    StreamlinedCommunication,
    StreamlinedMessage,
)
from juloserver.streamlined_communication.test.factories import (
    InfoCardPropertyFactory,
    StreamlinedCommunicationFactory,
    StreamlinedMessageFactory,
)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestPublicInterface(TestCase):

    def test_send_email_with_email_history(self):
        loan = LoanFactory()
        payment_id = loan.payment_set.all().first().id
        email_history = create_email_history_for_payment(payment_id)

        subject = "My Subject"
        content = "My Email Body"
        email_to = "julia@example.com"
        template_code = "my_template"
        email_from = "test@example.com"
        send_email_and_track_history.delay(
            email_history.id,
            subject,
            content,
            email_to,
            email_from,
            template_code=template_code)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestPaymentReminders(TestCase):
    def setUp(self):
        self.message_email = StreamlinedMessage.objects.create(
            message_content="<html><body>dpd-1</body></html>"
        )
        streamlined_test_email = StreamlinedCommunication.objects.create(
            dpd=-1,
            communication_platform=CommunicationPlatform.EMAIL,
            message=self.message_email,
            product='mtl',
            subject='unit test email',
            template_code='email_unit_test_1')
        streamlined_test_email_ptp = StreamlinedCommunication.objects.create(
            ptp=-1,
            communication_platform=CommunicationPlatform.EMAIL,
            message=self.message_email,
            product='internal_product',
            subject='unit test email ptp',
            template_code='email_ptp_unit_test_1')
        streamlined_test_plus_5 = StreamlinedCommunication.objects.create(
            ptp=5,
            communication_platform=CommunicationPlatform.EMAIL,
            message=self.message_email,
            product='mtl',
            subject='unit test email plus 5',
            template_code='email_ptp_unit_test_plus5')
        self.streamlined_test_email_id = streamlined_test_email.id
        self.streamlined = streamlined_test_email
        self.streamlined_ptp = streamlined_test_email_ptp
        self.streamlined_test_plus_5 = streamlined_test_plus_5
        self.today = timezone.localtime(timezone.now()).date()
        loan = LoanFactory()
        self.payment = loan.payment_set.all().first()
        self.account_lookup = AccountLookupFactory(moengage_mapping_number=1,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE))
        self.account = AccountFactory(account_lookup=self.account_lookup)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=self.today)
        self.account_property = AccountPropertyFactory(
            account=self.account)
        ApplicationFactory(account=self.account)

    def test_trigger_all_email_payment_reminders(self):
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.mtl()
        self.payment.due_date = self.today + relativedelta(days=1)
        self.payment.ptp_date = None
        self.payment.save()
        trigger_all_email_payment_reminders.delay(self.streamlined_test_email_id)

    def test_trigger_all_email_payment_reminders_ptp(self):
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.mtl()
        self.payment.ptp_date = self.today + relativedelta(days=1)
        self.payment.due_date = None
        self.payment.save()
        trigger_all_email_payment_reminders.delay(self.streamlined_ptp.id)

    def test_get_payment_info_for_email_reminder(self):
        self.payment.loan.application.product_line.product_line_code = 10
        self.payment.save()
        email_content, email_to, email_from = get_payment_info_for_email_reminder(
            self.payment, self.streamlined
        )
        self.assertEquals("unit test email", email_content.subject)
        self.assertEquals("collections@julo.co.id", email_from.email)

        self.payment.due_date = self.today - relativedelta(days=5)
        self.payment.payment_status_id = 321
        self.payment.save()
        email_content, email_to, email_from = get_payment_info_for_email_reminder(
            self.payment, self.streamlined_test_plus_5
        )
        self.assertEquals("unit test email plus 5", email_content.subject)

    def test_get_payment_info_for_email_reminder_if_application_is_none(self):
        self.payment.loan.application.product_line.product_line_code = 10
        self.payment.loan.application.email = None
        self.payment.save()
        email_content, email_to, email_from = get_payment_info_for_email_reminder(
            self.payment, self.streamlined
        )
        self.assertEqual(email_to.email, self.payment.loan.application.customer.email)

    def test_send_email_payment_reminder(self):
        send_email_payment_reminder.delay(
            self.payment.id,
            self.streamlined.id
        )

    @patch('juloserver.julo.tasks.send_automated_comms.delay')
    def test_send_automated(self, mock_send_automated_comms: MagicMock):
        from datetime import datetime
        now = timezone.localtime(datetime.now())
        self.info_card = InfoCardPropertyFactory()
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        StreamlinedCommunicationFactory(
            message=streamlined_message,
            communication_platform=CommunicationPlatform.ROBOCALL,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_WAITING_SCORE,
            is_active=True,
            is_automated=True,
            show_in_web=True,
            partner=None,
            product='nexmo_mtl',
            call_hours='{%s:%s}' % ((now.hour), now.minute),
            function_name='{send_voice_payment_reminder,retry_send_voice_payment_reminder1,retry_send_voice_payment_reminder2}',
        )
        send_automated_comms.delay()

    def test_get_payment_info_for_email_reminder_for_unsent_moengage(self):
        application = self.account_payment.account.application_set.last()
        application.email = None
        application.save()
        (
            email_content,
            email_to,
            email_from,
        ) = get_payment_info_for_email_reminder_for_unsent_moengage(
            self.account_payment, self.streamlined
        )
        self.assertEqual(email_to.email, self.account_payment.account.customer.email)
        self.assertEqual(email_from.email, 'collections@julo.co.id')

    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.email_delivery.tasks.send_email_ptp_payment_reminder_j1.delay')
    def test_send_automated_comm_email_for_jturbo(
        self, mocked_send_email_ptp_payment_reminder_j1, mock_time
    ):
        mock_now = timezone.localtime(timezone.now())
        mock_now.replace(
            hour=15, minute=59, second=59, microsecond=0, tzinfo=None
        )
        self.streamlined_comm_turbo = StreamlinedCommunication.objects.create(
            dpd=-1,
            communication_platform=CommunicationPlatform.EMAIL,
            message=self.message_email,
            product='jturbo',
            subject='unit test email',
            template_code='jturbo_email_dpd_-1',
            is_automated=True,
            is_active=True,
            time_sent='21:00',
            ptp=-1,
        )
        self.account_lookup.update_safely(workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER))
        ApplicationFactory(account=self.account)
        application = self.account.application_set.last()
        application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.TURBO),
            application_status=StatusLookupFactory(status_code=191)
        )
        self.account_payment_turbo = AccountPaymentFactory(
            account=self.account,
            due_date=self.today)
        self.account_payment_turbo.update_safely(ptp_date=self.today + relativedelta(days=abs(-1)))
        send_automated_comms.delay()
        mocked_send_email_ptp_payment_reminder_j1.assert_called_once_with(
            self.account_payment_turbo,
            self.streamlined_comm_turbo
        )


@patch('juloserver.email_delivery.tasks.evaluate_email_reachability.delay', return_value=None)
@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestEmailDeliveryTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(
            loan=self.loan,
            payment_status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_180DPD)
        )
        self.email_history = EmailHistoryFactory(
            customer=self.customer,
            application=self.application,
            payment=self.payment
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.SENT_EMAIl_AND_TRACKING)

    @patch('juloserver.email_delivery.tasks.get_julo_email_client')
    def test_send_email_and_track_history(self, mock_julo_email_client, *args):
        mock_julo_email_client.return_value.send_email.return_value = (
        202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})
        old_email_status = self.email_history.status
        send_email_and_track_history.delay(
            self.email_history.id,
            "subject unit test",
            "<html><head></head><body>unit test</body></html>",
            "unittest@julofinance.com",
            "test@julofinance.com"
        )
        self.email_history.refresh_from_db()
        self.assertNotEqual(old_email_status, self.email_history.status)

    @patch('juloserver.email_delivery.tasks.get_julo_nemesys_client')
    def test_update_email_history_status(self, mock_get_julo_nemesys_client, *args):
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'testing',
            'timestamp': 123123123,
        }
        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertNotEqual(old_email_status, self.email_history.status)
        mock_get_julo_nemesys_client.return_value.update_email_delivery_status.return_value = True
        self.email_history.refresh_from_db()
        old_email_status = self.email_history.status
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'testing',
            'category': 'nemesys',
        }
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        assert old_email_status == self.email_history.status

    def test_send_email_is_5_days_unreachable(self, *args):
        """To test the email is sending to customer email , even if application email is None."""
        application = self.payment.loan.application
        application.email = None
        application.save()
        send_email_is_5_days_unreachable.delay(self.payment.id, False)
        email_history = EmailHistory.objects.filter(
            payment=self.payment,
            application=application,
            customer_id=application.customer_id).last()
        self.assertEqual(email_history.to_email, application.customer.email)


@patch('juloserver.email_delivery.tasks.get_julo_nemesys_client')
@patch('juloserver.email_delivery.tasks.evaluate_email_reachability.delay', return_value=None)
@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestUpdateEmailHistoryStatus(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(
            loan=self.loan,
            payment_status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_180DPD)
        )
        self.email_history = EmailHistoryFactory(
            customer=self.customer,
            application=self.application,
            payment=self.payment
        )

    def test_not_allow_email_status_regress(self, *args):
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'processed',
            'timestamp': 123123123,
        }

        # not change status from delivered to processed
        self.email_history.status = 'delivered'
        self.email_history.save()

        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals(old_email_status, self.email_history.status)

        # not change status from clicked to processed
        self.email_history.status = 'clicked'
        self.email_history.save()

        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals(old_email_status, self.email_history.status)

        # not change status from open to processed
        self.email_history.status = 'open'
        self.email_history.save()

        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals(old_email_status, self.email_history.status)

        # change status from delivered to open
        self.email_history.status = 'delivered'
        self.email_history.save()
        item.update({'event': 'open'})
        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('open', self.email_history.status)

        # change status from delivered to open using Capital letters
        self.email_history.status = 'delivered'
        self.email_history.save()
        item.update({'event': 'OPEN'})
        old_email_status = self.email_history.status
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('open', self.email_history.status)

    @patch('juloserver.email_delivery.tasks.logger')
    def test_unexpected_status(self, mock_logger, *args):
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'unknown_event',
            'timestamp': 123123123,
        }

        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('unknown', self.email_history.status)

        self.assertEquals(3, mock_logger.info.call_count)
        self.assertEquals(mock_logger.info.call_args_list[1][0], ({
            'action': 'update_email_history_status',
            'sg_message_id': item['sg_message_id'],
            'event': 'unknown_event',
            'message': 'Unexpected status detected.'
        },))

    def test_save_categorized_bounce_status_sendgrid(self, mock_evaluate_email, *args):
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'bounce',
            'reason': '500 unknown recipient',
            'timestamp': 123123123,
        }

        item.update({'type': 'bounce'})
        self.email_history.update_safely(status='')
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('hard_bounce', self.email_history.status)

        item.update({'type': 'blocked'})
        self.email_history.update_safely(status='')
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('soft_bounce', self.email_history.status)

        item.update({'type': 'random-type'})
        self.email_history.update_safely(status='')
        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('unknown_bounce', self.email_history.status)

        # self.assertEquals(3, mock_evaluate_email.call_count)

    @patch('juloserver.email_delivery.tasks.logger')
    def test_logs_reason_for_bounce(self, mock_logger, *args):
        item = {
            'sg_message_id': self.email_history.sg_message_id,
            'event': 'bounce',
            'type': 'blocked',
            'reason': '500 error',
            'timestamp': 123123123,
        }

        update_email_history_status.delay(item)
        self.email_history.refresh_from_db()
        self.assertEquals('soft_bounce', self.email_history.status)

        self.assertEquals(3, mock_logger.info.call_count)
        self.assertEquals(mock_logger.info.call_args_list[1][0], ({
            'action': 'update_email_history_status',
            'sg_message_id': item['sg_message_id'],
            'event': 'soft_bounce',
            'type': 'blocked',
            'reason': '500 error',
            'message': 'Logging SendGrid bounce reason.'
        },))
