from datetime import time
from unittest import mock

from celery.exceptions import Retry
from django.test import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.constants import (
    ReminderTypeConst,
    VendorConst,
    VoiceTypeStatus,
)
from juloserver.julo.models import (
    VendorDataHistory,
    VoiceCallRecord,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CommsProviderLookupFactory,
    CustomerFactory,
    ProductLineFactory,
    VoiceCallRecordFactory,
)
from juloserver.nexmo.constants import NexmoVoiceRateLimit
from juloserver.nexmo.models import (
    NexmoCustomerData,
    NexmoSendConfig,
)
from juloserver.nexmo.tasks import (
    process_call_customer_via_nexmo,
    send_payment_reminder_nexmo_robocall,
    trigger_bulk_send_nexmo_robocall,
)
from juloserver.ratelimit.constants import RateLimitTimeUnit


@mock.patch("juloserver.nexmo.tasks.get_voice_client_v2")
@mock.patch("juloserver.nexmo.tasks.sliding_window_rate_limit")
@mock.patch("juloserver.nexmo.tasks.get_redis_client")
class TestSendPaymentReminderNexmoRobocall(TestCase):
    def setUp(self):
        self.comm_provider = CommsProviderLookupFactory(provider_name="Nexmo")
        self.customer = CustomerFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            gender="Pria",
        )
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.customer.current_application_id = self.application.id
        self.customer.save()

        self.account_payment = AccountPaymentFactory(
            account=AccountFactory(customer=self.customer),
            is_success_robocall=False,
            is_collection_called=False,
        )

        self.default_content = [
            {
                "action": "talk",
                "text": "Hello",
            }
        ]
        self.customer_data = NexmoCustomerData(
            customer_id=self.customer.id,
            account_payment_id=self.account_payment.id,
            phone_number="08123456789",
        )
        self.success_call_response = {
            "uuid": "123",
            "status": "started",
            "direction": "outbound",
            "conversation_uuid": "456",
        }

    def test_success_send(self, mock_redis_client, mock_rate_limit, mock_get_voice_client):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False
        mock_client = mock_get_voice_client.return_value
        mock_client.create_call.return_value = self.success_call_response

        self.account_payment.update_safely(
            is_success_robocall=True,
            is_collection_called=True,
        )
        now = timezone.now()
        now = now.replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            ret_val = send_payment_reminder_nexmo_robocall(
                template_code="template",
                customer_data=self.customer_data,
                content=self.default_content,
                send_config=NexmoSendConfig(trigger_time=timezone.now()),
            )
        self.assertIsNotNone(ret_val)

        # Validate VoiceCallRecord
        last_voice_call = VoiceCallRecord.objects.last()
        total_created_call = VoiceCallRecord.objects.filter(template_code='template').count()
        self.assertEqual(1, total_created_call)
        self.assertEqual(last_voice_call.account_payment_id, self.account_payment.id)
        self.assertEqual(last_voice_call.application_id, self.application.id)
        self.assertEqual(last_voice_call.status, "started")
        self.assertEqual(last_voice_call.uuid, "123")
        self.assertEqual(last_voice_call.conversation_uuid, "456")
        self.assertEqual(last_voice_call.direction, "outbound")
        self.assertEqual(last_voice_call.event_type, VoiceTypeStatus.PAYMENT_REMINDER)
        self.assertEqual(last_voice_call.account_payment_id, self.account_payment.id)
        self.assertIsNotNone(last_voice_call.voice_style_id)

        # Validate CommsDataHistory
        data_history = VendorDataHistory.objects.last()
        self.assertEqual(data_history.account_payment_id, self.account_payment.id)
        self.assertEqual(data_history.customer_id, self.customer.id)
        self.assertEqual(data_history.template_code, "template")
        self.assertEqual(data_history.vendor, VendorConst.NEXMO)
        self.assertEqual(data_history.reminder_type, ReminderTypeConst.ROBOCALL_TYPE_REMINDER)

    def test_success_retry_send(self, mock_redis_client, mock_rate_limit, mock_get_voice_client):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False
        mock_client = mock_get_voice_client.return_value
        mock_client.create_call.return_value = self.success_call_response

        now = timezone.now()
        now = now.replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - timezone.timedelta(minutes=10)
            VoiceCallRecordFactory(
                template_code="template",
                conversation_uuid="456",
                account_payment_id=self.account_payment.id,
            )

            ret_val = send_payment_reminder_nexmo_robocall(
                template_code="template",
                customer_data=self.customer_data,
                content=self.default_content,
                send_config=NexmoSendConfig(trigger_time=now, max_retry=1, min_retry_interval=0),
            )
            self.assertIsNotNone(ret_val)

        # Validate VoiceCallRecord
        total_created_call = VoiceCallRecord.objects.filter(template_code='template').count()
        self.assertEqual(2, total_created_call)

    def test_circuit_breaker_on(self, mock_redis_client, *args):
        mock_redis_client.return_value.get.return_value = 1
        now = timezone.now()
        now = now.replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            with self.assertRaises(Retry):
                send_payment_reminder_nexmo_robocall(
                    template_code="template",
                    customer_data=self.customer_data,
                    content=self.default_content,
                    send_config=NexmoSendConfig(trigger_time=timezone.now()),
                )
        mock_redis_client.return_value.get.assert_called_once_with(
            "nexmo:nexmo_voice_rate_limit_payment_reminder",
        )

    def test_customer_id_not_found(self, mock_redis_client, mock_rate_limit, *args):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False

        self.customer_data.customer_id = "not_found"
        now = timezone.now()
        now = now.replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            with self.assertRaises(ValueError):
                ret_val = send_payment_reminder_nexmo_robocall(
                    template_code="template",
                    customer_data=self.customer_data,
                    content=self.default_content,
                    send_config=NexmoSendConfig(trigger_time=timezone.now()),
                )
                self.assertIsNone(ret_val)

    def test_rate_limit_true(self, mock_redis_client, mock_rate_limit, *args):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = True

        now = timezone.now()
        now = now.replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            with self.assertRaises(Retry):
                ret_val = send_payment_reminder_nexmo_robocall(
                    template_code="template",
                    customer_data=self.customer_data,
                    content=self.default_content,
                    send_config=NexmoSendConfig(trigger_time=timezone.now()),
                )
                self.assertIsNone(ret_val)
            mock_rate_limit.assert_called_once_with(
                NexmoVoiceRateLimit.PAYMENT_REMINDER_REDIS_KEY,
                NexmoVoiceRateLimit.PAYMENT_REMINDER,
                RateLimitTimeUnit.Seconds,
            )
            mock_redis_client.return_value.set.assert_called_once_with(
                'nexmo:nexmo_voice_rate_limit_payment_reminder',
                1,
                ex=1,
            )

    def test_retry_successful_called(self, mock_redis_client, mock_rate_limit, *args):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False

        now = timezone.now()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - timezone.timedelta(minutes=10)
            VoiceCallRecordFactory(
                template_code="template",
                conversation_uuid="456",
                account_payment_id=self.account_payment.id,
            )

        self.account_payment.update_safely(
            is_success_robocall=True,
        )
        ret_val = send_payment_reminder_nexmo_robocall(
            template_code="template",
            customer_data=self.customer_data,
            content=self.default_content,
            send_config=NexmoSendConfig(trigger_time=now, max_retry=1, min_retry_interval=0),
        )
        self.assertIsNone(ret_val)

    def test_retry_successful_answered(self, mock_redis_client, *args):
        mock_redis_client.return_value.get.return_value = None

        now = timezone.now()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - timezone.timedelta(minutes=10)
            VoiceCallRecordFactory(
                template_code="template",
                conversation_uuid="456",
                account_payment_id=self.account_payment.id,
            )

        self.account_payment.update_safely(
            is_collection_called=True,
        )
        ret_val = send_payment_reminder_nexmo_robocall(
            template_code="template",
            customer_data=self.customer_data,
            content=self.default_content,
            send_config=NexmoSendConfig(trigger_time=now, max_retry=1, min_retry_interval=0),
        )
        self.assertIsNone(ret_val)

    def test_has_no_retry(self, mock_redis_client, mock_rate_limit, mock_get_voice_client, *args):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False
        mock_client = mock_get_voice_client.return_value
        mock_client.create_call.return_value = self.success_call_response

        now = timezone.now()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - timezone.timedelta(minutes=10)
            VoiceCallRecordFactory(
                template_code="template",
                conversation_uuid="456",
                account_payment_id=self.account_payment.id,
            )
            ret_val = send_payment_reminder_nexmo_robocall(
                template_code="template",
                customer_data=self.customer_data,
                content=self.default_content,
                send_config=NexmoSendConfig(trigger_time=now, max_retry=0, min_retry_interval=0),
            )
            self.assertIsNone(ret_val)

    def test_retry_not_allowed(self, mock_redis_client, *args):
        mock_redis_client.return_value.get.return_value = None

        now = timezone.now()
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - timezone.timedelta(minutes=10)
            VoiceCallRecordFactory(
                template_code="template",
                conversation_uuid="456",
                account_payment_id=self.account_payment.id,
            )

        ret_val = send_payment_reminder_nexmo_robocall(
            template_code="template",
            customer_data=self.customer_data,
            content=self.default_content,
            send_config=NexmoSendConfig(trigger_time=now, max_retry=1, min_retry_interval=20),
        )
        self.assertIsNone(ret_val)

    def test_zero_due_amount(self, mock_redis_client, mock_rate_limit, mock_get_voice_client):
        mock_redis_client.return_value.get.return_value = None
        mock_rate_limit.return_value = False
        mock_client = mock_get_voice_client.return_value
        mock_client.create_call.return_value = self.success_call_response

        self.account_payment.update_safely(due_amount=0)
        ret_val = send_payment_reminder_nexmo_robocall(
            template_code="template",
            customer_data=self.customer_data,
            content=self.default_content,
            send_config=NexmoSendConfig(trigger_time=timezone.now()),
        )
        self.assertIsNone(ret_val)


