from builtins import str
from builtins import object
import logging
import requests

from juloserver.julo.exceptions import JuloException


logger = logging.getLogger(__name__)


class JuloXenditClient(object):
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
        json['status'] = 'name_validated'
        json['response_status'] = response.status_code
        logger.info(json)
        return response.json()

    def disburse(self, loan, disbursement_data, description):
        url = self.base_url + '/disbursements/'
        idempotency_key = str(disbursement_data.external_id) + str(disbursement_data.retry_times)
        headers = {'X-IDEMPOTENCY-KEY': idempotency_key}
        json = {
            'external_id': str(loan.application.application_xid),
            'amount': loan.loan_disbursement_amount,
            'bank_code': disbursement_data.bank_code,
            'account_holder_name': loan.application.name_in_bank,
            'account_number': loan.application.bank_account_number,
            'description': description
        }
        logger.info(json)
        response = requests.post(url, auth=(self.api_key, ''), json=json, headers=headers)
        if response.status_code == 400:
            raise JuloException(
                'Xendit disbursement failed. reason: %s, message: %s' %
                (response.json()['error_code'], response.json()['message'])
            )
        json['status'] = 'disbursement_triggered'
        json['response_status'] = response.status_code
        logger.info(json)
        return response.json()

    def get_balance(self):
        url = self.base_url + '/balance'
        response = requests.get(url, auth=(self.api_key, ''))
        if response.status_code == 400:
            raise JuloException(
                'Failed to get cash balance on Xendit: %s' % response.json())
        logger.info({
            'status': 'balance_obtained',
            'response_status': response.status_code
        })
        return response.json()

    def transfer(self, external_id, amount, bank_code, validated_name,
                 bank_number, description, retry_times):
        url = self.base_url + '/disbursements/'
        headers = {'X-IDEMPOTENCY-KEY': '{}{}'.format(external_id, retry_times)}
        json = {
            'external_id': '{}{}'.format(external_id, retry_times),
            'amount': amount,
            'bank_code': bank_code,
            'account_holder_name': validated_name,
            'account_number': bank_number,
            'description': description
        }
        logger.info(json)
        response = requests.post(url, auth=(self.api_key, ''), json=json, headers=headers)

        json['status'] = 'cashback_disbursement_triggered'
        json['response_status'] = response.status_code
        logger.info(json)

        response_json = response.json()
        response_json['status_code'] = response.status_code
        return response_json
