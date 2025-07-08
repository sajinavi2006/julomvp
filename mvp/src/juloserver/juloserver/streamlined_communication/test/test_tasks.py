from unittest import mock
from unittest.mock import patch

from django.test import TestCase
from pandas.core.computation.expressions import evaluate

from juloserver.julo.models import CommsProviderLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    CommunicationTypeConst,
    TemplateCode,
    StreamlinedCommCampaignConstants,
)
from juloserver.streamlined_communication.tasks import (
    evaluate_sms_reachability,
    send_pn_fraud_ato_device_change,
    send_sms_campaign_async,
    handle_failed_campaign_and_notify_slack,
    evaluate_email_reachability,
)
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationFactory,
    StreamlinedMessageFactory,
    StreamlinedCampaignDepartmentFactory,
    StreamlinedCommunicationCampaignFactory,
    StreamlinedCommunicationSegmentFactory,
    CommsUserSegmentChunkFactory,
    CommsCampaignSmsHistoryFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    CommsProviderLookupFactory,
    CustomerFactory,
    ApplicationJ1Factory,
    SmsHistoryFactory,
    EmailHistoryFactory,
)
from juloserver.streamlined_communication.models import CommsCampaignSmsHistory


@mock.patch('juloserver.streamlined_communication.tasks.get_push_notification_service')
class TestSendPNFraudATODeviceChange(TestCase):
    def setUp(self):
        # obtained from retroload script
        self.streamlined_comm = StreamlinedCommunicationFactory(
            subject='Transaksimu Gagal',
            heading_title=' ',
            description='This PN is sent when Fraud ATO device change triggered in loan_submission',
            template_code=TemplateCode.FRAUD_ATO_DEVICE_CHANGE_BLOCK,
            message=StreamlinedMessageFactory(message_content=(
                'Sepertinya akunmu bermasalah dan perlu diverifikasi ulang.' 
                'Hubungi CS untuk memulai prosesnya, ya!'
            )),
            communication_platform=CommunicationPlatform.PN,
            type=CommunicationTypeConst.INFORMATION,
            status_code_id=LoanStatusCodes.INACTIVE,
            is_active=True,
            is_automated=True,
            show_in_web=False,
            show_in_android=False,
            time_sent=None,
        )

    def test_send_pn(self, mock_get_push_notification_service):
        mock_pn_service = mock.MagicMock()
        mock_get_push_notification_service.return_value = mock_pn_service

        send_pn_fraud_ato_device_change(1234)
        mock_pn_service.send_pn.assert_called_once_with(self.streamlined_comm, 1234)

    def test_send_pn_not_active_streamlined(self, mock_get_push_notification_service):
        self.streamlined_comm.update_safely(is_automated=False, is_active=False)
        mock_pn_service = mock.MagicMock()
        mock_get_push_notification_service.return_value = mock_pn_service

        send_pn_fraud_ato_device_change(1234)
        mock_pn_service.send_pn.assert_not_called()


class TestSendSmsCampaignAsync(TestCase):
    def setUp(self):
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.sms_campaign = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department
        )
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
        )
        self.sms_campaign.content = self.streamlined_message
        self.sms_campaign.save()
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()
        self.template_code = 'J1_sms_{}'.format(self.sms_campaign.name)
        self.msg = self.sms_campaign.content.message_content

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_send_sms_campaign_async_success(self, mock_send_sms):
        sms_response = {
            "messages": [
                {
                    'status': '0',
                    'message-id': '1234',
                    'to': self.application.mobile_phone_1,
                    'julo_sms_vendor': 'nexmo',
                    'is_comms_campaign_sms': True,
                }
            ]
        }
        txt_msg = "fake sms"
        mock_send_sms.return_value = txt_msg, sms_response
        # account data csv
        csv_item_id = self.application.account_id
        column_header = 'account_id'
        send_sms_campaign_async(
            self.application.mobile_phone_1,
            self.msg,
            self.template_code,
            csv_item_id,
            column_header,
            self.sms_campaign,
        )

        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.all().last()
        self.assertEqual(comms_campaign_sms_history.message_content, self.msg)
        self.assertEqual(
            comms_campaign_sms_history.message_id, sms_response["messages"][0]["message-id"]
        )
        self.assertEqual(comms_campaign_sms_history.account, self.application.account)

        #  application data csv

        csv_item_id = self.application.id
        column_header = 'application_id'
        send_sms_campaign_async(
            self.application.mobile_phone_1,
            self.msg,
            self.template_code,
            csv_item_id,
            column_header,
            self.sms_campaign,
        )

        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.all().last()
        self.assertEqual(comms_campaign_sms_history.message_content, self.msg)
        self.assertEqual(
            comms_campaign_sms_history.message_id, sms_response["messages"][0]["message-id"]
        )
        self.assertEqual(comms_campaign_sms_history.application, self.application)

        #  customer data csv

        csv_item_id = self.customer.id
        column_header = 'customer_id'
        send_sms_campaign_async(
            self.application.mobile_phone_1,
            self.msg,
            self.template_code,
            csv_item_id,
            column_header,
            self.sms_campaign,
        )

        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.all().last()
        self.assertEqual(comms_campaign_sms_history.message_content, self.msg)
        self.assertEqual(
            comms_campaign_sms_history.message_id, sms_response["messages"][0]["message-id"]
        )
        self.assertEqual(comms_campaign_sms_history.customer, self.customer)

        #  phone number data csv

        csv_item_id = self.application.mobile_phone_1
        column_header = 'phone_number'
        send_sms_campaign_async(
            format_e164_indo_phone_number(self.application.mobile_phone_1),
            self.msg,
            self.template_code,
            csv_item_id,
            column_header,
            self.sms_campaign,
        )

        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.all().last()
        self.assertEqual(comms_campaign_sms_history.message_content, self.msg)
        self.assertEqual(
            comms_campaign_sms_history.message_id, sms_response["messages"][0]["message-id"]
        )
        self.assertEqual(
            comms_campaign_sms_history.to_mobile_phone.raw_input,
            format_e164_indo_phone_number(self.application.mobile_phone_1),
        )

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_send_sms_campaign_async_fail(self, mock_send_sms):
        sms_response = {
            "messages": [
                {
                    'status': '1',
                    'message-id': '1234',
                    'to': '0857222333',
                    'julo_sms_vendor': 'nexmo',
                    'is_comms_campaign_sms': True,
                }
            ]
        }
        txt_msg = "fake sms"
        csv_item_id = self.application.mobile_phone_1
        column_header = 'phone_number'
        mock_send_sms.return_value = txt_msg, sms_response
        send_sms_campaign_async(
            self.application.mobile_phone_1,
            self.msg,
            self.template_code,
            csv_item_id,
            column_header,
            self.sms_campaign,
        )

        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.all().last()
        self.assertEqual(comms_campaign_sms_history, None)


