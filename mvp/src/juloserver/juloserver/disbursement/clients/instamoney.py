from builtins import next
from builtins import str
from builtins import object
import logging
import requests

from juloserver.disbursement.exceptions import InstamoneyApiError


logger = logging.getLogger(__name__)


class InstamoneyClient(object):
    """Client for Instamoney API"""
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url

    def validate_bank(self, bank_code):
        url = self.base_url + '/available_disbursements_banks'
        response = requests.get(url, auth=(self.api_key, ''))
        if response.status_code != 200:
            raise InstamoneyApiError(response.json())
        result = next(
            (val for val in response.json() if val['code'] == bank_code), None)
        if not result:
            raise InstamoneyApiError({"error": "Matching Bank code not found"})
        return response, result

    def validate_account(self, bank_account_number):
        pass

    def validate_name(self, bank_account_number, bank_code):
        json = {
            'bank_account_number': str(bank_account_number),
            'bank_code': bank_code
        }
        logger.info(json)
        bank_response, bank_result = self.validate_bank(bank_code)
        json['status'] = 'name_validated'
        json['response_status'] = bank_response.status_code
        logger.info(bank_result)
        return bank_result

    def disburse(self, external_id, amount, account_number, validated_name,
                 bank_code, description, retry_times):
        url = self.base_url + '/disbursements/'
        idempotency_key = '{}-{}'.format(external_id, retry_times)
        headers = {'X-IDEMPOTENCY-KEY': idempotency_key}
        json = {
            'external_id': external_id,
            'amount': amount,
            'bank_code': bank_code,
            'account_holder_name': validated_name,
            'account_number': account_number,
            'description': description
        }
        logger.info(json)
        response = requests.post(
            url, auth=(self.api_key, ''), json=json, headers=headers)
        if response.status_code == 400:
            raise InstamoneyApiError(
                'Instamoney disbursement failed. reason: %s, message: %s' %
                (response.json()['error_code'], response.json()['message'])
            )
        json['status'] = 'disbursement_triggered'
        json['response_status'] = response.status_code
        logger.info(json)
        return response.json()

    def get_balance(self):
        url = self.base_url + '/balance'
        response = requests.get(url, auth=(self.api_key, ''))
        if response.status_code != 200:
            raise InstamoneyApiError(
                'Failed to get cash balance on Instamoney: %s' %
                response.json())
        logger.info({
            'status': 'balance_obtained',
            'response_status': response.status_code
        })
        return response.json()
