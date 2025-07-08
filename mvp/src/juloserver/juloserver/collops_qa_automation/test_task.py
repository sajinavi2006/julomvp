from datetime import datetime

from django.conf import settings
from django.test import TestCase
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.tests.factories import VendorRecordingDetailFactory
from juloserver.collops_qa_automation.constant import QAAirudderAPIPhase
from juloserver.collops_qa_automation.factories import RecordingReportFactory, AirudderRecordingUploadFactory
from juloserver.collops_qa_automation.models import AirudderRecordingUpload
from juloserver.collops_qa_automation.task import upload_recording_file_to_airudder_task, slack_alert_negative_words
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.tests.factories import CustomerFactory


def slack_message_mock(message, channel):
    return message, channel


class TestUploadRecordingAirrudder(TestCase):
    def setUp(self):
        self.agent_user = AuthUserFactory()
        j1_customer = CustomerFactory()
        account = AccountFactory(customer=j1_customer)
        AccountPaymentFactory(account=account)
        account_payment = account.accountpayment_set.order_by('due_date').first()
        today = datetime.now()
        today = today.strftime("%Y-%m-%d")
        start_date = today + " 12:00:00"
        end_date = today + " 12:00:30"
        self.vendor_recording = VendorRecordingDetailFactory(
            agent=self.agent_user,
            payment=None,
            account_payment=account_payment,
            call_start=datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S'),
            call_end=datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S'),
            recording_url='{}/unittest/unittestfile.wav'.format(settings.OSS_JULO_COLLECTION_BUCKET)
        )
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.SENDING_RECORDING_CONFIGURATION,
            parameters={
                "recording_resources": ['Intelix'],
                "recording_duration_type": "between",
                "recording_duration": [8, 14],
                "buckets": ['BUCKET_1'],
                "call_result_ids": [self.vendor_recording.call_status.id],
            },
            is_active=True
        )
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.SLACK_NOTIFICATION_NEGATIVE_WORDS_THRESHOLD,
            parameters={
                "negative_words_threshold": 10,
                "threshold_type": ">=",
                "channel": "#call_negative_words_alert"
            },
            is_active=True
        )

    @patch('juloserver.collops_qa_automation.task.file_to_base64')
    @patch('juloserver.collops_qa_automation.task.get_julo_qa_airudder')
    def test_upload_to_airudder(self, mock_airudder_client, mock_file_to_base64):
        mock_file_to_base64.return_value = 'unitest_image'
        mock_airudder_client.return_value.create_task.return_value = ('unitest_task_id', 'OK', 200)
        mock_airudder_client.return_value.upload_recording_file_to_airudder.return_value = (
            'OK', 200
        )
        mock_airudder_client.return_value.start_task.return_value = {
            'status': 'OK',
            'code': 200
        }

        upload_recording_file_to_airudder_task(
            self.vendor_recording.id, 'unitest_path'
        )
        inserted_data = AirudderRecordingUpload.objects.filter(
            vendor_recording_detail=self.vendor_recording,
            phase=QAAirudderAPIPhase.START_TASK
        ).last()
        self.assertTrue(inserted_data)

    @patch('juloserver.collops_qa_automation.task.send_message_normal_format',
           side_effect=slack_message_mock)
    def test_slack_alert_negative_words(self, slack_channel_mock):
        airuder_recording_upload = AirudderRecordingUploadFactory(
            vendor_recording_detail=self.vendor_recording
        )
        recording_report = RecordingReportFactory(
            airudder_recording_upload=airuder_recording_upload,
            r_channel_negative_score="15/10"
        )
        slack_alert_negative_words([recording_report.id])
        assert '#call_negative_words_alert' == slack_channel_mock.mock_calls[0][2]['channel']
        assert len(slack_channel_mock.mock_calls[0][1][0]) > 0
