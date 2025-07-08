from builtins import object
from future import standard_library
standard_library.install_aliases()
from django.conf import settings
from django.template.loader import render_to_string

import requests
import json
import logging
from bs4 import BeautifulSoup

from juloserver.julo.constants import EmailDeliveryAddress


logger = logging.getLogger(__name__)


class AxiataClient(object):
    UPDATE_CREDIT_INFORMATION = "/Rest-GW/services/juloServices/updateCreditInformation"
    DISBURSEMENT_CONTRACT = "/Rest-GW/services/juloServices/disburseContract"
    REPAYMENT_INFORMATION = "/Rest-GW/services/juloServices/updateRepaymentInformation"
    UPDATE_DIGITAL_SIGNATURE = ""

    def __init__(self):
        self.url = settings.AXIATA_API_URL

        self.headers = {
            'Content-Type': 'application/json'
        }

    def send_update_credit_information(self, data):
        response = self.handle_request(self.UPDATE_CREDIT_INFORMATION, data)
        return response

    def send_disbursement_contract(self, data):
        response = self.handle_request(self.DISBURSEMENT_CONTRACT, data)
        return response

    def send_repayment_information(self, data):
        response = self.handle_request(self.REPAYMENT_INFORMATION, data)
        return response

    def send_update_digital_signature(self, data):
        response = self.handle_request(self, self.UPDATE_DIGITAL_SIGNATURE, data)
        return response

    def handle_request(self, endpoint, data):
        from juloserver.merchant_financing.exceptions import AxiataLogicException

        response = requests.post(
            self.url + endpoint, headers=self.headers, json=data)

        logger.info({
            'action': "Response Merchant Financing Callback",
            'endpoint': endpoint,
            'response': response.content
        })

        return response.json()


class MerchantFinancingEmailClient(object):
    def email_sign_sphp_general(self, application, sign_link):
        customer = application.customer
        title = 'Bapak/Ibu'
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        context = {
            'fullname_with_title': title + ' ' + application.first_name_only,
            'sign_link': sign_link
        }

        subject = 'Tanda tangan SPHP kamu sekarang'
        template = 'email_merchant_finacing_sphp_sign.html'
        msg = render_to_string(template, context)
        email_to = customer.email
        email_from = EmailDeliveryAddress.CS_JULO
        name_from = 'JULO'
        reply_to = EmailDeliveryAddress.CS_JULO

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        logger.info({
            'action': 'email_sphp_general',
            'email': email_to,
            'customer_id': customer.id
        })

        soap = BeautifulSoup(msg, features="lxml").find('body')
        body_msg = " ".join(soap.get_text().split())

        return status, headers, subject, body_msg
