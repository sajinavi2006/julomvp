from builtins import str
from builtins import object
import json
import logging
import requests

from datetime import datetime, timedelta
from django.utils import timezone

from juloserver.disbursement.constants import RedisKey
from juloserver.disbursement.models import BcaTransactionRecord
from juloserver.disbursement.exceptions import BcaApiError
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import generate_hmac_sha256, generate_base64, generate_hex_sha256

logger = logging.getLogger(__name__)


class BcaClient(object):
    """client for BCA API"""
    def __init__(self, api_key, api_secret_key, client_id, client_secret, base_url,
                 corporate_id, account_number, use_token=True):
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.corporate_id = corporate_id
        self.account_number = account_number
        self.token = None
        self.token_type = None
        if use_token:
            self.token, self.token_type = self.get_access_token()

    def get_access_token(self):
        redis_client = get_redis_client()
        token_hash = redis_client.get(RedisKey.BCA_AUTH_TOKEN_HASH)
        token_type = redis_client.get(RedisKey.BCA_AUTH_TOKEN_TYPE)

        if not token_hash or not token_type:
            relative_url = '/api/oauth/token'
            url = self.base_url + relative_url
            auth = 'Basic ' + generate_base64('%s:%s' % (self.client_id, self.client_secret))
            headers = {
                'Authorization': auth,
                'Content-type': 'application/x-www-form-urlencoded'
            }

            response = requests.post(url, headers=headers, data='grant_type=client_credentials')
            res = response.json()

            logger.info({
                'action': 'get_access_token_bca',
                'response_status': response.status_code,
                'request': response.request.__dict__,
                'response': res
            })

            if response.status_code != 200:
                raise BcaApiError(
                    'Failed to get access token API BCA: %s' % res['ErrorMessage']['English'])
            token_hash = res['access_token']
            token_type = res['token_type']
            redis_client.set(
                RedisKey.BCA_AUTH_TOKEN_HASH,
                token_hash,
                timedelta(seconds=res['expires_in'] - 600)
            )
            redis_client.set(
                RedisKey.BCA_AUTH_TOKEN_TYPE,
                token_type,
                timedelta(seconds=res['expires_in'] - 600)
            )

        return token_hash, token_type

    def generate_signature(self, method, relative_url, access_token, encrypted_body, timestamp):
        string_to_sign = '%s:%s:%s:%s:%s' % (method.upper(), relative_url, access_token,
                                             encrypted_body, timestamp)
        return generate_hmac_sha256(self.api_secret_key, string_to_sign)

    def get_balance(self):
        relative_url = '/banking/v3/corporates/%s/accounts/%s' % \
                       (self.corporate_id, self.account_number)
        url = self.base_url + relative_url
        timestamp = timezone.localtime(timezone.now())
        str_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+07:00'
        access_token = self.token
        data = ''
        encrypted_data = generate_hex_sha256(data)
        signature = self.generate_signature('GET', relative_url, access_token,
                                            encrypted_data, str_timestamp)
        headers = {
            'Authorization': 'Bearer %s' % (access_token),
            'Content-Type': 'application/json',
            'X-BCA-Key': self.api_key,
            'X-BCA-Timestamp': str_timestamp,
            'X-BCA-Signature': signature
        }
        response = requests.get(url, headers=headers)
        res = response.json()
        logger.info({
            'action': 'get_balance_bca',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
        if response.status_code != 200:
            raise BcaApiError(res['ErrorMessage']['English'])

        if res['AccountDetailDataFailed']:
            raise BcaApiError('BCA-API check balance: {}'.format(
                res['AccountDetailDataFailed'][0]['English']))
        return res

    def transfer(self, reference_id, account_number, amount, description):
        relative_url = '/banking/corporates/transfers'
        url = self.base_url + relative_url
        timestamp = timezone.localtime(timezone.now())
        str_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+07:00'
        access_token = self.token
        transaction_date = datetime.now().strftime('%Y-%m-%d')
        reference_id = '{}'.format(reference_id)
        currency_code = "IDR"
        cust_account_number = account_number
        amount = int(amount)

        transaction_record = BcaTransactionRecord.objects.create(
            transaction_date=transaction_date, reference_id=reference_id,
            currency_code=currency_code, amount=amount,
            beneficiary_account_number=cust_account_number, remark1=description)

        if 'disburse_id' in description:
            description = description.replace('disburse_id', str(transaction_record.id))
            transaction_record.remark1 = description
            transaction_record.save(update_fields=['remark1'])

        if len(description) <= 18:
            remark1 = description
            remark2 = ''

        elif 18 < len(description) < 37:
            remark1 = description[0:18]
            remark2 = description[18:len(description)]

        else:
            remark1 = description[0:18]
            remark2 = description[18:37]

        transaction_id = transaction_record.id
        data = {
            "CorporateID": self.corporate_id,
            "SourceAccountNumber": self.account_number,
            "TransactionID": transaction_id,
            "TransactionDate": transaction_date,
            "ReferenceID": reference_id,
            "CurrencyCode": currency_code,
            "Amount": amount,
            "BeneficiaryAccountNumber": cust_account_number,
            "Remark1": remark1,
            "Remark2": remark2
        }
        body = json.dumps(data).replace(' ', '')
        encrypted_data = generate_hex_sha256(body)
        signature = self.generate_signature('POST',
                                            relative_url,
                                            access_token,
                                            encrypted_data,
                                            str_timestamp)
        headers = {
            'Authorization': 'Bearer %s' % (access_token),
            'Content-Type': 'application/json',
            'X-BCA-Key': self.api_key,
            'X-BCA-Timestamp': str_timestamp,
            'X-BCA-Signature': signature
        }
        response = requests.post(url, headers=headers, data=json.dumps(data))
        res = response.json()
        logger.info({
            'action': 'transfer_bca',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
        if response.status_code != 200:
            transaction_record.status = res['ErrorMessage']['English']
            transaction_record.error_code = res['ErrorCode']
            transaction_record.save()
            raise BcaApiError({'status': response.status_code,
                               'error_code': res['ErrorCode'],
                               'message': res['ErrorMessage']['English'],
                               'transaction_id': transaction_id,
                               'reference_id': reference_id})

        transaction_record.status = res['Status']
        transaction_record.save()

        res['TransactionID'] = transaction_id
        res['ReferenceID'] = reference_id
        res['Amount'] = amount
        return res

    def get_statements(self, start_date, end_date):
        relative_url = '/banking/v3/corporates/{}/accounts/{}/statements'.format(
            self.corporate_id, self.account_number)
        query_param1 = '?EndDate={}&StartDate={}'.format(end_date, start_date)
        query_param2 = '?StartDate={}&EndDate={}'.format(start_date, end_date)
        url = '{}{}{}'.format(self.base_url, relative_url, query_param2)
        timestamp = timezone.localtime(timezone.now())
        str_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+07:00'
        access_token = self.token
        data = ''
        encrypted_data = generate_hex_sha256(data)
        signature = self.generate_signature('GET', relative_url + query_param1, access_token,
                                            encrypted_data, str_timestamp)
        headers = {
            'Authorization': 'Bearer %s' % (access_token),
            'Content-Type': 'application/json',
            'X-BCA-Key': self.api_key,
            'X-BCA-Timestamp': str_timestamp,
            'X-BCA-Signature': signature
        }
        response = requests.get(url, headers=headers)
        res = response.json()
        logger.info({
            'action': 'get_statements_bca',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
        if response.status_code != 200:
            raise BcaApiError(res['ErrorMessage']['English'])

        return res

    def generate_bca_token_response(self, token):
        response_data = {
            'access_token': token,
            'token_type': 'bearer',
            'expires_in': 3600,
            'scope': 'resource.WRITE resource.READ'
        }

        return response_data
