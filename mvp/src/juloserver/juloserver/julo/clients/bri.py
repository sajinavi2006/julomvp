from builtins import object
import logging
import json
import requests
import ast

from django.utils import timezone

from ..exceptions import JuloException
from ..models import KycRequest
from ..utils import scrub
from ..models import BankApplication
from ..models import Loan
from ..statuses import ApplicationStatusCodes
from ..utils import get_jenis_pekerjaan
from ..utils import get_penghasilan_perbulan
from . import get_julo_pn_client
from . import get_julo_sms_client
from django.template.loader import render_to_string
from juloserver.julo.utils import have_pn_device

logger = logging.getLogger(__name__)


class JuloBriClient(object):
    """Bri Client"""

    def __init__(self, x_key, code, client_id, client_secret, base_url):
        self.x_key = x_key
        self.code = code
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.template_form_name = 'form_bri.json'
        self.list_code_rejected = [111,133,135,137,139,142,143,161,171,174]

    def get_access_token(self):
        url = self.base_url + 'token'
        headers = {
            'X-BRI-KEY': self.x_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'grant_type': 'authorization_code',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': self.code,
        }
        response = requests.post(url, headers=headers, data=data)
        response = json.loads(response.content)
        if response['status']:
            return response['data']['access_token']
        else:
            error_message = 'Failed get token : %s' % (response['errDesc'])
            raise JuloException(error_message)

    def send_application_result(self, status, application):
        token = self.get_access_token()
        url = self.base_url + 'julo_reg'
        headers = {
            'X-BRI-KEY': self.x_key,
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        }
        data = self.get_form(status,application) #convert objects to e-form bri
        data = scrub(data) #convert null to empty string
        response = requests.post(url, headers=headers, json=data)
        response = json.loads(response.content)
        logger.info({
            'action': 'sending_application_status_bri',
            'application_id': application.id,
            'data': data,
            'response': response,
            'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        })
        if response['status']:
            if not application.bank_account_number and status:
                kyc = KycRequest.objects.create(
                    application=application,
                    eform_voucher=response['data']['eform_voucher'],
                    expiry_time=response['data']['expire_date'])
                if have_pn_device(application.device):
                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.kyc_in_progress(
                        application.device.gcm_reg_id, application.id)
                get_julo_sms = get_julo_sms_client()
                message_content, api_response = get_julo_sms.sms_kyc_in_progress(
                    application.mobile_phone_1,
                    response['data']['eform_voucher'])
                return kyc
        else:
            error_message = 'Failed request bri store : %s , %s' % (response['responseCode'], response['errDesc'])
            raise JuloException(error_message)

    def get_account_info(self, kyc):
        token = self.get_access_token()
        url = self.base_url + 'julo_bankaccount'
        headers = {
            'X-BRI-KEY': self.x_key,
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        }
        data = {
            "request_type" : "notification_account",
            "application_xid" : kyc.application.application_xid,
            "acct_date" : timezone.localtime(timezone.now()).strftime('%Y-%m-%d'),
            "eform_voucher" : kyc.eform_voucher
        }
        response = requests.post(url, headers=headers, json=data)
        response = json.loads(response.content)
        logger.info({
            'action': 'get_account_info_bri',
            'application_id': application.id,
            'data': data,
            'response': response,
            'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        })
        if response['status']:
            return response['data']['account_no']
        else:
            return None

    def payment_notification(self):
        token = self.get_access_token()
        url = self.base_url + 'julo_payment'
        headers = {
            'X-BRI-KEY': self.x_key,
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        }
        data = {
            "request_type": "notification_payment",
            "application_xid":  123456789,
            "payment_status": "Paid on time",
            "due_amount": 1200000,
            "due_date": "2017-11-28",
            "paid_amount": 1200000,
            "principal_amount": 1000000,
            "interest_amount": 128000,
            "service_fee_amount": 72000,
            "late_fee_amount": 0,
            "paid_date": "2017-11-28"
        }
        response = requests.post(url, headers=headers, json=data)
        response = json.loads(response.content)
        logger.info({
            'action': 'payment_notification_bri',
            'data': data,
            'response': response,
            'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        })
        if response['status']:
            return {
                'status': True,
                'application_xid': response['data']['application_xid']
            }
        else:
            error_message = 'Failed payment notification : %s , %s' % (response['responseCode'], response['errDesc'])
            raise JuloException(error_message)

    def update_info_application(self, status_change):
        application = status_change.application
        if status_change.status_new in self.list_code_rejected:
            self.send_application_result(False, application)
        elif status_change.status_new ==  ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED and status_change.status_old ==  ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED:
            if not application.bank_account_number:
                application.change_status(ApplicationStatusCodes.KYC_IN_PROGRESS)
                application.save()
            self.send_application_result(True, application)

    def get_form(self, status, application):
        data = "{}"
        bank_application = BankApplication.objects.get(application=application)
        ctx = {
            "application" : application,
            "bank_application" : bank_application,
            "jenis_pekerjaan" : get_jenis_pekerjaan(application),
            "penghasilan_perbulan" : get_penghasilan_perbulan(application.monthly_income),
            "eform_show" : False,
            "loan_show" : False,
            "application_show" : True,
            "status" : "reject"
        }
        if status:
            ctx['status'] = "approve"
            loan = Loan.objects.get_or_none(pk=application.loan.id)
            if loan:
                if application.bank_account_number:
                    ctx['loan'] = loan
                    ctx['loan_show'] = True
                    data = render_to_string(self.template_form_name, ctx)
                else:
                    ctx['loan'] = loan
                    ctx['loan_show'] = True
                    ctx['eform_show'] = True
                    data = render_to_string(self.template_form_name, ctx)
        else:
            data = render_to_string(self.template_form_name, ctx)
        return ast.literal_eval(data)