from ..models import SmsHistory, CommsProviderLookup
import logging
from juloserver.julo.exceptions import JuloException

from juloserver.streamlined_communication.utils import get_telco_code_and_tsp_name
from ...streamlined_communication.models import CommsCampaignSmsHistory

logger = logging.getLogger(__name__)


def create_sms_history(**kwargs):
    if 'response' not in kwargs:
        logger.warning({
            'action': "create_sms_history",
            'status': "response missing can't create sms history",
            'data': kwargs
        })
        return

    data = kwargs
    fields = ('customer',
              'payment',
              'account_payment',
              'application',
              'message_content',
              'template_code',
              'to_mobile_phone',
              'phone_number_type',
              'category',
              'template_code',
              'source',
              'partnership_customer_data')

    if data['response'].get('is_comms_campaign_sms') is True:
        fields = fields + ('account',)

    filtered_data = dict((k, data[k]) for k in fields if k in data)
    if (
        int(data['response'].get('status'))
        and data['response']['julo_sms_vendor'] not in ('infobip', 'alicloud', 'whatsapp_service')
    ):
        raise JuloException("error: {}, status: {}".format(
                data['response'].get('error-text'), data['response'].get('status')
        ))
    telco_code, tsp = get_telco_code_and_tsp_name(data['to_mobile_phone'])
    filtered_data['is_otp'] = False
    filtered_data['message_id'] = data['response']['message-id']
    filtered_data['tsp'] = tsp

    if data['response'].get('vendor_status'):
        filtered_data['status'] = data['response'].get('vendor_status')

    provider = CommsProviderLookup.objects.get_or_none(
        provider_name__iexact=data['response']['julo_sms_vendor'])
    if not provider:
        logger.warning({
            'action': "create_sms_history",
            'status': "provider not found",
            'data': kwargs
        })
        return

    filtered_data['comms_provider'] = provider
    if data['response'].get('is_otp'):
        filtered_data['is_otp'] = data['response']['is_otp']

    keys_to_remove_for_sms_campaign_history = [
        'is_otp',
        'source',
        'category',
        'partnership_customer_data',
        'account_payment',
        'payment',
    ]
    if data['response'].get('is_comms_campaign_sms') is True:
        filtered_data_copy = {
            key: value
            for key, value in filtered_data.items()
            if key not in keys_to_remove_for_sms_campaign_history
        }
        sms = CommsCampaignSmsHistory(**filtered_data_copy)
        sms.save()
        return sms
    sms = SmsHistory(**filtered_data)
    sms.save()
    return sms
