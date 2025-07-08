from unittest import mock

from django.test.testcases import TestCase
from django.test import SimpleTestCase

from juloserver.moengage.utils import (
    SendToMoengageManager,
    preprocess_moengage_stream,
)


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendToMoengageManager(SimpleTestCase):
    @mock.patch('juloserver.moengage.utils.MAX_EVENT', 3)
    def test_send_to_moengage(self, mock_send_to_moengage):
        with SendToMoengageManager() as moengage_manager:
            for i in range(8):
                moengage_manager.add(i, [f'data-{i}'])

        mock_send_to_moengage.has_calls([
            mock.call([0, 1, 2], ['data-0', 'data-1', 'data-2']),
            mock.call([3, 4, 5], ['data-3', 'data-4', 'data-5']),
            mock.call([6, 7], ['data-6', 'data-7'])
        ])


class TestSanitizeMoengageStreamData(TestCase):
    def test_no_duplicate_data_return_as_is(self):
        payload = [
            {
                "event_name": "Email Sent",
                "event_code": "MOE_EMAIL_SENT",
                "event_uuid": "unique_id_1",
                "event_time": 1580967474,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "email_id": "recipient_email_1",
                "uid": "user_1",
                "event_attributes": {
                    "campaign_id": "campaign_1",
                    "campaign_name": "Campaign Name 1",
                    "campaign_channel": "Email",
                },
            },
            {
                "event_name": "Push Notification Sent",
                "event_code": "PN_SENT",
                "event_uuid": "unique_id_3",
                "event_time": 1580967490,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "user_2",
                "event_attributes": {
                    "campaign_id": "campaign_2",
                    "campaign_name": "Campaign Name 2",
                    "campaign_channel": "Push",
                },
            },
            {
                "event_name": "SMS Delivered",
                "event_code": "SMS_DELIVERED",
                "event_uuid": "unique_id_4",
                "event_time": 1580967491,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "mobile_number": "recipient_mobile_number",
                "uid": "user_3",
                "event_attributes": {
                    "campaign_id": "campaign_3",
                    "campaign_name": "Campaign Name 3",
                    "campaign_channel": "SMS",
                },
            },
        ]

        result = preprocess_moengage_stream(payload)

        self.assertEqual(result, payload)

    def test_has_duplicate_data_return_no_duplicate_result(self):
        payload = [
            {
                "event_name": "Email Sent",
                "event_code": "MOE_EMAIL_SENT",
                "event_uuid": "unique_id_1",
                "event_time": 1580967474,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "email_id": "recipient_email_1",
                "uid": "user_1",
                "event_attributes": {
                    "campaign_id": "campaign_1",
                    "campaign_name": "Campaign Name 1",
                    "campaign_channel": "Email",
                },
            },
            {
                "event_name": "Email Clicked",
                "event_code": "MOE_EMAIL_CLICK",
                "event_uuid": "unique_id_2",
                "event_time": 1580967480,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "email_id": "recipient_email_1",
                "uid": "user_1",
                "event_attributes": {
                    "campaign_id": "campaign_1",
                    "campaign_name": "Campaign Name 1",
                    "campaign_channel": "Email",
                },
            },
            {
                "event_name": "Push Notification Sent",
                "event_code": "PN_SENT",
                "event_uuid": "unique_id_3",
                "event_time": 1580967490,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "user_2",
                "event_attributes": {
                    "campaign_id": "campaign_2",
                    "campaign_name": "Campaign Name 2",
                    "campaign_channel": "Push",
                },
            },
            {
                "event_name": "SMS Delivered",
                "event_code": "SMS_DELIVERED",
                "event_uuid": "unique_id_4",
                "event_time": 1580967491,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "mobile_number": "recipient_mobile_number",
                "uid": "user_3",
                "event_attributes": {
                    "campaign_id": "campaign_3",
                    "campaign_name": "Campaign Name 3",
                    "campaign_channel": "SMS",
                },
            },
        ]
        expected_result = [
            {
                "event_name": "Email Clicked",
                "event_code": "MOE_EMAIL_CLICK",
                "event_uuid": "unique_id_2",
                "event_time": 1580967480,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "email_id": "recipient_email_1",
                "uid": "user_1",
                "event_attributes": {
                    "campaign_id": "campaign_1",
                    "campaign_name": "Campaign Name 1",
                    "campaign_channel": "Email",
                },
            },
            {
                "event_name": "Push Notification Sent",
                "event_code": "PN_SENT",
                "event_uuid": "unique_id_3",
                "event_time": 1580967490,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "uid": "user_2",
                "event_attributes": {
                    "campaign_id": "campaign_2",
                    "campaign_name": "Campaign Name 2",
                    "campaign_channel": "Push",
                },
            },
            {
                "event_name": "SMS Delivered",
                "event_code": "SMS_DELIVERED",
                "event_uuid": "unique_id_4",
                "event_time": 1580967491,
                "event_type": "CAMPAIGN_EVENT",
                "event_source": "MOENGAGE",
                "mobile_number": "recipient_mobile_number",
                "uid": "user_3",
                "event_attributes": {
                    "campaign_id": "campaign_3",
                    "campaign_name": "Campaign Name 3",
                    "campaign_channel": "SMS",
                },
            },
        ]

        result = preprocess_moengage_stream(payload)

        self.assertEqual(result, expected_result)
