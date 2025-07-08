import hashlib
from datetime import datetime

from django.conf import settings
from django.test import TestCase
from mock import patch

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.tests.factories import VendorRecordingDetailFactory
from juloserver.collops_qa_automation.constant import QAAirudderAPIPhase
from juloserver.collops_qa_automation.factories import RecordingReportFactory, AirudderRecordingUploadFactory
from juloserver.collops_qa_automation.models import AirudderRecordingUpload, RecordingReport
from juloserver.collops_qa_automation.task import upload_recording_file_to_airudder_task, slack_alert_negative_words
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.tests.factories import CustomerFactory
from rest_framework.test import APIClient


class TestUploadingReport(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
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

    def test_store_uploading_report(self):
        airuder_recording_upload = AirudderRecordingUploadFactory(
            vendor_recording_detail=self.vendor_recording
        )
        task_id = airuder_recording_upload.task_id
        key = "airudder"
        sign_value = (task_id + key).encode('utf-8')
        sign = hashlib.md5(sign_value).hexdigest()
        data = {
            "TaskID": airuder_recording_upload.task_id,
            "Sign": sign,
            "QADetail": [
                {
                    "Recordingid": "12336",
                    "Size": "3.3",
                    "Length": "83",
                    "Words": "128",
                    "AsrResults": [
                        {
                            "Channel": "1",
                            "Begin": "1000",
                            "End": "20300",
                            "Sentence": "Selamat pagi",
                            "Words": "2"
                        },
                        {
                            "Channel": "2",
                            "Begin": "23000",
                            "End": "30000",
                            "Sentence": "Selamat malam Negative",
                            "Words": "3"
                        },
                        {
                            "Channel": "1",
                            "Begin": "30020",
                            "End": "40300",
                            "Sentence": "Selamat siang",
                            "Words": "2"
                        }
                    ],
                    "CheckPoint": [
                        {
                            "CheckPointType": "SOP",
                            "CheckPointResultsDetail": [
                                {
                                    "CheckPointVal": "Greeting",
                                    "Channel": "1",
                                    "Begin": "1000",
                                    "End": "20300",
                                    "Sentence": "Selamat pagi"
                                },
                                {
                                    "CheckPointVal": "Greeting",
                                    "Channel": "1",
                                    "Begin": "30020",
                                    "End": "40300",
                                    "Sentence": "Selamat siang"
                                }
                            ]
                        },
                        {
                            "CheckPointType": "Negative",
                            "CheckPointResultsDetail": [
                                {
                                    "CheckPointVal": "True",
                                    "Channel": "2",
                                    "Begin": "23000",
                                    "End": "30000",
                                    "Sentence": "Selamat malam Negative"
                                }
                            ]
                        },
                        {
                            "CheckPointType": "Repeat",
                            "CheckPointResultsDetail": [
                                {
                                    "CheckPointVal": "2",
                                    "Channel": "2",
                                    "Begin": "23000",
                                    "End": "30000",
                                    "Sentence": "Selamat malam Negative"
                                }
                            ]
                        },
                        {
                            "CheckPointType": "VoiceMail",
                            "CheckPointResultsDetail": [
                                {
                                    "CheckPointVal": "True",
                                    "Channel": "",
                                    "Begin": "",
                                    "End": "",
                                    "Sentence": ""
                                }
                            ]
                        }
                    ],
                    "Scores": [
                        {
                            "CheckPointType": "Negative",
                            "Channel": "1",
                            "Score": "1/4"
                        },
                        {
                            "CheckPointType": "SOP",
                            "Channel": "1",
                            "Score": "0/2"
                        },
                        {
                            "CheckPointType": "Negative",
                            "Channel": "2",
                            "Score": "0/4"
                        },
                        {
                            "CheckPointType": "SOP",
                            "Channel": "2",
                            "Score": "1/1"
                        }
                    ]
                }
            ]
        }
        res = self.client.post(
            '/collops_qa_automation/store_recording_report/',
            data=data, format='json')
        assert res.status_code == 200
        inserted_data = RecordingReport.objects.filter(
            airudder_recording_upload=airuder_recording_upload.id,
        ).last()
        self.assertTrue(inserted_data)