@mock.patch('juloserver.nexmo.tasks.send_payment_reminder_nexmo_robocall')
class TestTriggerBulkSendNexmoRobocall(TestCase):
    def setUp(self):
        self.default_nexmo_config = NexmoSendConfig(trigger_time=timezone.now())
        self.payloads = [
            {
                "customer_id": "1",
                "phone_number": "08123456789",
                "account_payment_id": "100",
                "content": [
                    {
                        "action": "talk",
                        "text": "Hello",
                    }
                ],
            },
            {
                "customer_id": "2",
                "phone_number": "081234567891",
                "account_payment_id": "101",
                "content": [
                    {
                        "action": "talk",
                        "text": "Hello 2",
                    }
                ],
            },
        ]

    def test_success(self, mock_send_robocall):
        ret_val = trigger_bulk_send_nexmo_robocall(
            template_code="template",
            payloads=self.payloads,
            send_config=self.default_nexmo_config,
        )
        self.assertIsNone(ret_val)
        mock_send_robocall.delay.has_calls(
            [
                mock.call(
                    "template",
                    NexmoCustomerData(
                        customer_id="1",
                        phone_number="08123456789",
                        account_payment_id="100",
                    ),
                    [
                        {
                            "action": "talk",
                            "text": "Hello",
                        }
                    ],
                    self.default_nexmo_config,
                ),
                mock.call(
                    "template",
                    NexmoCustomerData(
                        customer_id="2",
                        phone_number="081234567891",
                        account_payment_id="101",
                    ),
                    [
                        {
                            "action": "talk",
                            "text": "Hello",
                        }
                    ],
                    self.default_nexmo_config,
                ),
            ]
        )

    def test_invalid_content(self, mock_send_robocall):
        self.payloads[0]["content"] = None
        ret_val = trigger_bulk_send_nexmo_robocall(
            template_code="template",
            payloads=self.payloads,
            send_config=self.default_nexmo_config,
        )
        self.assertIsNone(ret_val)
        mock_send_robocall.delay.has_calls(
            [
                mock.call(
                    "template",
                    NexmoCustomerData(
                        customer_id="2",
                        phone_number="081234567891",
                        account_payment_id="101",
                    ),
                    [
                        {
                            "action": "talk",
                            "text": "Hello",
                        }
                    ],
                    self.default_nexmo_config,
                ),
            ]
        )

    def test_invalid_customer(self, mock_send_robocall):
        self.payloads[0]["account_payment_id"] = None
        ret_val = trigger_bulk_send_nexmo_robocall(
            template_code="template",
            payloads=self.payloads,
            send_config=self.default_nexmo_config,
        )
        self.assertIsNone(ret_val)
        mock_send_robocall.delay.has_calls(
            [
                mock.call(
                    "template",
                    NexmoCustomerData(
                        customer_id="2",
                        phone_number="081234567891",
                        account_payment_id="101",
                    ),
                    [
                        {
                            "action": "talk",
                            "text": "Hello",
                        }
                    ],
                    self.default_nexmo_config,
                ),
            ]
        )


