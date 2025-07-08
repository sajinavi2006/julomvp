from builtins import str
from builtins import object
import logging
import requests

from juloserver.disbursement.exceptions import XenditApiError


logger = logging.getLogger(__name__)


class XenditClient(object):
    """Client for Xendit API"""
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def validate_name(self, bank_account_number, bank_code):
        url = self.base_url + '/bank_account_data_requests/'
        json = {
            'bank_account_number': str(bank_account_number),
            'bank_code': bank_code
        }
        logger.info(json)
        response = requests.post(url, auth=(self.api_key, ''), json=json)
        if response.status_code != 200:
            raise XenditApiError(response.json())
        json['status'] = 'name_validated'
        json['response_status'] = response.status_code
        logger.info(json)
        return response.json()

    def disburse(self, external_id, amount, account_number, validated_name,
                 bank_code, description, retry_times):
        url = self.base_url + '/disbursements/'
        idempotency_key = '{}{}'.format(external_id, retry_times)
        headers = {'X-IDEMPOTENCY-KEY': idempotency_key}
        json = {
            'external_id': idempotency_key,
            'amount': amount,
            'bank_code': bank_code,
            'account_holder_name': validated_name,
            'account_number': account_number,
            'description': description
        }
        logger.info(json)
        response = requests.post(url, auth=(self.api_key, ''), json=json, headers=headers)
        if response.status_code == 400:
            raise XenditApiError(
                'Xendit disbursement failed. reason: %s, message: %s' %
                (response.json()['error_code'], response.json()['message'])
            )
        json['status'] = 'disbursement_triggered'
        json['response_status'] = response.status_code
        logger.info(json)
        return response.json()

    def get_balance(self):
        url = self.base_url + '/balance?currency=IDR'
        response = requests.get(url, auth=(self.api_key, ''))
        if response.status_code != 200:
            raise XenditApiError(
                'Failed to get cash balance on Xendit: %s' % response.json())
        logger.info({
            'status': 'balance_obtained',
            'response_status': response.status_code
        })
        return response.json()