class TestHandleFailedCampaignAndNotifySlack(TestCase):
    def setUp(self):
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory(segment_count=2)
        self.comms_segment_chunk1 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk2 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.sms_campaign = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department, user_segment=self.user_segment_obj
        )
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
        )
        self.sms_campaign.content = self.streamlined_message
        self.sms_campaign.save()
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.application.mobile_phone_1 = '088321312312312'
        self.application.save()
        self.template_code = 'J1_sms_{}'.format(self.sms_campaign.name)
        self.msg = self.sms_campaign.content.message_content

    @patch('juloserver.streamlined_communication.tasks.send_slack_bot_message')
    def test_handle_failed_campaign_and_notify_slack_for_campaign_with_no_sms_history(
        self, mock_slack
    ):
        handle_failed_campaign_and_notify_slack(self.sms_campaign)
        self.sms_campaign.refresh_from_db()
        self.assertEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.FAILED
        )
        self.assertEquals(mock_slack.call_count, 1)

    @patch('juloserver.streamlined_communication.tasks.send_slack_bot_message')
    def test_handle_failed_campaign_and_notify_slack_for_campaign_with_sms_history(
        self, mock_slack
    ):
        CommsCampaignSmsHistoryFactory(campaign=self.sms_campaign)
        handle_failed_campaign_and_notify_slack(self.sms_campaign)
        self.sms_campaign.refresh_from_db()
        self.assertNotEquals(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.FAILED
        )
        self.assertEquals(mock_slack.call_count, 0)


@patch('juloserver.streamlined_communication.tasks.get_nsq_producer')
class TestEvaluateEmailReachability(TestCase):
    def setUp(self):
        self.comms_provider_nexmo = CommsProviderLookupFactory(provider_name='nexmo')

    def test_success_publish(self, mock_nsq_producer):
        mock_nsq_producer.return_value.publish_message.return_value = None
        expected_nsq_message = {
            'email': 'dummy@gmail.com',
            'customer_id': 1,
            'status': 'delivered',
            'message_id': 'msg-id-1',
            'event_timestamp': 1,
        }

        evaluate_email_reachability('dummy@gmail.com', 1, 'delivered', 'msg-id-1', 1)
        mock_nsq_producer.return_value.publish_message.assert_called_once_with(
            'communication_service_email_reachability_dev', expected_nsq_message
        )

##TODO: Temporarily disabled due to function disabled
# @patch('juloserver.streamlined_communication.tasks.get_nsq_producer')
# class TestEvaluateSmsReachability(TestCase):
#     def setUp(self):
#         SmsHistoryFactory()
#         self.comms_provider_nexmo = CommsProviderLookupFactory(provider_name='nexmo')

#     def test_consecutive_failure_should_publish(self, mock_nsq_producer):
#         mock_nsq_producer.return_value.publish_message.return_value = None
#         mock_number = '+6282134567890'
#         mock_customer = CustomerFactory()

#         statuses = ['FAILED', 'FAILED', 'FAILED']

#         for status in statuses:
#             SmsHistoryFactory(
#                 to_mobile_phone=mock_number,
#                 status=status,
#                 comms_provider=self.comms_provider_nexmo,
#                 customer=mock_customer,
#             )

#         expected_nsq_messsage = {
#             'phone': mock_number,
#             'status': False,
#             'customer_id': mock_customer.id,
#         }
#         evaluate_sms_reachability('082134567890', 'nexmo', mock_customer.id)
#         mock_nsq_producer.return_value.publish_message.assert_called_once_with(
#             'communication_service_sms_reachability_dev', expected_nsq_messsage
#         )

#     def test_default_status_in_between_consecutive_failed_should_not_publish(
#         self, mock_nsq_producer
#     ):
#         mock_nsq_producer.return_value.publish_message.return_value = None
#         mock_number = '082134567890'
#         mock_customer = CustomerFactory()

#         statuses = ['FAILED', 'FAILED', 'sent_to_provider', 'FAILED']

#         for status in statuses:
#             SmsHistoryFactory(
#                 to_mobile_phone=mock_number,
#                 status=status,
#                 comms_provider=self.comms_provider_nexmo,
#                 customer=mock_customer,
#             )

#         evaluate_sms_reachability(mock_number, 'nexmo', mock_customer.id)
#         mock_nsq_producer.publish_message.assert_not_called()

#     def test_no_recent_records_should_not_call_nsq(self, mock_nsq_producer):
#         mock_number = '082134567890'
#         mock_customer = CustomerFactory()
#         evaluate_sms_reachability(mock_number, 'nexmo', mock_customer.id)
#         mock_nsq_producer.assert_not_called()
