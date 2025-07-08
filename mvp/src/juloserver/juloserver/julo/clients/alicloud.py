import json
import logging
from typing import (
    Dict,
    Tuple,
)

import datetime
from celery.task import task

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients.interface import SmsVendorClientAbstract
from juloserver.julo.models import (
    SmsHistory,
    CommsProviderLookup,
    OtpRequest,
)
from juloserver.julo.exceptions import SmsNotSent
from django.conf import settings

from juloserver.julo.constants import (
    AlicloudNoRetryErrorCodeConst,
    VendorConst,
)
from juloserver.streamlined_communication.constant import SmsMapping
from juloserver.streamlined_communication.models import SmsVendorRequest
from juloserver.streamlined_communication.tasks import evaluate_sms_reachability

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class JuloAlicloudClient(SmsVendorClientAbstract):
    alicloud_domain = 'dysmsapi.ap-southeast-1.aliyuncs.com'
    alicloud_version = '2018-05-01'
    alicloud_region_id = 'ap-southeast-1'

    def __init__(self, source: str = 'JULO', is_otp: bool = False):
        # Import in function to avoid Alicloud SDK breaking unit tests.
        from aliyunsdkcore.client import AcsClient
        self.source = source
        self.msg_type = 'NOTIFY' if not is_otp else 'OTP'
        self.client = AcsClient(settings.ALICLOUD_ACCESS_KEY, settings.ALICLOUD_SECRET,
            self.alicloud_region_id)

    def send_sms_handler(self, recipient: str, message: str) -> Tuple[str, dict]:
        """
        Alicloud Short Message Service: SendMessageToGlobe.
        https://www.alibabacloud.com/help/en/short-message-service/latest/sendmessagetoglobe.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.

        Returns:
            str: Returns the argument message.
            dict: Returns the restructured response from Alicloud api response.

        Raises:
            SmsNotSent: If an error occur when attempting api call to Alicloud
                Or if Alicloud's response ResponseCode != 'OK'.
        """
        from aliyunsdkcore.request import CommonRequest

        if recipient[0] == '+':
            recipient = recipient[1:]

        request = CommonRequest(
            domain=self.alicloud_domain,
            version=self.alicloud_version,
            action_name='SendMessageToGlobe',
        )
        request.set_accept_format('json')
        request.set_method('POST')
        request.set_protocol_type('https')
        request.add_query_param('RegionId', self.alicloud_region_id)
        request.add_query_param('To', recipient)
        request.add_query_param('From', self.source)
        request.add_query_param('Message', message)
        request.add_query_param('Type', self.msg_type)

        params = {
            'to': recipient,
            'from': self.source,
            'text': message,
        }

        logger.info({
            'action': 'sending_sms_via_alicloud',
            'domain': 'dysmsapi.ap-southeast-1.aliyuncs.com',
            'params': params,
        })
        try:
            api_response = self.client.do_action_with_exception(request)
            api_response = json.loads(api_response)
            SmsVendorRequest.objects.create(
                vendor_identifier=api_response['MessageId'],
                phone_number=api_response['To'],
                comms_provider_lookup_id=CommsProviderLookup.objects.get(
                    provider_name=VendorConst.ALICLOUD.capitalize()
                ).id,
                payload=api_response,
            )
            if api_response['ResponseCode'] not in (AlicloudNoRetryErrorCodeConst.OK,
                                                    AlicloudNoRetryErrorCodeConst.NOT_SUPPORTED_COUNTRY,
                                                    AlicloudNoRetryErrorCodeConst.ALERT_LIMIT_DAY,
                                                    AlicloudNoRetryErrorCodeConst.ALERT_LIMIT_MONTH,
                                                    AlicloudNoRetryErrorCodeConst.CONTENT_EXCEED_LIMIT,
                                                    AlicloudNoRetryErrorCodeConst.MOBILE_NUMBER_ILLEGAL
                                                    ):
                raise Exception('{} - {}'.format(
                    api_response['ResponseCode'], api_response['ResponseDescription']))

        except Exception as e:
            raise SmsNotSent(
                'Failed to send sms (via Alicloud) to number ' + recipient + ': ' + str(e)) from e

        if api_response['ResponseCode'] == AlicloudNoRetryErrorCodeConst.OK:
            restructured_response = {'messages': [
                {
                    'status': '0',
                    'to': api_response['To'],
                    'message-id': api_response['MessageId']
                }
            ]}

            logger.info(
                {
                    'status': "sms_sent (via Alicloud)",
                    'api_response': api_response
                }
            )
        else:
            restructured_response = {'messages': [
                {
                    'status': '0',
                    'to': recipient,
                    'message-id': None,
                    'vendor_status': api_response['ResponseCode']
                }
            ]}

            logger.info(
                {
                    'status': "Failed to send sms (via Alicloud)",
                    'api_response': api_response
                }
            )

        return message, restructured_response

    @staticmethod
    @task(queue='comms', name='alicloud_sms_callback_report')
    def process_sms_report(data: Dict):
        """
        Process handling sms delivery report callback from Alicloud.

        Args:
            data (Dict): A Dict data expected from Alicloud.
                https://www.alibabacloud.com/help/en/sms/developer-reference/sms-webhook-1?spm=a2c63.p38356.0.0.1d9636b12uDHR2
        """
        SmsVendorRequest.objects.create(
            vendor_identifier=data['MessageId'],
            phone_number=data['To'],
            comms_provider_lookup_id=CommsProviderLookup.objects.get(
                provider_name=VendorConst.ALICLOUD.capitalize()
            ).id,
            payload=data,
        )
        sms_history = SmsHistory.objects.get_or_none(
            message_id=data['MessageId'],
            comms_provider__provider_name=VendorConst.ALICLOUD.capitalize()
        )
        logger_data = {
            'action': 'JuloAlicloudClient.process_sms_report',
            'message_id': data['MessageId'],
        }
        if sms_history is None:
            logger.info({'message': 'Alicloud send unregistered message_id', **logger_data})
            return

        if data['Status'] == '1':
            sms_history.update_safely(status=SmsMapping.STATUS['alicloud']['DELIVERED'])
            evaluate_sms_reachability.delay(
                data['To'], VendorConst.ALICLOUD, sms_history.customer_id
            )
            otp_request = OtpRequest.objects.filter(sms_history_id=sms_history.id)
            otp_request.update(reported_delivered_time=datetime.datetime.now())
        elif data['Status'] == '2':
            sms_history.update_safely(status=SmsMapping.STATUS['alicloud']['FAILED'])
            evaluate_sms_reachability.delay(
                data['To'], VendorConst.ALICLOUD, sms_history.customer_id
            )
            logger.info(
                {
                    'message': 'Alicloud returns error',
                    'sms_history_id': sms_history.id,
                    'error_code': data['ErrorCode'],
                    **logger_data,
                }
            )
        elif data['Status'] == '6':
            logger.info(
                {
                    'message': 'Alicloud does not receive response or delivery status from partner '
                    'after 72 hours',
                    'sms_history_id': sms_history.id,
                    'error_code': data['ErrorCode'],
                    **logger_data,
                }
            )
