from builtins import object
import json
import logging
import requests

from juloserver.disbursement.exceptions import GopayClientException
from juloserver.julo.utils import generate_base64

logger = logging.getLogger(__name__)


class GopayClient(object):
    """client for Gopay API"""

    def __init__(self, api_key, api_key_approver, base_url):
        self.auth = 'Basic {}:'.format(generate_base64(api_key))
        self.base_url = base_url
        self.auth_approver = 'Basic {}:'.format(generate_base64(api_key_approver))
        self.headers = {
            'Authorization': self.auth,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def get_balance(self):
        relative_url = "/api/v1/balance"
        url = self.base_url + relative_url
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            raise GopayClientException("Failed get balance, {}".format(response.reason))

        res = response.json()

        logger.info({
            'action': 'get_balance_midtrans',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })

        return res

    def create_payouts(self, receiver_data):
        # receiver_data = beneficiary_name, beneficiary_account, beneficiary_bank,
        #                 beneficiary_email, amount, notes
        # https://docs.midtrans.com/reference/create-payout
        relative_url = "/api/v1/payouts"
        url = self.base_url + relative_url
        data = {
            "payouts": receiver_data
        }
        response = requests.post(url, headers=self.headers, data=json.dumps(data))
        if response.status_code != 201:
            raise GopayClientException("failed get response {}".format(response.reason))

        res = response.json()

        logger.info({
            'action': 'transfer_gopay',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })

        return res

    def approve_payouts(self, reference_ids):
        # https://docs.midtrans.com/reference/accept-payout
        relative_url = "/api/v1/payouts/approve"
        url = self.base_url + relative_url
        data = {
            "reference_nos": reference_ids
        }
        approver_headers = self.headers
        approver_headers['Authorization'] = self.auth_approver
        response = requests.post(url, headers=approver_headers, data=json.dumps(data))

        if response.status_code != 202:
            raise GopayClientException("Failed to approve payout %s " % (reference_ids))

        res = response.json()

        logger.info({
            'action': 'approve_transfer_gopay',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
