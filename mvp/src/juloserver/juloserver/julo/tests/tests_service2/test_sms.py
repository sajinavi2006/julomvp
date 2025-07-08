import mock
from django.test.testcases import TestCase

from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    CommsProviderLookupFactory
)
from juloserver.julo.utils import format_e164_indo_phone_number

from juloserver.julo.models import SmsHistory

from juloserver.streamlined_communication.constant import SmsTspVendorConstants

from juloserver.julo.constants import (
    VendorConst,
    AlicloudNoRetryErrorCodeConst
)


class TestCreateSmsHistory(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    @mock.patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    def test_create_sms_history_with_tsp(self, mock_send_sms):
        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {'status': '0', 'message-id': '1234', 'to': '0857222333', 'julo_sms_vendor': 'nexmo'}
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response
        response_message = sms_response['messages'][0]
        create_sms_history(response=response_message,
                           template_code="test_template_code",
                           message_content="test_dummy_message",
                           to_mobile_phone=format_e164_indo_phone_number(response_message["to"]),
                           phone_number_type="mobile_phone_1",
                           customer=self.application.customer,
                           application=self.application)
        sms_history_obj = SmsHistory.objects.all().last()
        self.assertEqual(sms_history_obj.tsp, SmsTspVendorConstants.OTHERS)

    @mock.patch('juloserver.pin.clients.sms.JuloPinSmsClient.send_sms')
    def test_create_sms_history_for_non_retry_error_code(self, mock_send_sms):
        self.alicloud_provider = CommsProviderLookupFactory(provider_name=VendorConst.ALICLOUD)
        txt_msg = "Dummy sms"
        sms_response = {'messages': [
                {
                    'status': '0',
                    'to': '0857222333',
                    'message-id': None,
                    'vendor_status': AlicloudNoRetryErrorCodeConst.MOBILE_NUMBER_ILLEGAL,
                    'julo_sms_vendor': VendorConst.ALICLOUD
                }
            ]}
        mock_send_sms.return_value = txt_msg, sms_response
        response_message = sms_response['messages'][0]
        create_sms_history(response=response_message,
                           template_code="test_template_code",
                           message_content="test_dummy_message",
                           to_mobile_phone=format_e164_indo_phone_number(response_message["to"]),
                           phone_number_type="mobile_phone_1",
                           customer=self.application.customer,
                           application=self.application)

        sms_history_obj = SmsHistory.objects.all().last()
        self.assertEqual(sms_history_obj.status, AlicloudNoRetryErrorCodeConst.MOBILE_NUMBER_ILLEGAL)
