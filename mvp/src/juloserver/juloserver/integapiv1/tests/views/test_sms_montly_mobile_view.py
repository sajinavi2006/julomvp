from mock.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.reverse import reverse

from juloserver.julo.constants import VendorConst
from juloserver.julo.models import SmsHistory
from juloserver.julo.tests.factories import (
    SmsHistoryFactory,
    OtpRequestFactory,
    CommsProviderLookupFactory,
)
from juloserver.streamlined_communication.models import SmsVendorRequest


class TestSMSMontyMobileView(APITestCase):
    def setUp(self):
        self.url = reverse('v1:monty_sms_callback')
        self.sms_history = SmsHistoryFactory(
            message_id='test_message_id',
            status='delivered',
            delivery_error_code=0,
            is_otp=False,
            to_mobile_phone='1234567890',
        )
        self.customer = self.sms_history.customer

    def test_no_callback_response(self):
        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_no_message_id_or_guid(self):
        data = {'CallBackResponse': {'Status': 'delivered', 'StatusId': '2'}}
        response = self.client.post(self.url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('MessageId', response.data)

    def test_no_status(self):
        data = {'CallBackResponse': {'MessageId': 'test_message_id', 'StatusId': '2'}}
        response = self.client.post(self.url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Status', response.data)

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    def test_no_status_id(self):
        data = {'CallBackResponse': {'MessageId': 'test_message_id', 'Status': 'delivered'}}
        response = self.client.post(self.url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('StatusId', response.data)

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    def test_message_id_not_found(self):
        data = {
            'CallBackResponse': {'MessageId': 'nonexistent', 'Status': 'delivered', 'StatusId': '2'}
        }
        response = self.client.post(self.url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)

    def test_successful_callback(self):
        data = {
            'CallBackResponse': {
                'MessageId': 'test_message_id',
                'Status': 'delivered',
                'StatusId': '2',
            }
        }
        response = self.client.post(self.url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    @patch('juloserver.integapiv1.views.get_julo_sms_client')
    @patch('juloserver.integapiv1.views.create_sms_history')
    def test_delivery_error_code_not_2(self, mock_create_sms_history, mock_get_julo_sms_client):
        data = {
            'CallBackResponse': {
                'MessageId': 'test_message_id',
                'Status': 'undelivered',
                'StatusId': '5',
            }
        }
        self.sms_history.is_otp = True
        self.sms_history.save()

        OtpRequestFactory(
            customer=self.customer,
            request_id='existing_request_id',
            otp_token='123456',
            is_used=False,
            is_active=True,
        )

        mock_send_sms_nexmo = mock_get_julo_sms_client.return_value.send_sms_nexmo
        mock_send_sms_nexmo.return_value = ('mock_message', {'messages': [{'status': '0'}]})
        mock_create_sms_history.return_value = SmsHistoryFactory(
            template_code='retry_for_id_%s' % self.sms_history.id
        )

        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertTrue(
            SmsHistory.objects.filter(
                template_code='retry_for_id_%s' % self.sms_history.id
            ).exists()
        )
        mock_send_sms_nexmo.assert_called_once()

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    @patch('juloserver.integapiv1.views.get_julo_sms_client')
    @patch('juloserver.integapiv1.views.create_sms_history')
    def test_delivery_error_code_not_2_no_existing_otp(
        self, mock_create_sms_history, mock_get_julo_sms_client
    ):
        data = {
            'CallBackResponse': {
                'MessageId': 'test_message_id',
                'Status': 'undelivered',
                'StatusId': '5',
            }
        }
        self.sms_history.is_otp = True
        self.sms_history.save()

        mock_send_sms_nexmo = mock_get_julo_sms_client.return_value.send_sms_nexmo
        mock_send_sms_nexmo.return_value = ('mock_message', {'messages': [{'status': '0'}]})
        mock_create_sms_history.return_value = SmsHistoryFactory(
            template_code='retry_for_id_%s' % self.sms_history.id
        )

        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertTrue(
            SmsHistory.objects.filter(
                template_code='retry_for_id_%s' % self.sms_history.id
            ).exists()
        )
        mock_send_sms_nexmo.assert_called_once()

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    def test_guid_instead_of_message_id(self):
        data = {
            'CallBackResponse': {'Guid': 'test_message_id', 'Status': 'delivered', 'StatusId': '2'}
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)

    @patch('juloserver.integapiv1.views.get_julo_sms_client')
    @patch('juloserver.integapiv1.views.create_sms_history')
    def test_delivery_error_code_5(self, mock_create_sms_history, mock_get_julo_sms_client):
        data = {
            'CallBackResponse': {
                'MessageId': 'test_message_id',
                'Status': 'undelivered',
                'StatusId': '5',
            }
        }
        self.sms_history.is_otp = False
        self.sms_history.save()

        mock_send_sms_nexmo = mock_get_julo_sms_client.return_value.send_sms_nexmo
        mock_send_sms_nexmo.return_value = ('mock_message', {'messages': [{'status': '0'}]})
        mock_create_sms_history.return_value = SmsHistoryFactory(
            template_code='retry_for_id_%s' % self.sms_history.id
        )

        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertTrue(
            SmsHistory.objects.filter(
                template_code='retry_for_id_%s' % self.sms_history.id
            ).exists()
        )
        mock_send_sms_nexmo.assert_called_once()

        sms_vendor_request_exist = SmsVendorRequest.objects.filter(
            vendor_identifier='test_message_id',
        ).exists()
        self.assertTrue(sms_vendor_request_exist)
