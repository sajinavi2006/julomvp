import logging

from juloserver.julo.clients.sms import JuloSmsClient
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.services import process_streamlined_comm

logger = logging.getLogger(__name__)


class JuloPinSmsClient(JuloSmsClient):
    def sms_new_device_login_alert(self, template_code, mobile_phone, manufacturer=None):
        filter_ = dict(
            communication_platform=CommunicationPlatform.SMS,
            template_code=template_code,
        )
        context = None
        if manufacturer:
            context = {'short_first_new_device_login_name': manufacturer}
        msg = process_streamlined_comm(filter_, replaced_data=context)
        phone_number = format_e164_indo_phone_number(mobile_phone)
        logger.info(
            {'action': 'sms_new_device_login_alert', 'to_phone_number': mobile_phone, 'msg': msg}
        )
        message, response = self.send_sms(phone_number, msg)
        return message, response['messages'][0]
