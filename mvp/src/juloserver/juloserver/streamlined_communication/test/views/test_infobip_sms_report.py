import json

from rest_framework.test import APITestCase

from juloserver.julo.constants import VendorConst
from juloserver.julo.tests.factories import CommsProviderLookupFactory
from mock.mock import patch


class TestInfobipMessageReport(APITestCase):
    def setUp(self):
        self.data = {
            'results': [
                {
                    'bulkId': 'BULK-ID-123-xyz',
                    'messageId': '126123',
                    'to': '62231920312',
                    'from': 'SMS Info',
                    'text': 'Test Text',
                    'status': {
                        'groupId': 3,
                        'groupName': 'DELIVERED',
                        'id': 5,
                        'name': 'DELIVERED_TO_HANDSET',
                        'description': 'Message delivered to handset',
                    },
                    'error': {
                        'groupId': 0,
                        'groupName': 'OK',
                        'id': 0,
                        'name': 'NO_ERROR',
                        'description': 'No Error',
                        'permanent': False,
                    },
                }
            ]
        }
        self.infobip_provider = CommsProviderLookupFactory(provider_name=VendorConst.INFOBIP)

    @patch('juloserver.streamlined_communication.views.JuloInfobipClient.fetch_sms_report')
    def test_infobip_message_report_payload_data_exist(self, mock_fetch_sms_report):
        response = self.client.post(
            '/api/streamlined_communication/callbacks/v1/infobip-sms-report',
            data=json.dumps(self.data),
            content_type='application/json',
        )
        response_json = response.json()

        mock_fetch_sms_report.delay.assert_called_once_with(self.data['results'])
        self.assertEqual({"message": 'success'}, response_json['data'])

    @patch('juloserver.streamlined_communication.views.JuloInfobipClient.fetch_sms_report')
    def test_infobip_message_report_payload_data_dont_exist(self, mock_fetch_sms_report):
        response = self.client.post(
            '/api/streamlined_communication/callbacks/v1/infobip-sms-report',
            data=json.dumps({}),
            content_type='application/json',
        )
        response_json = response.json()

        mock_fetch_sms_report.delay.assert_not_called()
        self.assertEqual({"message": 'failure'}, response_json['data'])
