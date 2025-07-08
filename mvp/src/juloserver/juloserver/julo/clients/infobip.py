import ast
import copy
import http.client
import json
import logging
import random
from datetime import timedelta
from typing import Tuple
from celery import task

from infobip_api_client import (
    ApiClient,
    Configuration,
)
from infobip_api_client.api.send_sms_api import SendSmsApi
from infobip_api_client.model.sms_advanced_textual_request import SmsAdvancedTextualRequest
from infobip_api_client.model.sms_destination import SmsDestination
from infobip_api_client.model.sms_textual_message import SmsTextualMessage

from juloserver.julo.clients.interface import (
    RobocallVendorClientAbstract,
    SmsVendorClientAbstract,
)
from juloserver.julo.constants import VendorConst
from juloserver.julo.exceptions import (
    SmsNotSent,
    VoiceNotSent,
)
from django.conf import settings

from juloserver.julo.models import (
    CommsProviderLookup,
    Customer,
    SmsHistory,
    VoiceCallRecord,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.streamlined_communication.constant import (
    InfobipVoice,
    RedisKey,
)
from juloserver.streamlined_communication.models import SmsVendorRequest
from juloserver.streamlined_communication.tasks import evaluate_sms_reachability

logger = logging.getLogger(__name__)


class JuloInfobipClient(SmsVendorClientAbstract):
    callback_url = (
                settings.BASE_URL + '/api/streamlined_communication/callbacks/v1/infobip-sms-report')

    def __init__(self, source: str = 'JULO', is_otp: bool = False):
        self.source = source if not is_otp else source + '-OTP'            
        sms_host = settings.INFOBIP_SMS_HOST if not is_otp else settings.INFOBIP_SMS_OTP_HOST
        api_key = settings.INFOBIP_SMS_API_KEY if not is_otp else settings.INFOBIP_SMS_OTP_API_KEY
        self.client = ApiClient(Configuration(
            host=sms_host,
            api_key={'APIKeyHeader': api_key},
            api_key_prefix={'APIKeyHeader': 'App'},
        ))

    def send_sms_handler(self, recipient: str, message: str) -> Tuple[str, dict]:
        """
        Infobip Outbound SMS: Send SMS message.
        https://www.infobip.com/docs/api/channels/sms/sms-messaging/outbound-sms/send-sms-message.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.

        Returns:
            str: Returns the argument message.
            dict: Returns the restructured response from Infobip api response.

        Raises:
            SmsNotSent: If an error occur when attempting api call to Infobip.
        """
        if recipient[0] == '+':
            recipient = recipient[1:]

        sms_request = SmsAdvancedTextualRequest(
            messages=[
                SmsTextualMessage(
                    destinations=[
                        SmsDestination(
                            to=recipient,
                        ),
                    ],
                    _from=self.source,
                    text=message,
                    notify_url=self.callback_url
                )
            ]
        )

        params = {
            'to': recipient,
            'from': self.source,
            'text': message,
        }

        logger.info({
            'action': 'sending_sms_via_infobip',
            'host': settings.INFOBIP_SMS_HOST,
            'params': params,
        })

        try:
            api_instance = SendSmsApi(self.client)
            api_response = api_instance.send_sms_message(sms_advanced_textual_request=sms_request)
            SmsVendorRequest.objects.create(
                vendor_identifier=api_response['messages'][0]['messageId'],
                phone_number=api_response['messages'][0]['to'],
                comms_provider_lookup_id=CommsProviderLookup.objects.get(
                    provider_name=VendorConst.INFOBIP.capitalize()
                ).id,
                payload=api_response,
            )
        except Exception as e:
            raise SmsNotSent(
                'Failed to send sms (via Infobip) to number ' + recipient + ': ' + str(e))

        restructured_response = {'messages': [
            {
                'status': str(api_response['messages'][0]['status']['group_id']),
                'to': api_response['messages'][0]['to'],
                'message-id': api_response['messages'][0]['message_id']
            }
        ]}

        logger.info({
            'status': "sms_sent (via Infobip)",
            'api_response': api_response
        })

        return message, restructured_response

    @staticmethod
    @task(name='infobip_sms_report')
    def fetch_sms_report(report_data: list):
        """
        Process handling sms delivery report callback from infobip.

        Args:
            report_data (list): A list of delivery report from infobip
        Todo:
            Treat infobip status and error differently. Might need new property in sms_history.
        """
        for report in report_data:
            SmsVendorRequest.objects.create(
                vendor_identifier=report['messageId'],
                phone_number=report['to'],
                comms_provider_lookup_id=CommsProviderLookup.objects.get(
                    provider_name=VendorConst.INFOBIP.capitalize()
                ).id,
                payload=report,
            )
            sms_history = SmsHistory.objects.get_or_none(message_id=report['messageId'],
                comms_provider__provider_name=VendorConst.INFOBIP.capitalize())
            if sms_history is None:
                logger.info({
                    'message': 'Infobip send unregistered messsageId',
                    'message_id': report['messageId'],
                    'data': report_data
                })
                continue

            report_error = report['error']
            report_status = report['status']
            # Check if callback report has error or status is not (PENDING, DELIVERED)
            if report_error['groupId'] != 0 or report_status['groupId'] not in (1, 3):
                sms_history.status = 'FAILED'
                sms_history.delivery_error_code = report_error['id']
                evaluate_sms_reachability.delay(
                    report['to'], VendorConst.INFOBIP, sms_history.customer_id
                )

                logger.warning({
                    'message': 'Infobip returns error',
                    'message_id': report['messageId'],
                    'error': '{} - {}'.format(report_error['name'], report_error['description']),
                    'error_id': report_error['id']
                })
            else:
                # DELIVERED_TO_OPERATOR cannot be considered delivered.
                if report_status['id'] != 5:
                    sms_history.status = 'sent_to_provider'
                    logger.info({
                        'action': 'JuloInfobipClient.fetch_sms_report',
                        'message': 'Infobip return DELIVERED_TO_OPERATOR',
                        'data': report_status,
                        'error': report_error
                    })
                else:
                    sms_history.status = report['status']['groupName']
            sms_history.save()
            if report_status['id'] != 5:
                evaluate_sms_reachability.delay(
                    report['to'], VendorConst.INFOBIP, sms_history.customer_id
                )


class JuloInfobipVoiceClient(RobocallVendorClientAbstract):
    callback_url = (
        settings.BASE_URL + '/api/streamlined_communication/callbacks/v1/infobip-voice-report')

    def __init__(self, source: str = '442032864231'):
        self.source = source
        self.authorization = 'App ' + settings.INFOBIP_VOICE_API_KEY
        self.client = http.client.HTTPSConnection(settings.INFOBIP_VOICE_HOST)

    def construct_headers(self) -> dict:
        return {
            'Authorization': self.authorization,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def construct_request_data(self, message: str, recipient: str, voice_randomize: bool = False,
                               **kwargs) -> Tuple[str, dict, int]:
        """
        Construct request data to be send to Infobip's Voice API.

        Args:
            message (str):
            recipient (str):
            voice_randomize (bool):
            **kwargs:

        Returns:
            str: A json dumped payload.
            dict: A dictionary of header content.
            int: The mapped voice caller id.
        """
        if voice_randomize:
            voice, voice_id = self.rotate_voice_caller(kwargs['customer'])
        else:
            voice = InfobipVoice().default_voice
            voice_id = 20

        payload = json.dumps({
            'messages': [
                {
                    'from': self.source,
                    'destinations': [{'to': recipient}],
                    'text': message,
                    'language': 'id',
                    'voice': voice,
                    'notifyUrl': self.callback_url,
                }
            ]
        })
        headers = self.construct_headers()

        return payload, headers, voice_id

    def rotate_voice_caller(self, customer: Customer) -> Tuple[dict, int]:
        """
        Rotates the robo voice caller based on customer's called history.

        Args:
            customer (Customer): A Customer class object.

        Returns:
            dict: A dictionary of voice caller detail.
            int: The mapped id of the voice.
        """
        infobip_voice_map_class = InfobipVoice()
        infobip_comms_provider = CommsProviderLookup.objects.get(provider_name='Infobip')
        last_voice_call_record = VoiceCallRecord.objects.filter(
            application__customer=customer, comms_provider=infobip_comms_provider
        ).values_list('voice_style_id', flat=True).last()

        default_voices = infobip_voice_map_class.voice_style_id_map['id']['Pria']
        all_voices_single_gender = infobip_voice_map_class.voice_style_id_map['id'].get(
            customer.gender, default_voices)
        if last_voice_call_record:
            next_voices = copy.copy(all_voices_single_gender)
            try:
                next_voices.remove(last_voice_call_record)
            except ValueError as e:
                pass
            random_choice = random.choice(next_voices)
            return infobip_voice_map_class.voice_value_map[random_choice], random_choice

        random_choice = random.choice(all_voices_single_gender)
        return infobip_voice_map_class.voice_value_map[random_choice], random_choice

    def send_robocall_handler(self, recipient: str, message: str, randomize_voice: bool, **kwargs
                              ) -> dict:
        """
        Infobip Voice Message: Send advanced voice message.
        https://www.infobip.com/docs/api/channels/voice/voice-message/send-advanced-voice-tts.
        We do not use the Send Single Voice Message API as it does not support callback.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.
            randomize_voice (bool): False or True randomize robo voices.
        Returns:
            dict: Returns the response from Infobip API .

        Raises:
            VoiceNotSent: If an error occur when attempting api call to Infobip.
        """
        if recipient[0] == '+':
            recipient = recipient[1:]

        payload, headers, voice_id = self.construct_request_data(message, recipient,
            randomize_voice, **kwargs)

        try:
            self.client.request('POST', '/tts/3/advanced', payload, headers)
            api_response = self.client.getresponse()
            data = json.loads(api_response.read())
        except Exception as e:
            raise VoiceNotSent('Failed to execute robocall to number ' + recipient + ': ' + str(e))

        logger.info({
            'status': 'voice_sent (via Infobip)',
            'api_response': data
        })

        return data, voice_id

    @staticmethod
    @task(name='infobip_voice_report')
    def fetch_voice_report(report_data: list):
        """
        Process handling voice delivery report callback from infobip.

        Args:
            report_data (list): A list of delivery report from infobip
        """
        for report in report_data:
            voice_call_record = VoiceCallRecord.objects.get_or_none(uuid=report['messageId'])
            if voice_call_record is None:
                logger.info({
                    'message': 'Infobip send unregistered messsageId',
                    'message_id': report['messageId'],
                    'data': report
                })
                continue

            report_error = report['error']
            report_status = report['status']
            data_update = {
                'duration': report['voiceCall']['duration'],
                'start_time': report['voiceCall']['startTime'],
                'end_time': report['voiceCall']['endTime'],
                'call_from': report['from'],
                'call_to': report['to'],
            }
            # Check if callback report has error or status is not (PENDING, DELIVERED)
            if report_error['groupId'] != 0 or report_status['groupId'] not in (1, 3):
                data_update.update({'status': 'failed'})

                logger.warning({
                    'message': 'Infobip returns error',
                    'message_id': report['messageId'],
                    'error': '{} - {}'.format(report_error['name'], report_error['description']),
                    'error_id': report_error['id']
                })
            else:
                # DELIVERED_TO_OPERATOR cannot be considered delivered.
                if report_status['id'] != 5:
                    data_update.update({'status': 'started'})
                    logger.info({
                        'action': 'JuloInfobipVoiceClient.fetch_voice_report',
                        'message': 'Infobip return DELIVERED_TO_OPERATOR',
                        'data': report_status,
                        'error': report_error
                    })
                else:
                    data_update.update({'status': report['status']['groupName']})

            voice_call_record.update_safely(**data_update)

    def fetch_voices(self, language: str = 'id') -> dict:
        """
        Fetches voice list that Infobip voice product provides.
        https://www.infobip.com/docs/api/channels/voice/voice-message/get-voices

        Args:
            language (str): Voices for what language.

        Returns:
            dict: A dictionary listing voices.
        """
        redis_client = get_redis_client()
        infobip_voice_list = redis_client.get(RedisKey.INFOBIP_VOICE_LIST)

        if infobip_voice_list:
            return ast.literal_eval(infobip_voice_list)

        headers = self.construct_headers()
        try:
            self.client.request('GET', '/tts/3/voices/{}'.format(language), '', headers)
            api_response = self.client.getresponse()
            infobip_voice_list = json.loads(api_response.read())
            redis_client.set(
                RedisKey.INFOBIP_VOICE_LIST, infobip_voice_list, timedelta(hours=24)
            )
        except Exception as e:
            raise Exception('Fail to retrieve voice list from infobip: ' + str(e))

        return infobip_voice_list
