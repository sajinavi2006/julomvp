import os
import mock
import json
from mock import patch
from django.test.testcases import TestCase
from juloserver.pn_delivery.models import PNBlast, PNBlastEvent, PNDelivery, PNDeliveryEvent, PNTracks
from juloserver.pn_delivery.services import update_pn_details
from juloserver.julo.models import EmailHistory, SmsHistory
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.moengage.services.sms_services import update_sms_details
from juloserver.moengage.services.inapp_notif_services import update_inapp_notif_details
from juloserver.email_delivery.services import update_email_details


class TestMoengageViews(TestCase):
    def setUp(self):
        self.data = {
            "app_name": "App Name",
            "source": "MOENGAGE",
            "moe_request_id": "6564564654646",
            "event_name": "Notification cleared Android",
            "event_code": "NOTIFICATION_CLEARED_MOE",
            "event_uuid": "8888888888",
            "event_time": 1580967474,
            "event_type": "CAMPAIGN_EVENT",
            "event_source": "MOENGAGE",
            "push_id": "775757566756",
            "uid": "1000001350",
            "campaign_id": "44444444",
            "campaign_name": "test camp",
            "campaign_type": "Smart Trigger",
            "campaign_channel": "Push",
            "customer_id": "100000135025",
            "payment_id": 4000000303,
            "account_payment_id": 123,
            "application_id": 2000001408,
            "loan_status_code": 310,
            "gcm_action_id": '',
            "title": "Title",
            "content": "Content",
            "account1_payment_id": 1,
            "account2_payment_id": 2,
            "account3_payment_id": 3,
            "account4_payment_id": 4,
            "account5_payment_id": 5
        }
        self.data1 = {
            "event_name": "Notification cleared Android",
            "event_code": "NOTIFICATION_CLEARED_MOE",
            "event_uuid": "8888888888",
            "event_time": 1580967474,
            "event_type": "CAMPAIGN_EVENT",
            "event_source": "MOENGAGE",
            "push_id": "775757566756",
            "uid": "1000001350",
            "campaign_id": "44444444",
            "campaign_name": "test camp",
            "campaign_type": "Smart Trigger",
            "campaign_channel": "Push",
            "customer_id": "100000135025",
            "payment_id": 4000000303,
            "application_id": 2000001408,
            "account_payment_id": 123,
            "loan_status_code": 310,
            "gcm_action_id": '',
            "title": "Title",
            "content": "Content",
            "account1_payment_id": 1,
            "account2_payment_id": 2,
            "account3_payment_id": 3,
            "account4_payment_id": 4,
            "account5_payment_id": 5
        }

        self.sms_data = {
            "event_code": "SMS Sent",
            "event_source": "MoEngage",
            "template_code": "sms_reminder_1",
            "to_mobile_phone": "628123123212",
            "customer_id" : 1000000325,
            "application_id": 2000000340,
            "payment_id": 4000000340,
            "account_payment_id": 123,
            "phone_number_type": "mobile_number_1",
            "account1_payment_id": 1,
            "account2_payment_id": 2,
            "account3_payment_id": 3,
            "account4_payment_id": 4,
            "account5_payment_id": 5,
        }

        self.inapp_data = {
            "event_source": "MoEngage",
            "event_code": "Mobile In-App Shown",
            "template_code": "Marketing Special Promotion",
            "customer_id": 1000000325
        }

        self.email_data = {
            "event_source": "MoEngage",
            "event_code": "Email Sent",
            "to_email": "abc@123.com",
            "template_code":"MTL_T0",
            "customer_id" : 1000000325,
            "application_id": 2000000340,
            "payment_id": 4000000340,
            "account_payment_id": 123,
            "account1_payment_id": 1,
            "account2_payment_id": 2,
            "account3_payment_id": 3,
            "account4_payment_id": 4,
            "account5_payment_id": 5,
            "campaign_id": "12389238723486723"
        }

        self.stream_data = {
         "app_name": "App Name",
         "source": "MOENGAGE",
         "moe_request_id": "moengage unique request id for each request",
         "events": [{
             "event_name": "Notification Received Android",
             "event_code": "NOTIFICATION_RECEIVED_MOE",
             "event_uuid": "moengage unique id for each event",
             "event_time": 1580967474,
             "event_type": "CAMPAIGN_EVENT",
             "event_source": "MOENGAGE",
             "push_id": "push_id",
             "uid": "<MoEngage customer_id>",
             "event_attributes": {
                 "campaign_id": "353df897hkbh67657",
                 "campaign_name": "Name of the Campaign",
                 "campaign_type": "Smart Trigger",
                 "campaign_channel": "Push"
             },
             "user_attributes": {
                 "moengage_user_id": "moe_internal_user_id",
                 "user_attr_1": "user_attr_val1",
                 "user_attr_2": "user_attr_val2",
                 "customer_id": 1000000329,
                 "application_id": 2000000344,
                 "payment_id": 4000000344,
                 "loan_status_code": 210,
                 "account_payment_id": 123
             }
         }, {
             "event_name": "Sms Sent",
             "event_code": "SMS_SENT",
             "event_uuid": "moengage unique id for each event",
             "event_time": 1580967474,
             "event_type": "CAMPAIGN_EVENT",
             "event_source": "MOENGAGE",
             "push_id": "push_id",
             "uid": "<MoEngage customer_id>",
             "event_attributes": {
                 "campaign_id": "353df897hkbh67658",
                 "campaign_name": "Name of the Campaign",
                 "campaign_type": "Smart Trigger",
                 "campaign_channel": "Push"
             },
             "user_attributes": {
                 "moengage_user_id": "moe_internal_user_id",
                 "user_attr_1": "user_attr_val1",
                 "user_attr_2": "user_attr_val2",
                 "customer_id": 1000000328,
                 "application_id": 2000000343,
                 "to_mobile_phone": "085698288288",
                 "payment_id": 4000000343,
                 "account_payment_id": 123
             }
         }, {
             "event_name": "Email Sent",
             "event_code": "MOE_EMAIL_SENT",
             "event_uuid": "moengage unique id for each event",
             "event_time": 1580967474,
             "event_type": "CAMPAIGN_EVENT",
             "event_source": "MOENGAGE",
             "push_id": "push_id",
             "uid": "<MoEngage customer_id>",
             "event_attributes": {
                 "campaign_id": "353df897hkbh67658",
                 "campaign_name": "Name of the Campaign",
                 "campaign_type": "Smart Trigger",
                 "campaign_channel": "Push"
             },
             "user_attributes": {
                 "moengage_user_id": "moe_internal_user_id",
                 "user_attr_1": "user_attr_val1",
                 "user_attr_2": "user_attr_val2",
                 "customer_id": 1000000328,
                 "application_id": 2000000343,
                 "to_mobile_phone": "085698288288",
                 "payment_id": 4000000343,
                 "to_email": "abc@abc.in",
                 "account_payment_id": 123
             }
         }, {
             "event_name": "In App Shown",
             "event_code": "MOE_IN_APP_SHOWN",
             "event_uuid": "moengage unique id for each event",
             "event_time": 1580967474,
             "event_type": "CAMPAIGN_EVENT",
             "event_source": "MOENGAGE",
             "push_id": "push_id",
             "uid": "<MoEngage customer_id>",
             "event_attributes": {
                 "campaign_id": "353df897hkbh67658",
                 "campaign_name": "Name of the Campaign",
                 "campaign_type": "Smart Trigger",
                 "campaign_channel": "Push"
             },
             "user_attributes": {
                 "moengage_user_id": "moe_internal_user_id",
                 "user_attr_1": "user_attr_val1",
                 "user_attr_2": "user_attr_val2",
                 "customer_id": 1000000328,
                 "application_id": 2000000343,
                 "to_mobile_phone": "085698288288",
                 "payment_id": 4000000343,
                 "to_email": "abc@abc.in"
             }
         }]
         }

    @mock.patch('juloserver.pn_delivery.services.update_pn_details')
    @patch.object(PNTracks.objects, 'create')
    @patch.object(PNDeliveryEvent.objects, 'create')
    @patch.object(PNDelivery.objects, 'create')
    @patch.object(PNBlastEvent.objects, 'create')
    @patch.object(PNBlast.objects, 'create')
    def test_moengage_pn_details(self, mock_create_pn_blast,
                                 mock_create_pn_blast_event,
                                 mock_create_pn_delivery,
                                 mock_create_pn_delivery_event,
                                 mock_create_pn_track, mock_update_pn_details):
        response = self.client.post('/api/moengage/v1/callback/pn_details', data=json.dumps(self.data),
                                    content_type='application/json')
        assert response.status_code == 200


    @patch.object(PNTracks.objects, 'create')
    @patch.object(PNDeliveryEvent.objects, 'create')
    @patch.object(PNDelivery.objects, 'create')
    @patch.object(PNBlastEvent.objects, 'create')
    @patch.object(PNBlast.objects, 'create')
    def test_update_pn_details(self, mock_create_pn_blast,
                                 mock_create_pn_blast_event,
                                 mock_create_pn_delivery,
                                 mock_create_pn_delivery_event,
                                 mock_create_pn_track):
        result = update_pn_details(self.data1)
        self.assertIsNone(result)

    @mock.patch('juloserver.moengage.services.sms_services.update_sms_details')
    @patch.object(SmsHistory.objects, 'create')
    def test_moengage_sms_details(self, mock_update_sms_details, mock_sms_history):
        response = self.client.post('/api/moengage/v1/callback/sms_details',
                                    data=json.dumps(self.sms_data),
                                    content_type="application/json")
        assert response.status_code == 200
        mock_update_sms_details.assert_called()

    @mock.patch('juloserver.moengage.services.inapp_notif_services.update_inapp_notif_details')
    @patch.object(InAppNotificationHistory.objects, 'create')
    def test_moengage_inapp_details(self, mock_update_inapp_details, mock_inapp_history):
        response = self.client.post('/api/moengage/v1/callback/inappnotif_details',
                                    data=json.dumps(self.inapp_data),
                                    content_type="application/json")
        assert response.status_code == 200
        mock_update_inapp_details.assert_called()

    @mock.patch('juloserver.moengage.views.update_email_details')
    @patch.object(EmailHistory.objects, 'create')
    def test_moengage_email_details(self, mock_email_history, mock_email_details):
        response = self.client.post('/api/moengage/v1/callback/email_details',
                                    data=json.dumps(self.email_data),
                                    content_type="application/json")
        assert response.status_code == 200
        mock_email_details.assert_called()

    @patch.object(PNTracks.objects, 'create')
    @patch.object(PNDeliveryEvent.objects, 'create')
    @patch.object(PNDelivery.objects, 'create')
    @patch.object(PNBlastEvent.objects, 'create')
    @patch.object(PNBlast.objects, 'create')
    @patch.object(SmsHistory.objects, 'create')
    @patch.object(InAppNotificationHistory.objects, 'create')
    @patch.object(EmailHistory.objects, 'create')
    def test_moengage_stream_details(self, mock_email, mock_inapp, mock_sms, mock_pn_blast,
                                    mock_pn_blast_event, mock_pn_delivery, mock_pn_delivery_event,
                                    mock_pn_tracks):
        response = self.client.post('/api/moengage/v1/callback/streams',
                                    data=json.dumps(self.stream_data),
                                    content_type="application/json")
        assert response.status_code == 200

    @patch.object(PNTracks.objects, 'create')
    @patch.object(PNDeliveryEvent.objects, 'create')
    @patch.object(PNDelivery.objects, 'create')
    @patch.object(PNBlastEvent.objects, 'create')
    @patch.object(PNBlast.objects, 'create')
    @patch.object(SmsHistory.objects, 'create')
    @patch.object(InAppNotificationHistory.objects, 'create')
    @patch.object(EmailHistory.objects, 'create')
    def test_moengage_stream_details(self, mock_email, mock_inapp, mock_sms, mock_pn_blast,
                                    mock_pn_blast_event, mock_pn_delivery, mock_pn_delivery_event,
                                    mock_pn_tracks):
        response = self.client.post('/api/moengage/v1/callback/streams/updated',
                                    data=json.dumps(self.stream_data),
                                    content_type="application/json")
        assert response.status_code == 200

    @patch.object(SmsHistory.objects, 'create')
    def test_update_sms_details(self, mocked_obj):
        update_sms_details(self.sms_data)
        mocked_obj.assert_called()

        mocked_obj.reset_mock()
        fail_case = self.sms_data
        fail_case['event_code'] = 'failed'
        return_value = update_sms_details(fail_case)
        self.assertIsNone(return_value)
        mocked_obj.assert_not_called()

    @patch.object(InAppNotificationHistory.objects, 'create')
    def test_update_inapp_details(self, mocked_obj):
        update_inapp_notif_details(self.inapp_data)
        mocked_obj.assert_called()

        mocked_obj.reset_mock()
        fail_case = self.inapp_data
        fail_case['event_code'] = 'failed'
        return_value = update_inapp_notif_details(fail_case)
        self.assertIsNone(return_value)
        mocked_obj.assert_not_called()

    @patch.object(EmailHistory.objects, 'create')
    def test_update_email_details(self, mocked_obj):
        update_email_details(self.email_data)
        mocked_obj.assert_called()

        mocked_obj.reset_mock()
        fail_case = self.email_data
        fail_case['event_code'] = 'failed'
        return_value = update_email_details(fail_case)
        self.assertIsNone(return_value)
        mocked_obj.assert_not_called()

    @patch.object(EmailHistory.objects, 'create')
    def test_moengage_stream_deatils_windows_encoded(self, mock_email):
        data_file_path = os.path.join(os.path.dirname(__file__), "email.json")
        with open(data_file_path, 'rb') as payload:
            r = self.client.generic(
                'POST',
                '/api/moengage/v1/callback/streams',
                data=payload.read(),
                content_type='application/json',
            )

        self.assertEquals(200, r.status_code)
