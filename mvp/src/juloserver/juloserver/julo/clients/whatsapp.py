from builtins import str
from builtins import object
import json
import logging

import requests

from django.template.loader import render_to_string
from datetime import datetime, timedelta, date

from ...julo.utils import display_rupiah
from ...julo.utils import format_e164_indo_phone_number
from ...julo.product_lines import ProductLineCodes
from django.conf import settings
from django.utils import timezone
from juloserver.julo.models import WhatsappHistory
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.services import process_streamlined_comm

logger = logging.getLogger(__name__)
COMMUNICATION_PLATFORM = CommunicationPlatform.WA


class WhatsappNotSent(Exception):
    pass

class JuloWhatsappClient(object):
    """
        DEPRECATED, DO NOT USE
        Moving to Julo Golang Whatsapp Service
        JuloWhatsappGoClient()
    """
    def __init__(self, sub_account_id, api_key):
        self.sub_account_id = sub_account_id
        self.api_key = api_key

    def send_whatsapp(self, phone_number, message, xid=''):
        """
        send message with wavecell
        """

        url = "https://api.wavecell.com/chatapps/v1/{}/message/single".format(self.sub_account_id)
        headers = {
            'authorization': 'Bearer {}'.format(self.api_key),
            'content-type': 'application/json'
        }

        e164_number = format_e164_indo_phone_number(phone_number)
        payload = "{\"user\":{\"msisdn\":\"%s\"},\"clientMessageId\":\"%s\",\"type\":\"text\",\"content\":{\"text\":\"%s\"}}" % (e164_number, xid, message)
        response = requests.request("POST", url, data=payload, headers=headers)
        return response

    def send_wa_payment_reminder(self, payment):
        product_line = payment.loan.application.product_line.product_line_code
        phone_number = payment.loan.application.mobile_phone_1
        dpd = payment.due_late_days
        template_name = 'wa_stl_payment_reminder'
        template_code = 'wa_STL_payment_reminder_t' + str(dpd)
        collection_whatsapp = 'nomor ini'
        context = {
            "fullname": payment.loan.application.fullname_with_title,
            "due_amount": display_rupiah(payment.due_amount),
            "due_date": datetime.strftime(payment.due_date, '%d/%m/%Y'),
            "bank_name": payment.loan.julo_bank_name,
            "virtual_account_number": payment.loan.julo_bank_account_number,
            "collection_whatsapp": collection_whatsapp,
        }

        if product_line in ProductLineCodes.mtl():
            mtl_context = {
                "payment_number": payment.payment_number,
                "due_date_minus_4": datetime.strftime(payment.due_date - timedelta(days=4), '%d/%m/%Y'),
                "cashback_amount": display_rupiah(0.03 /
                                                  payment.loan.loan_duration *
                                                  payment.loan.loan_amount)
            }

            context.update(mtl_context)

            template_name = 'wa_mtl_payment_reminder'
            template_code = 'wa_MTL_payment_reminder_t' + str(dpd)

        elif product_line in ProductLineCodes.pede():
            pede_context = {
                "fullname": payment.loan.application.fullname_with_title,
                "payment_number": payment.payment_number,
                "due_amount" : display_rupiah(payment.due_amount),
                "due_date": datetime.strftime(payment.due_date, '%d/%m/%Y'),
                "bank_name": payment.loan.julo_bank_name,
                "virtual_account_number": payment.loan.julo_bank_account_number
            }
            context.update(pede_context)

            template_name = 'wa_pede_payment_reminder'
            template_code = 'wa_PEDE_payment_reminder_t' + str(dpd)
        try:
            filter_ = dict(
                dpd=dpd,
                communication_platform=COMMUNICATION_PLATFORM,
                template_code=template_name
            )
            message = process_streamlined_comm(filter_, replaced_data=context)
        except Exception as e:
            message = render_to_string(template_name+'.txt', context=context)
        else:
            if message:
                msg = render_to_string(template_name + '.html', context)

        history = WhatsappHistory.objects.create(
            customer=payment.loan.application.customer,
            payment=payment,
            application=payment.loan.application,
            message_content=message,
            template_code=template_code,
            to_mobile_phone=format_e164_indo_phone_number(phone_number)
        )
        response = self.send_whatsapp(phone_number, message, history.xid)
        if response.status_code != 200:
            history.status = 'SEND FAILED'
            history.error = json.dumps(response.json())
            history.save()
        return history

    def send_bukalapak_wa_payment_reminder(self, statement):
        customer = statement.customer_credit_limit.customer
        phone_number = customer.phone
        today = timezone.localtime(timezone.now()).day
        template_name = 'wa_bukalapak_payment_reminder_' + str(today)
        collection_whatsapp = '087886904744'
        context = {
            "fullname": customer.fullname,
            "due_amount": display_rupiah(statement.statement_due_amount),
            "due_date": datetime.strftime(statement.statement_due_date, '%d/%m/%Y'),
            "collection_whatsapp": collection_whatsapp,
        }
        message = render_to_string(template_name + '.txt', context=context)
        history = WhatsappHistory.objects.create(
            customer=customer,
            message_content=message,
            template_code=template_name,
            to_mobile_phone=format_e164_indo_phone_number(phone_number)
        )
        response = self.send_whatsapp(phone_number, message, history.xid)
        if response.status_code != 200:
            history.status = 'SEND FAILED'
            history.error = json.dumps(response.json())
            history.save()
        return history
    
class JuloWhatsappClientgo(object):
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def send_whatsapp(self, phone_number, whatsapp_content, purpose, hostname):
        """
            send message with julo whatsapp-service
            The required parameteres are
                phone_number,
                whatsapp_content,
                purpose,
                hostname,
            Currently the value for "purpose" and "hostname" is fixed, but for further improvement, I put it as a configurable parameters.
        """

        url = settings.JULO_WHATSAPP_BASE_URL + '/v1/send-otp'
        headers = {
            "JULO-WHATSAPP-API-KEY": self.api_key,
            "JULO-WHATSAPP-API-SECRET": self.api_secret,
            "content-type": 'application/json'
        }
        data = {
            "phone_number": phone_number,
            "whatsapp_content": whatsapp_content,
            "purpose": purpose,
            "hostname": hostname
        }
        response = requests.request("POST", url, json=data, headers=headers)
        return response
