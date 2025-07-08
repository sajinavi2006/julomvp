from builtins import object
from builtins import str
import logging
import json
from django.conf import settings
from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.julo.constants import VoiceTypeStatus, NexmoRobocallConst
from juloserver.julo.models import VoiceCallRecord

logger = logging.getLogger(__name__)


class LoanRefinancingVoiceClient(object):
    def refinancing_reminder(
            self, phone_number, account_payment_or_payment_id,
            template_code, text, is_for_j1=False):
        """
        send voice for proactive reminder
        """
        record_callback_url = settings.BASE_URL + \
            '/api/integration/v1/callbacks/voice-call-recording-callback'
        input_webhook_urls = [
            settings.BASE_URL, '/api/integration/v1/callbacks/voice-call/',
            VoiceTypeStatus.REFINANCING_REMINDER, '/', str(account_payment_or_payment_id)
        ]
        input_webhook_url = ''.join(input_webhook_urls)
        ncco_dict = [
            {"action": "record", "eventUrl": [record_callback_url]},
            {"action": "talk", "voiceName": "Damayanti", "text": text},
            {"action": "input", "eventUrl": [input_webhook_url], "maxDigits": 1,
                "timeOut": NexmoRobocallConst.PROACTIVE_TIMEOUT_DURATION}
        ]
        if template_code == "offergenerated_first_robocall":
            ncco_dict.append(
                {"action": "input", "eventUrl": [input_webhook_url], "maxDigits": 1,
                    "timeOut": NexmoRobocallConst.PROACTIVE_TIMEOUT_DURATION}
            )
        ncco_dict = json.loads(json.dumps(ncco_dict))

        voice_call_record = VoiceCallRecord.objects.create(
            template_code=template_code,
            event_type=VoiceTypeStatus.REFINANCING_REMINDER,
            voice_identifier=account_payment_or_payment_id)

        response = self.create_call(format_nexmo_voice_phone_number(phone_number), ncco_dict)

        logger.info({
            'action': 'sending_voice_call_for_refinancing_reminder',
            'payment_id_or_account_payment_id': account_payment_or_payment_id,
            'response': response
        })

        if response.get('conversation_uuid'):
            voice_call_record.update_safely(
                status=response['status'],
                direction=response['direction'],
                uuid=response['uuid'],
                conversation_uuid=response['conversation_uuid'])
        else:
            voice_call_record.update_safely(status=response.get('status'))

        return response
