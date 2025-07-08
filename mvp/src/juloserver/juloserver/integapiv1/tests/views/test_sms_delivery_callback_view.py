from rest_framework.reverse import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from mock.mock import patch

from juloserver.julo.constants import VendorConst
from juloserver.julo.models import CommsProviderLookup
from juloserver.julo.tests.factories import (
    CommsProviderLookupFactory,
    SmsHistoryFactory,
)
from juloserver.streamlined_communication.models import SmsVendorRequest


class TestSmsDeliveryCallbackView(APITestCase):
    def setUp(self):
        self.url = reverse('v1:nexmo_sms_callback')
        self.sms_history = SmsHistoryFactory(
            message_id='test_message_id', status='delivered', delivery_error_code=0
        )

    def test_no_message_id(self):
        response = self.client.get(self.url, {'status': 'delivered', 'err-code': '0'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('messageId', response.data)

    def test_no_status(self):
        response = self.client.get(self.url, {'messageId': 'test_message_id', 'err-code': '0'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('status', response.data)

    def test_no_err_code(self):
        response = self.client.get(
            self.url, {'messageId': 'test_message_id', 'status': 'delivered'}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('err-code', response.data)

    def test_message_id_not_found(self):
        response = self.client.get(
            self.url, {'messageId': 'nonexistent', 'status': 'delivered', 'err-code': '0'}
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)

    def test_successful_callback(self):
        response = self.client.get(
            self.url, {'messageId': 'test_message_id', 'status': 'delivered', 'err-code': '0'}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('sms_history', response.data)
        self.assertEqual(response.data['sms_history'], self.sms_history.id)

    @patch('juloserver.integapiv1.views.logger.warn')
    def test_delivery_error_logged(self, mock_logger_warn):
        response = self.client.get(
            self.url, {'messageId': 'test_message_id', 'status': 'undelivered', 'err-code': '1'}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_logger_warn.assert_called_once_with(
            {'message_id': 'test_message_id', 'status': 'undelivered', 'delivery_error_code': 1}
        )

    def test_sms_vendor_request_created(self):
        self.client.get(
            self.url, {'messageId': 'test_message_id', 'status': 'delivered', 'err-code': '0'}
        )
        vendor_request = SmsVendorRequest.objects.filter(vendor_identifier='test_message_id').last()
        comms_provider = CommsProviderLookup.objects.get(
            provider_name=VendorConst.NEXMO.capitalize()
        )

        self.assertIsNotNone(vendor_request)
        self.assertEqual(vendor_request.vendor_identifier, 'test_message_id')
        self.assertEqual(vendor_request.comms_provider_lookup_id, comms_provider.id)
