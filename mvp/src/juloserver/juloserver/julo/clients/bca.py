from builtins import object
import json
import logging
import requests
from typing import Dict, Optional, Tuple

from datetime import datetime

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from django.utils import timezone

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import BcaTransactionRecord
from juloserver.julo.utils import generate_hmac_sha256, generate_base64, generate_hex_sha256, \
    generate_sha256_rsa, wrap_sha512_with_base64
from juloserver.julocore.patch import SSLEolPatchManager
from juloserver.payback.tasks import store_payback_api_log

logger = logging.getLogger(__name__)

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl


class BCATLS12Adapter(HTTPAdapter):
    """Transport adapter that enforces TLS v1.2"""

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        kwargs['ssl_context'] = ctx
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **kwargs,
        )

class JuloBcaClient(object):
    """client for BCA API"""
    def __init__(self, api_key, api_secret_key, client_id, client_secret, base_url,
                 corporate_id, account_number, channel_id):
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.corporate_id = corporate_id
        self.account_number = account_number
        self.channel_id = channel_id
        self.token, self.token_type = self.get_access_token()

    def get_access_token(self):
        relative_url = '/api/oauth/token'
        url = self.base_url + relative_url
        auth = 'Basic ' + generate_base64('%s:%s' % (self.client_id, self.client_secret))
        headers = {
            'Authorization': auth,
            'Content-type': 'application/x-www-form-urlencoded'
        }

        session = requests.Session()
        session.mount('https://', BCATLS12Adapter())
        response = session.post(url, headers=headers, data='grant_type=client_credentials')
        res = response.json()

        logger.info({
            'action': 'get_access_token_bca',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })

        if response.status_code != 200:
            raise JuloException(
                'Failed to get access token API BCA: %s' % res['ErrorMessage']['English'])

        return (res['access_token'], res['token_type'])

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
            raise JuloException(res['ErrorMessage']['English'])

        if res['AccountDetailDataFailed']:
            raise JuloException('BCA-API check balance: {}'.format(
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
        succeed_transaction = BcaTransactionRecord.objects.filter(
            reference_id=reference_id, status='Success').order_by('-id').last()
        if succeed_transaction:
            return {
                'TransactionID': succeed_transaction.id,
                'TransactionDate': succeed_transaction.transaction_date.strftime('%Y-%m-%d'),
                'ReferenceID': succeed_transaction.reference_id,
                'Amount': succeed_transaction.amount,
                'Status': succeed_transaction.status
            }

        transaction_record = BcaTransactionRecord.objects.create(
            transaction_date=transaction_date, reference_id=reference_id,
            currency_code=currency_code, amount=amount,
            beneficiary_account_number=cust_account_number, remark1=description)

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
            raise JuloException('{} - {}'.format(res['ErrorCode'],
                                                 res['ErrorMessage']['English']))

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
            raise JuloException(res['ErrorMessage']['English'])

        return res

    def inquiry_status(self, request_id):
        """get status of transaction"""
        relative_url = '/va/payments?CompanyCode={}&RequestID={}'.format(self.corporate_id, request_id)
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
        try:
            session = requests.Session()
            session.mount('https://', BCATLS12Adapter())
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as error:
            #sentry_client.captureException()
            logger.error({
                'action': 'get_statements_bca',
                'status': 'Something went wrong',
                'error': error,
            })
            return None
        res = response.json()
        logger.info({
            'action': 'inquiry_status',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
        return res["TransactionData"]

    def domestic_transfer(self, reference_id, transaction_id, cust_account_number,
                          cust_bank_code, cust_name_in_bank, amount, description):
        relative_url = '/banking/corporates/transfers/domestic'
        url = self.base_url + relative_url
        timestamp = timezone.localtime(timezone.now())
        str_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+07:00'
        access_token = self.token
        transaction_date = datetime.now().strftime('%Y-%m-%d')
        reference_id = '{}'.format(reference_id)
        currency_code = "IDR"
        transfer_type = "LLG"

        if len(description) <= 18:
            remark1 = description
            remark2 = ''
        elif 18 < len(description) < 37:
            remark1 = description[0:18]
            remark2 = description[18:len(description)]
        else:
            remark1 = description[0:18]
            remark2 = description[18:37]

        if float(amount) >= 100000000:
            transfer_type = "RTG"

        data = {
            "SourceAccountNumber": self.account_number,
            "TransactionID": transaction_id,
            "TransactionDate": transaction_date,
            "ReferenceID": reference_id,
            "CurrencyCode": currency_code,
            "BeneficiaryAccountNumber": cust_account_number,
            "Remark1": remark1,
            "Amount": amount,
            "Remark2": remark2,
            'BeneficiaryBankCode': cust_bank_code,
            'BeneficiaryName': cust_name_in_bank,
            "TransferType": transfer_type,
            "BeneficiaryCustType": '1',
            "BeneficiaryCustResidence": '1',
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
            'X-BCA-Signature': signature,
            'ChannelID': self.channel_id,
            'CredentialID': self.corporate_id,
        }
        response = requests.post(url, headers=headers, data=body)
        res = response.json()
        logger.info({
            'action': 'bca_domestic_transfer',
            'response_status': response.status_code,
            'request': response.request.__dict__,
            'response': res
        })
        if response.status_code != 200:
            raise JuloException('{} - {}'.format(res['ErrorCode'],
                                                 res['ErrorMessage']['English']))

        return res


class JuloBcaSnapClient(object):
    def __init__(
        self,
        client_id,
        client_secret,
        base_url,
        corporate_id,
        channel_id,
        private_key,
        company_va,
        customer_id=None,
        loan_id=None,
        account_payment_id=None,
        payback_transaction_id=None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.corporate_id = corporate_id
        self.channel_id = channel_id
        self.private_key = private_key
        self.company_va = company_va
        self.customer_id = customer_id
        self.loan_id = loan_id
        self.account_payment_id = account_payment_id
        self.payback_transaction_id = payback_transaction_id
        self.token = self.get_access_token_snap()

    def send_request(
        self,
        request_type: str,
        request_path: str,
        data: Dict,
        headers: Dict,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "json": data,
            "headers": headers,
        }

        return_response = None
        response = None
        error_message = None
        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error_message = None
        except Exception:
            error_message = "Failed"
            if return_response and 'responseMessage' in return_response:
                error_message = return_response['responseMessage']

        logger.info(
            {
                "action": "juloserver.julo.clients.bca.JuloBcaSnapClient.send_request",
                "url": request_params.get("url"),
                "data": data,
                "headers": headers,
                "response": return_response,
            }
        )

        store_payback_api_log.delay(
            url="[%s] %s" % (request_type.upper(), request_path),
            request_params=request_params,
            vendor="bca",
            response=response,
            return_response=return_response,
            customer_id=self.customer_id,
            loan_id=self.loan_id,
            account_payment_id=self.account_payment_id,
            payback_transaction_id=self.payback_transaction_id,
            error_message=error_message,
        )

        return return_response, error_message

    def get_access_token_snap(self):
        request_type = 'post'
        request_path = '/openapi/v1.0/access-token/b2b'
        timestamp = timezone.localtime(timezone.now())
        x_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        string_to_sign = self.client_id+'|'+x_timestamp
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(),
            password=None,
            backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        headers = {
            'X-TIMESTAMP': x_timestamp,
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
            'Content-Type': 'application/json'
        }
        data = {"grantType": "client_credentials"}
        response_data, error_message = self.send_request(request_type, request_path, data, headers)

        if error_message:
            raise JuloException(
                'Failed to get access token API BCA: %s' % response_data['responseMessage']
            )

        return response_data['accessToken']

    def inquiry_status_snap(self, virtual_account, request_id):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        request_type = 'post'
        request_path = '/openapi/v1.0/transfer-va/status'
        customer_no = virtual_account[len(self.company_va):]
        data = {
            'partnerServiceId': ' ' * 3 + self.company_va,
            'customerNo': str(customer_no),
            'virtualAccountNo': ' ' * 3 + virtual_account,
            'inquiryRequestId': request_id,
            'paymentRequestId': request_id,
            'additionalInfo': {}
        }
        string_to_sign = self.generate_string_to_sign('post', request_path, data)
        headers = {
            'Authorization': 'Bearer {}'.format(self.token),
            'Content-Type': 'application/json',
            'CHANNEL-ID': self.channel_id,
            'X-SIGNATURE': wrap_sha512_with_base64(
                self.client_secret, string_to_sign),
            'X-TIMESTAMP': timestamp,
            'X-PARTNER-ID': self.company_va,
            'X-EXTERNAL-ID': self.generate_external_id(customer_no)
        }

        response_data, error_message = self.send_request(request_type, request_path, data, headers)

        return response_data['virtualAccountData'], error_message

    def generate_external_id(self, customer_no):
        now = timezone.localtime(timezone.now())
        return now.strftime('%Y%m%d%H%M%S') + str(customer_no)

    def generate_string_to_sign(self, http_method, relative_url, request_body):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        minify_json = json.dumps(request_body, separators=(',', ':'))
        hashed_request_body = generate_hex_sha256(minify_json)
        string_to_sign = '{}:{}:{}:{}:{}'.format(
            http_method.upper(),
            relative_url,
            self.token,
            hashed_request_body,
            timestamp
        )
        return string_to_sign