@mock.patch('juloserver.nexmo.tasks.trigger_bulk_send_nexmo_robocall')
class TestProcessCallCustomerViaNexmo(TestCase):
    def setUp(self):
        self.campaign_data = {
            "campaign_id": "123",
            "campaign_name": "campaign",
        }
        self.retries = [time(hour=10, minute=12), time(hour=12, minute=42)]
        self.payloads = [
            {
                "customer_id": "1",
                "phone_number": "08123456789",
                "account_payment_id": "100",
                "content": [
                    {
                        "action": "talk",
                        "text": "Hello",
                    }
                ],
            },
        ]

    def test_success(self, mock_trigger_robocall):
        now = timezone.localtime(timezone.now())
        now = now.replace(hour=8, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            ret_val = process_call_customer_via_nexmo(
                trigger_time=now,
                source="testing",
                request_data={
                    "campaign_data": self.campaign_data,
                    "retries": self.retries,
                    "min_retry_delay_in_minutes": 90,
                    "payload": self.payloads,
                },
            )
            expected_template_code = "testing|123|campaign"
            self.assertEqual(ret_val, expected_template_code)
            mock_trigger_robocall.delay.assert_called_once_with(
                expected_template_code,
                self.payloads,
                NexmoSendConfig(trigger_time=now, max_retry=2, min_retry_interval=90),
            )

            expected_retry_times = [
                now.replace(hour=10, minute=12),
                now.replace(hour=12, minute=42),
            ]
            self.assertEqual(2, mock_trigger_robocall.apply_async.call_count)
            mock_trigger_robocall.apply_async.has_calls(
                [
                    mock.call(
                        (
                            expected_template_code,
                            self.payloads,
                            NexmoSendConfig(
                                trigger_time=expected_retry_time,
                                max_retry=len(expected_retry_times),
                                min_retry_interval=90,
                            ),
                        ),
                        eta=expected_retry_time,
                    )
                    for expected_retry_time in expected_retry_times
                ]
            )

    def test_invalid_retry_time_format(self, mock_trigger_robocall):
        now = timezone.localtime(timezone.now())
        now = now.replace(hour=8, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now.replace()
            ret_val = process_call_customer_via_nexmo(
                trigger_time=now,
                source="testing",
                request_data={
                    "campaign_data": self.campaign_data,
                    "retries": ["invalid_time", time(hour=12, minute=42)],
                    "min_retry_delay_in_minutes": 90,
                    "payload": self.payloads,
                },
            )
            expected_template_code = "testing|123|campaign"
            self.assertEqual(ret_val, expected_template_code)

            expected_retry_times = [
                now.replace(hour=12, minute=42),
            ]
            self.assertEqual(1, mock_trigger_robocall.apply_async.call_count)
            mock_trigger_robocall.apply_async.has_calls(
                [
                    mock.call(
                        (
                            expected_template_code,
                            self.payloads,
                            NexmoSendConfig(
                                trigger_time=expected_retry_time,
                                max_retry=len(expected_retry_times),
                                min_retry_interval=90,
                            ),
                        ),
                        eta=expected_retry_time,
                    )
                    for expected_retry_time in expected_retry_times
                ]
            )

    def test_retry_pass_time(self, mock_trigger_robocall):
        now = timezone.localtime(timezone.now())
        now = now.replace(hour=8, minute=0, second=0, microsecond=0)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            ret_val = process_call_customer_via_nexmo(
                trigger_time=now,
                source="testing",
                request_data={
                    "campaign_data": self.campaign_data,
                    "retries": [time(hour=7), time(hour=12, minute=42)],
                    "min_retry_delay_in_minutes": 90,
                    "payload": self.payloads,
                },
            )
            expected_template_code = "testing|123|campaign"
            self.assertEqual(ret_val, expected_template_code)

            expected_retry_times = [
                now.replace(hour=12, minute=42),
            ]
            self.assertEqual(1, mock_trigger_robocall.apply_async.call_count)
            mock_trigger_robocall.apply_async.has_calls(
                [
                    mock.call(
                        (
                            expected_template_code,
                            self.payloads,
                            NexmoSendConfig(
                                trigger_time=expected_retry_time,
                                max_retry=len(expected_retry_times),
                                min_retry_interval=90,
                            ),
                        ),
                        eta=expected_retry_time,
                    )
                    for expected_retry_time in expected_retry_times
                ]
            )
