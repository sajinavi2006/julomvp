from builtins import object
import logging
from django.template.loader import render_to_string

from juloserver.julo.utils import format_e164_indo_phone_number

from ..utils import save_sms_history


class PromoSmsClient(object):
    @save_sms_history
    def send_ramadan_sms_promo(self, customer_info, template_info):
        """
        send sms for lebaran event
        """
        application = customer_info['application']
        context = {
            'first_name': application.first_name_only,
            'payment_link': customer_info['payment_link']
        }

        msg = render_to_string(template_info['template'], context)
        phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
        message, response = self.send_sms(phone_number, msg)

        return dict(
            response=response['messages'][0],
            customer=customer_info['customer'],
            application=application,
            template_code=template_info['template_code'],
            message_content=message,
            to_mobile_phone=phone_number,
            phone_number_type='mobile_phone_1'
        )
