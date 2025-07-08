from datetime import datetime, timedelta
from unittest.mock import patch

import mock
from django.test.testcases import TestCase, override_settings
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.julo.models import EmailHistory
from juloserver.julo.models import (StatusLookup)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tests.factories import (
    PaymentFactory,
    ApplicationFactory,
    LoanFactory,
    CustomerFactory,
    ApplicationJ1Factory,
    StatusLookupFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.moengage.exceptions import MoengageCallbackError
from juloserver.moengage.models import MoengageOsmSubscriber
from juloserver.moengage.services.use_cases import async_moengage_events_for_j1_account_status_change
from juloserver.moengage.tasks import (
    async_update_moengage_for_payment_status_change,
    async_update_moengage_for_loan_status_change,
    async_update_moengage_for_refinancing_request_status_change,
    async_update_moengage_for_payment_due_amount_change,
    trigger_update_moengage_for_scheduled_events,
    trigger_bulk_update_moengage_for_scheduled_loan_status_change_210,
    async_moengage_events_for_j1_loan_status_change,
    trigger_to_update_data_on_moengage,
    trigger_moengage_streams,
    parse_moengage_install_event,
    parse_moengage_email_event,
    parse_moengage_response_submitted_event,
    bulk_process_moengage_streams,
)
from juloserver.moengage.tests.factories import MoengageUploadFactory, MoengageOsmSubscriberFactory
from juloserver.streamlined_communication.models import InAppNotificationHistory


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestMoengageTasks(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.payment.due_date = datetime.now() - timedelta(days=2)
        self.payment.payment_status_id = 325
        self.payment.due_amount = 10000000
        self.payment.late_fee_amount = 50000
        self.payment.cashback_earned = 40000
        self.payment.save()
        self.loan_ref_req = LoanRefinancingRequestFactory(
            loan=self.loan,
            status='Expired',
            product_type='R4'
        )
        self.status_220 = StatusLookup.objects.get(status_code=220)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_update_moengage_for_loan_status_change(self, mocked_client):
        data = async_update_moengage_for_loan_status_change(self.loan.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_update_moengage_for_payment_status_change(self, mocked_client):
        data = async_update_moengage_for_payment_status_change(self.payment.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_update_moengage_for_payment_due_amount_change(self, mocked_client):
        data = async_update_moengage_for_payment_due_amount_change(self.payment.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_update_moengage_for_refinancing_request_status_change(self, mocked_client):
        data = async_update_moengage_for_refinancing_request_status_change(self.loan_ref_req.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_trigger_update_moengage_for_scheduled_events(self, mocked_client):
        data = trigger_update_moengage_for_scheduled_events()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_trigger_bulk_update_moengage_for_scheduled_loan_status_change_210(self, mocked_client):
        data = trigger_bulk_update_moengage_for_scheduled_loan_status_change_210()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_moengage_events_for_j1_loan_status_change(self, mocked_client):
        loan_j1 = LoanFactory(loan_status=self.status_220)
        data = async_moengage_events_for_j1_loan_status_change(loan_j1.id, self.status_220)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.tasks.send_user_attributes_to_moengage_in_bulk_daily')
    def test_trigger_to_update_data_on_moengage(self, mock1):
        account_limit = AccountLimitFactory()
        customer = account_limit.account.customer
        MoengageUploadFactory(customer_id=customer.id)
        trigger_to_update_data_on_moengage()
        mock1.delay.assert_called()

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_async_moengage_events_for_j1_account_status_change(self, mocked_client):
        loan_j1 = LoanFactory(loan_status=self.status_220)

        data = async_moengage_events_for_j1_account_status_change(loan_j1.id, 420)
        self.assertIsNone(data)


class TestTriggerMoengageStreams(TestCase):
    def test_event_code_for_inapp(self):
        customer = CustomerFactory()
        application = ApplicationJ1Factory(customer=customer)
        event = {
            'device_attributes': {
                'moengage_device_id': ''
            },
            'event_attributes': {
                'Campaign ID': '607e8a48cb07c021db1785ce',
                'campaign_name': 'test',
                'OS Version': '30',
                'Publisher Name': 'Organic',
                'Push ID': 'dmpYvzJ4SI123',
                'Push Service Name': 'FCM',
            },
            'event_code': 'MOE_IN_APP_SHOWN',
            'event_name': 'Event Name',
            'event_source': 'MOENGAGE',
            'event_time': 1655868583,
            'event_type': 'USER_ACTION_EVENT',
            'event_uuid': '5755311c-21f-487a-8dbe-520e79ac42ad',
            'uid': str(customer.id),
            'user_attributes': {
                'application_id': str(application.id),
                'email': 'email@email.com',
                'moengage_user_id': '6061ae584b8f7808038ee40b',
            }
        }
        trigger_moengage_streams(event)
        count = InAppNotificationHistory.objects.filter(customer_id=customer.id).count()
        self.assertEqual(1, count)

    def test_event_code_install(self):
        @patch('juloserver.moengage.tasks.logger')
        def execute_subtest(mock_logger, event_code):
            event = {
                'device_attributes': {
                    'moengage_device_id': ''
                },
                'event_attributes': {
                    'Campaign ID': '607e8a48cb07c021db1785ce',
                    'OS Version': '30',
                    'Publisher Name': 'Organic',
                    'Push ID': 'dmpYvzJ4SI123',
                    'Push Service Name': 'FCM',
                },
                'event_code': event_code,
                'event_name': 'Event Name',
                'event_source': 'MOENGAGE',
                'event_time': 1655868583,
                'event_type': 'USER_ACTION_EVENT',
                'event_uuid': '5755311c-21f-487a-8dbe-520e79ac42ad',
                'uid': '100081231',
                'user_attributes': {
                    'account1_payment_id': 24712342,
                    'application_id': 200123182,
                    'email': 'email@email.com',
                    'moengage_user_id': '6061ae584b8f7808038ee40b',
                }
            }
            parse_moengage_install_event(event)
            mock_logger.info.assert_called_once_with(
                {
                    'message': 'parse_moengage_install_event Event code {}'.format(event_code),
                    'action': 'parse_moengage_install_event',
                    'module': 'moengage',
                    'event_code': event_code,
                    'event': event,
                }
            )

        for event_code in ['INSTALL', 'Device Uninstall']:
            execute_subtest(event_code=event_code)

    def test_moengage_email_events(self):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(customer=customer, account=account)
        account_payment = AccountPaymentFactory(account=account)
        loan = LoanFactory(application=application)
        payment = PaymentFactory(loan=loan, account_payment=account_payment)

        def execute_subtest(event_code):
            event = {
                "event_name": "Email Dropped",
                "event_code": event_code,
                "event_uuid": "889f95a4-9235-4308-b327-7bee588662d6",
                "event_time": 1656895863,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": str(application.customer.id),
                "email_id": "test@julofinance.com",
                "event_attributes": {
                    "campaign_id": "62fca47bec946d1a0c865182",
                    "campaign_name": "Email_UnitTestenv",
                    "campaign_type": "One Time",
                    "campaign_channel": "EMAIL",
                    "moe_delivery_type": "One Time",
                    "moe_campaign_tags": [
                        "application"
                    ],
                    "moe_campaign_channel": "Email",
                    "email_subject": "This is testing",
                    "reason": "UT reason",  # Only used for bounce status
                },
                "user_attributes": {
                    "account1_payment_id": account_payment.id,
                    "loan_status_code": 220,
                    "payment_id": payment.id,
                    "moengage_user_id": "62ce489233655aa761625e41",
                    "mobile_phone_1": "628129222084",
                    "application_id": application.id,
                    "email": "test@julofinance.com"
                },
                "device_attributes": {}
            }
            parse_moengage_email_event(event)
            email_history = EmailHistory.objects.filter(
                customer_id=application.customer.id,
                subject=event['event_attributes']['email_subject'])
            self.assertTrue(email_history)

        for event_code in EmailStatusMapping['MoEngageStream'].keys():
            execute_subtest(event_code=event_code)


@mock.patch('juloserver.moengage.services.use_cases.construct_application_status_change_event_data_for_j1_customer')
class TestSendApplicationStatusEventToME(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dummy_event_attributes = {
            "type": "event",
            "customer_id": 123,
            "device_id": 'device-id',
            "actions": [{
                "action": 'BEx115',
                "attributes": {},
                "platform": "ANDROID",
                "current_time": 12345,
                "user_timezone_offset": -100
            }]
        }

    def test_x115_status(self, mock_construct_event_data):
        StatusLookupFactory(status_code=115)
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=121)
        )
        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=115,
            workflow=application.workflow,
            is_active=True,
        )
        mock_construct_event_data.return_value = self.dummy_event_attributes

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 10, 8, 9, 10)
            process_application_status_change(application.id, 115, 'manual change')

        expected_event_attributes = {
            "customer_id": application.customer_id,
            "partner_name": '',
            "application_id": application.id,
            "cdate": "2023-01-10 01:09:10",
            "event_triggered_date": "2023-01-10 08:09:10",
            "product_type": "J1",
        }
        mock_construct_event_data.assert_called_once_with(
            'BEx115',
            application.id,
            expected_event_attributes,
        )


@patch('juloserver.moengage.tasks.logger')
class TestParseMoengageResponsResponseSubmittedEvent(TestCase):
    def setUp(self):
        self.test_data = {
            'event_code': 'MOE_RESPONSE_SUBMITTED',
            'event_attributes': {
                'appVersion': '1.0',
                'moe_first_visit': True,
                'moe_logged_in_status': False,
                'sdkVersion': '2.19.14',
                'URL': 'https://www.julo.co.id/',
                'USER_ATTRIBUTE_USER_EMAIL': 'edward@test.com',
                'USER_ATTRIBUTE_USER_FIRST_NAME': 'Edward',
                'USER_ATTRIBUTE_USER_MOBILE': '082167912345'
            },
            'user_attributes': {
                'moengage_user_id': 'test-user-id-moengage',
            }
        }

    def test_with_new_valid_data(self, *args):
        parse_moengage_response_submitted_event(self.test_data)
        moengage_onsite_messaging_user = MoengageOsmSubscriber.objects.last()

        self.assertEqual(moengage_onsite_messaging_user.moengage_user_id, 'test-user-id-moengage')
        self.assertEqual(moengage_onsite_messaging_user.first_name, 'Edward')
        self.assertEqual(moengage_onsite_messaging_user.phone_number, '082167912345')
        self.assertEqual(moengage_onsite_messaging_user.email, 'edward@test.com')

    def test_with_user_already_exist(self, mock_logger):
        MoengageOsmSubscriberFactory(phone_number='082167912345', email='edward@test.com')
        parse_moengage_response_submitted_event(self.test_data)
        moengage_onsite_messaging_user = MoengageOsmSubscriber.objects.last()

        mock_logger.info.assert_called_once_with({
            'action': 'parse_moengage_response_submitted_event',
            'message': 'Email and phone number existed.',
            'event_attributes': self.test_data['event_attributes'],
            'user_attributes': self.test_data['user_attributes'],
        })

        self.assertEqual(moengage_onsite_messaging_user.moengage_user_id, 'abc123')
        self.assertEqual(moengage_onsite_messaging_user.first_name, 'Julo Prod')
        self.assertEqual(moengage_onsite_messaging_user.phone_number, '082167912345')
        self.assertEqual(moengage_onsite_messaging_user.email, 'edward@test.com')


@patch('juloserver.moengage.tasks.logger')
@patch('juloserver.moengage.tasks.preprocess_moengage_stream')
@patch('juloserver.moengage.tasks.trigger_moengage_streams')
class TestBulkProcessMoengageStreams(TestCase):
    def setUp(self):
        self.dummy_data = [
            {
                "event_name": "Email Sent",
                "event_code": "MOE_EMAIL_OPEN",
                "event_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "event_time": 1697438685,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "1000104583",
                "email_id": "test@julofinance.com",
                "event_attributes": {
                    "campaign_id": "UQJdnkqYT5qD6jKrlJjV6w",
                    "campaign_name": "test_campaign",
                    "campaign_type": "GENERAL",
                    "campaign_channel": "EMAIL",
                    "moe_campaign_tags": ["manual_refinancing"],
                    "moe_campaign_channel": "Email",
                    "moe_delivery_type": "One Time",
                    "email_subject": "Test Campaign",
                },
                "user_attributes": {},
                "device_attributes": {},
            }
        ]

    def test_success_process(self, mock_trigger_moengage_streams, mock_preprocess, mock_logger):
        mock_preprocess.return_value = self.dummy_data

        bulk_process_moengage_streams(self.dummy_data)
        mock_trigger_moengage_streams.assert_called_once_with(self.dummy_data[0])
        mock_logger.assert_not_called()

    def test_moengage_callback_error_raised(
        self, mock_trigger_moengage_streams, mock_preprocess, mock_logger
    ):
        self.dummy_data[0]['event_code'] = 'MOE_UNRECOGNIZED'
        self.dummy_data.append(
            {
                "event_name": "Email Sent",
                "event_code": "MOE_EMAIL_OPEN",
                "event_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "event_time": 1697438685,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "1000104583",
                "email_id": "test@julofinance.com",
                "event_attributes": {},
                "user_attributes": {},
                "device_attributes": {},
            }
        )
        mock_trigger_moengage_streams.side_effect = [MoengageCallbackError('unit test error'), None]
        mock_preprocess.return_value = self.dummy_data

        bulk_process_moengage_streams(self.dummy_data)
        self.assertEqual(mock_trigger_moengage_streams.call_count, 2)
        mock_logger.info.assert_called_once_with(
            {
                'action': 'bulk_process_moengage_streams',
                'data': self.dummy_data[0],
                'error': 'unit test error',
                'message': 'Unexpected event code.',
            }
        )

    def test_unknown_exception_raised(
        self, mock_trigger_moengage_streams, mock_preprocess, mock_logger
    ):
        self.dummy_data[0]['event_code'] = 'MOE_UNRECOGNIZED'
        self.dummy_data.append(
            {
                "event_name": "Email Sent",
                "event_code": "MOE_EMAIL_OPEN",
                "event_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "event_time": 1697438685,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "1000104583",
                "email_id": "test@julofinance.com",
                "event_attributes": {},
                "user_attributes": {},
                "device_attributes": {},
            }
        )

        mock_trigger_moengage_streams.side_effect = [Exception('unit test error'), None]
        mock_preprocess.return_value = self.dummy_data

        bulk_process_moengage_streams(self.dummy_data)
        self.assertEqual(mock_trigger_moengage_streams.call_count, 2)
        mock_logger.info.assert_called_once_with(
            {
                'action': 'bulk_process_moengage_streams',
                'data': self.dummy_data[0],
                'error': 'unit test error',
                'message': 'An unknown error occurred.',
            }
        )
