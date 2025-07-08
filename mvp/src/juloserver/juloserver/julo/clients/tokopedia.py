from builtins import str
from builtins import object
import logging
import time
import ast
import requests
import json

from ..utils import generate_sha1_base64
from ..utils import scrub
from ..models import ApplicationNote
from ..models import PartnerAccountAttribution
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


class JuloTokopediaClient(object):
    """Tokopedia Client"""

    def __init__(self, client_id, client_secret, base_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.formula_signature = ''
        self.unix_time = 0
        self.list_status_new = [105, 106, 111, 129, 133, 135, 136, 137, 139, 142,
                                143, 161, 170, 171, 174, 180, 189]
        self.list_status_new_expired = [106, 111, 136, 139, 143, 171, 174, 161]
        self.list_status_new_canceled = [137, 142]
        self.list_status_new_processing = [105, 129]
        self.list_status_new_approved = [170]
        self.list_status_new_disbursed = [180, 189]
        self.list_status_new_rejected = [133, 135]
        self.template_form_name = "form_tokopedia.json"

    def rejected_reason_mapping(self, status, reason=None):
        mapping_135_reason = {
            'active loan exists': 'Have other loan',
            'outside coverage area': 'Outside coverage area',
            'failed DV expired KTP': 'incomplete legal docs',
            'failed DV min income not met': 'incomplete legal docs',
            'failed DV identity': 'incomplete legal docs',
            'failed DV income': 'incomplete legal docs',
            'failed DV other': 'incomplete legal docs',
            'job type blacklisted': 'Job type blacklisted',
            'employer blacklisted': 'Job type blacklisted',
            'facebook friends < 10': 'Others',
            'failed PV employer': 'Failed phone verification (employer, spouse, kin)',
            'failed PV spouse': 'Failed phone verification (employer, spouse, kin)',
            'failed PV applicant': 'Failed phone verification (employer, spouse, kin)',
            'failed CA insuff income': 'Cannot afford loan',
            'failed bank transfer': 'Others',
            'bank account not under own name': 'Others',
            'cannot afford loan': 'Cannot afford loan',
            'basic_savings': 'Cannot afford loan',
            'job_not_black_listed': 'Job type blacklisted',
            'debt_to_income_40_percent': 'Cannot afford loan',
            'monthly_income_gt_3_million': 'Min income not met',
            'monthly_income': 'Min income not met'}

        if status == 133:
            returned_reason = "Not strong credit data"
        elif status == 161:
            returned_reason = "Uncontactable"
        elif status == 135:
            try:
                returned_reason = mapping_135_reason[reason]
            except KeyError:
                returned_reason = "Not strong credit data"

        return returned_reason

    def generate_signature(self, action):
        self.unix_time = int(time.time())
        if action == "update_application_status":
            self.formula_signature = "POST\n%s%s%s\n%s" % ('/micro/pl/program/',
                                                           self.client_id,
                                                           '/applications/update',
                                                           self.unix_time)
        signature = generate_sha1_base64(self.formula_signature, self.client_secret)
        return signature

    def get_interest_rate(self, amount):
        if amount <= 1000000:
            return 10.00
        else:
            return 3.00

    def update_application_status(self, status_change):
        data = "{}"
        url = '%sloan/micro/pl/program/%s/applications/update' % (self.base_url, self.client_id)
        application = status_change.application
        partner_account_attribution = PartnerAccountAttribution.objects.filter(application=application).last()
        headers = {
            "Content-Type": "application/json",
            "Signature": self.generate_signature('update_application_status'),
            "Unix-Time": str(self.unix_time)
        }
        ctx = {
            "application_id": partner_account_attribution.partner_account_id,  # application id tokopedia
            "status": "",
            "disbursed_show": False,
            "rejected_show": False,
            "approve_show": False
        }

        if status_change.status_new in self.list_status_new_processing:
            ctx['status'] = "processing"
            data = render_to_string(self.template_form_name, ctx)
        elif status_change.status_new in self.list_status_new_expired:
            ctx['status'] = "expired"
            data = render_to_string(self.template_form_name, ctx)
        elif status_change.status_new in self.list_status_new_canceled:
            ctx['status'] = "cancelled"
            data = render_to_string(self.template_form_name, ctx)
        elif status_change.status_new in self.list_status_new_disbursed:
            ctx['status'] = "disbursed"
            ctx['disbursed_show'] = True
            ctx['disbursement_date'] = application.loan.fund_transfer_ts.strftime('%d/%m/%Y')
            data = render_to_string(self.template_form_name, ctx)
        elif status_change.status_new in self.list_status_new_rejected:
            ctx['status'] = "rejected"
            ctx['rejected_show'] = True
            ctx['reject_reason'] = self.rejected_reason_mapping(status_change.status_new, status_change.change_reason)
            ctx['rejected_date'] = timezone.localtime(timezone.now()).strftime('%d/%m/%Y')
            data = render_to_string(self.template_form_name, ctx)
        elif status_change.status_new in self.list_status_new_approved:
            ctx['status'] = "approved"
            ctx['approve_show'] = True
            ctx['loan'] = application.loan
            ctx['interest_rate'] = self.get_interest_rate(application.loan.loan_amount)
            ctx['other_fees'] = 0
            ctx['approval_date'] = timezone.localtime(timezone.now()).strftime('%d/%m/%Y')
            data = render_to_string(self.template_form_name, ctx)
        data = ast.literal_eval(data)  # string to dict
        data = scrub(data)  # filter characters
        logger.info({
            "action": "update_application_status_tokopedia",
            "new_status": status_change.status_new,
            "old_status": status_change.status_old,
            "data": data,
            "date": timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        })
        response = requests.post(url, headers=headers, json=data)
        response = json.loads(response.content)
        logger.info({
            "action": "update_application_status_tokopedia",
            "application_id": application.id,
            "response": response,
            "date": timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        })
