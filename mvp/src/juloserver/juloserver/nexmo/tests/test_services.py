from datetime import timedelta

import mock
from django.test import TestCase
from django.utils import timezone

from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.nexmo.services import (
    NexmoVoiceContentSanitizer,
    choose_phone_number,
    nexmo_product_type,
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ExperimentSettingFactory,
    VoiceCallRecordFactory,
)
from juloserver.julo.constants import ExperimentConst
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.streamlined_communication.constant import NexmoVoice


# Create your tests here.
class TestChoosePhoneNumber(TestCase):
    def setUp(self) -> None:
        pass

    def test_feature_is_off(self):
        self.assertIsNone(choose_phone_number(1111111))

    def test_feature_is_expired(self):
        now = timezone.localtime(timezone.now())
        ExperimentSettingFactory(
            code=ExperimentConst.NEXMO_NUMBER_RANDOMIZER,
            name="Nexmo Number Randomizer Experiment",
            schedule="",
            action="",
            start_date=now - timedelta(days=5),
            end_date=now + timedelta(days=4),
            type="collection",
            criteria={
                'phone_numbers': [],
                'test_numbers': [5, 6, 7, 8, 9]
            })

        self.assertIsNone(choose_phone_number(1111111))

    def test_change_phone_number(self):
        now = timezone.localtime(timezone.now())
        ExperimentSettingFactory(
            code=ExperimentConst.NEXMO_NUMBER_RANDOMIZER,
            name="Nexmo Number Randomizer Experiment",
            schedule="",
            action="",
            start_date=now - timedelta(days=5),
            end_date=now+timedelta(days=5),
            type="collection",
            criteria={
                'phone_numbers': ['099999999999', '0622222222222'],
                'test_numbers': [5, 6, 7, 8, 9]
            })
        account_payment = AccountPaymentFactory()
        account_payment.account.id = 111119
        account_payment.account.save()
        voice_call_record = VoiceCallRecordFactory()
        voice_call_record.update_safely(
            account_payment = account_payment,
            call_from='099999999999',
        )

        phone_number = choose_phone_number(account_payment.account)
        self.assertEqual(phone_number, '0622222222222')


class TestNexmoProductType(TestCase):
    def test_valid_product(self):
        ret_val = nexmo_product_type(ProductLineCodes.J1)
        self.assertEqual(ret_val, "J1")

    def test_invalid_product(self):
        with self.assertRaises(ValueError):
            nexmo_product_type(ProductLineCodes.DANA)


class TestNexmoVoiceContentSanitizer(TestCase):
    def setUp(self):
        self.default_content = [
            {"action": "talk", "text": "this is the content"},
            {"action": "input"},
        ]
        self.customer = CustomerFactory(gender='male')

    def test_add_record_action(self):
        sanitizer = NexmoVoiceContentSanitizer(self.default_content, self.customer)
        sanitizer.add_record_action()

        expected_content = [
            {
                'action': 'record',
                'eventUrl': [
                    'http://localhost:8000/api/integration/v1/callbacks/voice-call-recording-callback'
                ],
            },
            {'action': 'talk', 'text': 'this is the content'},
            {'action': 'input'},
        ]
        self.assertEqual(expected_content, sanitizer._content)

    @mock.patch("juloserver.julo.clients.voice_v2.JuloVoiceClientV2")
    def test_voice_style_id(self, mock_julo_voice_client):
        mock_julo_voice_client.rotate_voice_for_account_payment_reminder.return_value = 9
        sanitizer = NexmoVoiceContentSanitizer(self.default_content, self.customer)
        self.assertEqual(9, sanitizer.voice_style_id())
        mock_julo_voice_client.rotate_voice_for_account_payment_reminder.assert_called_once_with(
            self.customer
        )

    def test_voice_style_id_no_customer(self):
        sanitizer = NexmoVoiceContentSanitizer(self.default_content, customer=None)
        self.assertIn(sanitizer.voice_style_id(), NexmoVoice.all_voice_styles())

    @mock.patch("juloserver.julo.clients.voice_v2.JuloVoiceClientV2")
    def test_voice_style_id_exception_with_customer(self, mock_julo_voice_client):
        mock_julo_voice_client.rotate_voice_for_account_payment_reminder.side_effect = Exception(
            "error"
        )
        sanitizer = NexmoVoiceContentSanitizer(self.default_content, self.customer)
        self.assertIn(sanitizer.voice_style_id(), NexmoVoice.all_voice_styles())
        mock_julo_voice_client.rotate_voice_for_account_payment_reminder.assert_called_once_with(
            self.customer
        )

    def test_voice_style_id_cache(self):
        sanitizer = NexmoVoiceContentSanitizer(self.default_content)
        sanitizer._voice_style_id = 100
        self.assertEqual(100, sanitizer.voice_style_id())

    def test_content_not_sanitized(self):
        sanitizer = NexmoVoiceContentSanitizer(self.default_content)
        with self.assertRaises(JuloException):
            self.assertIsNone(sanitizer.content)

    def test_content_sanitized(self):
        sanitizer = NexmoVoiceContentSanitizer(self.default_content)
        sanitizer._is_sanitized = True
        self.assertEqual(self.default_content, sanitizer.content)

    def test_validate(self):
        sanitizer = NexmoVoiceContentSanitizer(
            self.default_content,
            input_webhook_url="http://localhost:8000",
        )

        ret_val = sanitizer.validate()
        self.assertIsNone(ret_val)

    def test_validate_invalid_content(self):
        sanitizer = NexmoVoiceContentSanitizer("", input_webhook_url="http://localhost:8000")
        with self.assertRaises(ValueError):
            sanitizer.validate()

    def test_validate_invalid_content_item(self):
        sanitizer = NexmoVoiceContentSanitizer(
            [1, 2, 3],
            input_webhook_url="http://localhost:8000",
        )
        with self.assertRaises(ValueError):
            sanitizer.validate()

    def test_validate_invalid_talk_action(self):
        sanitizer = NexmoVoiceContentSanitizer([{"action": "talk"}])
        with self.assertRaises(ValueError):
            sanitizer.validate()

    def test_validate_invalid_input_action(self):
        sanitizer = NexmoVoiceContentSanitizer([{"action": "input"}])
        with self.assertRaises(ValueError):
            sanitizer.validate()

    @mock.patch("juloserver.julo.clients.voice_v2.JuloVoiceClientV2")
    def test_sanitize(self, mock_julo_voice_client):
        sanitizer = NexmoVoiceContentSanitizer(
            self.default_content,
            customer=self.customer,
            input_webhook_url="http://localhost:8000/webhook",
        )
        mock_julo_voice_client.rotate_voice_for_account_payment_reminder.return_value = 99

        sanitizer.sanitize()

        expected_content = [
            {'action': 'talk', 'text': 'this is the content', 'language': 'id-ID', 'style': 99},
            {'action': 'input', 'eventUrl': ['http://localhost:8000/webhook']},
        ]
        self.assertEqual(expected_content, sanitizer._content)
