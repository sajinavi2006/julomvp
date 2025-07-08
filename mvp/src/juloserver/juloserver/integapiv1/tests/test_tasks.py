import mock
from django.test.testcases import TestCase
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.integapiv1.tasks2.callback_tasks import update_voice_call_record
from juloserver.julo.constants import VoiceTypeStatus
from juloserver.julo.tests.factories import VoiceCallRecordFactory
from juloserver.integapiv1.constants import NOT_RETRY_ROBOCALL_STATUS


class TestUpdateVoiceRecord(TestCase):
    def setUp(self) -> None:
        pass

    def test_application_not_found(self):
        data = {
            'conversation_uuid': '3123123-31231233',
            'status': 'completed',
            'from': '622150826333',
            'to': '622150826344',
            'duration': 30,
            'start_time': '2022-01-31 12:00:28',
            'end_time': '2022-01-31 12:01:28',
            'rate': 0.04963000,
            'price': 0.02233350,
        }
        voice_call_record = VoiceCallRecordFactory(
            conversation_uuid=data['conversation_uuid'],
            template_code=''
        )
        result = update_voice_call_record(data)
        voice_call_record.refresh_from_db()
        self.assertNotEqual(voice_call_record.status, data['status'])
        data['status'] = 'test_status'
        result = update_voice_call_record(data)
        voice_call_record.refresh_from_db()
        self.assertEqual(voice_call_record.status, data['status'])

    def test_robocall_success_completed(self):
        data = {
            'conversation_uuid': '3123123-31231233',
            'status': 'completed',
            'from': '622150826333',
            'to': '622150826344',
            'duration': 30,
            'start_time': '2022-01-31 12:00:28',
            'end_time': '2022-01-31 12:01:28',
            'rate': 0.04963000,
            'price': 0.02233350,
        }
        account_payment = AccountPaymentFactory(
            is_robocall_active=True,
            is_collection_called=False,
            is_success_robocall=False,
        )
        voice_call_record = VoiceCallRecordFactory(
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            account_payment=account_payment,
            conversation_uuid=data['conversation_uuid'],
            status='answered',
        )
        update_voice_call_record(data)

        voice_call_record.refresh_from_db()
        account_payment.refresh_from_db()
        self.assertEqual('answered', voice_call_record.status)
        self.assertFalse(account_payment.is_collection_called)
        self.assertTrue(account_payment.is_success_robocall)

    def test_robocall_failed_completed(self):
        data = {
            'conversation_uuid': '3123123-31231233',
            'status': 'completed',
            'from': '622150826333',
            'to': '622150826344',
            'duration': 9,
            'start_time': '2022-01-31 12:00:28',
            'end_time': '2022-01-31 12:01:28',
            'rate': 0.04963000,
            'price': 0.02233350,
        }
        account_payment = AccountPaymentFactory(
            is_robocall_active=True,
            is_collection_called=False,
            is_success_robocall=False,
        )
        voice_call_record = VoiceCallRecordFactory(
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            account_payment=account_payment,
            conversation_uuid=data['conversation_uuid'],
            status='answered',
        )
        update_voice_call_record(data)

        voice_call_record.refresh_from_db()
        account_payment.refresh_from_db()
        self.assertEqual('answered', voice_call_record.status)
        self.assertFalse(account_payment.is_collection_called)
        self.assertFalse(account_payment.is_success_robocall)

    @mock.patch('juloserver.integapiv1.tasks2.callback_tasks.retry_blast_robocall')
    def test_robocall_success_completed_with_retry_robocall(self, mock_retry_blast_robocall):
        data = {
            'conversation_uuid': '3123123-31231233111',
            'status': 'failed',
            'from': '622150826333',
            'to': '622150826344',
            'duration': 30,
            'start_time': '2022-01-31 12:00:28',
            'end_time': '2022-01-31 12:01:28',
            'rate': 0.04963000,
            'price': 0.02233350,
            'detail': 'cannot_route',
        }
        account_payment = AccountPaymentFactory(
            is_robocall_active=True,
            is_collection_called=False,
            is_success_robocall=False,
        )
        VoiceCallRecordFactory(
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            account_payment=account_payment,
            conversation_uuid=data['conversation_uuid'],
            status='started',
            template_code='promo_code_sep_2023'
        )
        update_voice_call_record(data)
        mock_retry_blast_robocall.assert_called()

    @mock.patch('juloserver.integapiv1.tasks2.callback_tasks.retry_blast_robocall')
    def test_robocall_not_retry_robocall(self, mock_retry_blast_robocall):
        conversation_uuid = '3123123-31231233111'
        account_payment = AccountPaymentFactory(
            is_robocall_active=True,
            is_collection_called=False,
            is_success_robocall=False,
        )
        VoiceCallRecordFactory(
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            account_payment=account_payment,
            conversation_uuid=conversation_uuid,
            status='started',
            template_code='promo_code_sep_2023'
        )
        for status in NOT_RETRY_ROBOCALL_STATUS:
            data = {
                'conversation_uuid': conversation_uuid,
                'status': status,
                'from': '622150826333',
                'to': '622150826344',
                'duration': 30,
                'start_time': '2022-01-31 12:00:28',
                'end_time': '2022-01-31 12:01:28',
                'rate': 0.04963000,
                'price': 0.02233350,
            }

            update_voice_call_record(data)
            mock_retry_blast_robocall.assert_not_called()

    def test_loan_robocall_campaign(self):
        data = {
            'conversation_uuid': '3123123-31231233',
            'status': 'completed',
            'from': '622150826333',
            'to': '622150826344',
            'duration': 9,
            'start_time': '2022-01-31 12:00:28',
            'end_time': '2022-01-31 12:01:28',
            'rate': 0.04963000,
            'price': 0.02233350,
            'template_code': 'nexmo_code_sep_2023'
        }
        voice_call_record = VoiceCallRecordFactory(conversation_uuid=data['conversation_uuid'])
        is_loan_robocall_campaign = "promo_code" in str(voice_call_record.template_code)
        self.assertFalse(is_loan_robocall_campaign)
