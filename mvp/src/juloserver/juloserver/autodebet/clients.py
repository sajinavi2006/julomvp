import base64
import copy
import hashlib
from builtins import object
import logging
import json
from datetime import timedelta
from secrets import token_hex
from typing import Dict, Tuple, Optional
from urllib.parse import urlencode
import uuid

import requests  # noqa
from babel.dates import format_date
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from django.conf import settings
from django.utils import timezone
from juloserver.autodebet.constants import FeatureNameConst, AutodebetVendorConst

from juloserver.autodebet.constants import RedisKey
from juloserver.dana_linking.constants import RedisKey as dana_linking_redis_key
from juloserver.autodebet.exceptions import AutodebetException
from juloserver.autodebet.models import AutodebetAPILog
from juloserver.integapiv1.utils import generate_signature_asymmetric

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.models import FeatureSetting
from juloserver.julo.utils import generate_hmac_sha256, generate_base64, generate_hex_sha256, \
    generate_sha256_rsa, wrap_sha512_with_base64, generate_sha512_data
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.julo.banks import BankCodes

logger = logging.getLogger(__name__)


def get_bca_autodebet_client(account):
    return AutodebetBCAClient(
        account,
        settings.BCA_AUTODEBET_API_KEY,
        settings.BCA_AUTODEBET_API_SECRET_KEY,
        settings.BCA_AUTODEBET_CLIENT_ID,
        settings.BCA_AUTODEBET_CLIENT_SECRET,
        settings.BCA_AUTODEBET_BASE_URL,
        settings.BCA_AUTODEBET_V_CORPORATE_ID,
        settings.BCA_AUTODEBET_CHANNEL_ID
    )


def get_bca_fund_collection_client(account):
    return AutodebetBCAClient(
        account,
        settings.BCA_FUND_COLLECTION_API_KEY,
        settings.BCA_FUND_COLLECTION_API_SECRET_KEY,
        settings.BCA_FUND_COLLECTION_CLIENT_ID,
        settings.BCA_FUND_COLLECTION_CLIENT_SECRET,
        settings.BCA_FUND_COLLECTION_BASE_URL,
        settings.BCA_FUND_COLLECTION_CORPORATE_ID,
        settings.BCA_AUTODEBET_CHANNEL_ID,
        timeout=120
    )


def get_bri_autodebet_client(account):
    return AutodebetXenditClient(
        account,
        settings.XENDIT_AUTODEBET_API_KEY,
        settings.XENDIT_AUTODEBET_BASE_URL
    )


def autodebet_response_logger(
        request_type, response, return_response, error_message, account, account_payment,
        request_params, vendor, deduction_source=None):

    data = request_params.get('data', request_params.get('json', {}))
    if isinstance(data, str):
        request_params['data'] = json.loads(data)
        if 'json' in request_params:
            request_params.pop('json')

    if not response:
        status = 'failed'
        response_status = 400
        request = json.dumps(request_params)
    else:
        status = 'success' if response.status_code in {200, 201} else 'failed'
        response_status = response.status_code
        request = json.dumps(request_params)

    application = None
    if account:
        application = account.last_application
    logger.info(
        {
            'action': 'autodebet_response_logger - {}'.format(request_type),
            'response_status': response_status,
            'account_id': account.id if account else None,
            'account_payment_id': account_payment.id if account_payment else None,
            'application_xid': application.application_xid if application else None,
            'error': error_message,
            'request': request,
            'response': return_response,
            'status': status,
        }
    )

    autodebet_api_log = AutodebetAPILog.objects.create(
        application_id=application.id if application else None,
        account_id=account.id if account else None,
        account_payment_id=account_payment.id if account_payment else None,
        request_type=request_type.upper(),
        http_status_code=response_status,
        request=request,
        response=json.dumps(return_response) if return_response else None,
        error_message=error_message,
        vendor=vendor,
    )

    if request_type == '[POST] /fund-collection':
        autodebet_api_log.deduction_source = deduction_source
        autodebet_api_log.save()

    return autodebet_api_log.id


class AutodebetBCAClient(object):
    def __init__(self, account, api_key, api_secret_key, client_id, client_secret,
                 base_url, corporate_id, channel_id, timeout=None):
        self.account = account
        self.api_key = api_key
        self.api_secret_key = api_secret_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.corporate_id = corporate_id
        self.channel_id = channel_id
        self.sentry_client = get_julo_sentry_client()
        self.timeout = timeout

    def _construct_api_headers(self, request_type, request_path, data={}):
        current_timestamp = timezone.localtime(timezone.now())
        formatted_timestamp = "{}{}".format(
            current_timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3],
            current_timestamp.strftime('%z')
        )
        response_auth_token, error_message = self._request_auth_token()
        if error_message:
            return None, error_message
        access_token = response_auth_token['access_token']

        api_signature = self._construct_api_signature(
            request_type, request_path, data, access_token, formatted_timestamp)
        return {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % access_token,
            "X-BCA-Key": self.api_key,
            "X-BCA-Timestamp": formatted_timestamp,
            "X-BCA-Signature": api_signature,
            "channel-id": self.channel_id,
            "credential-id": self.corporate_id
        }, "Success"

    def _construct_api_signature(
            self, request_type, request_path, data, access_token, formatted_timestamp):
        encrypted_data = generate_hex_sha256(json.dumps(data).replace(' ', ''))
        string_to_sign = '%s:%s:%s:%s:%s' % (
            request_type.upper(), request_path, access_token, encrypted_data, formatted_timestamp
        )
        return generate_hmac_sha256(self.api_secret_key, string_to_sign)

    def construct_verification_key(self, request_id, random_string):
        return generate_hex_sha256("%s%s%s" % (request_id[1:], self.corporate_id, random_string))

    def _request_auth_token(self):
        auth_string = generate_base64('%s:%s' % (self.client_id, self.client_secret))
        redis_client = get_redis_client()
        cached_token = redis_client.get(RedisKey.CLIENT_AUTH_TOKEN)
        error_message = None

        if not cached_token:
            fresh_response = self.send_request(
                "post", "/api/oauth/token", {"grant_type": "client_credentials"}, False,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": "Basic %s" % auth_string
                },
            )
            try:
                content, error_message = fresh_response
            except ValueError:
                content, error_message, _ = fresh_response

            if not error_message:
                cached_token = content['access_token']
                redis_client.set(
                    RedisKey.CLIENT_AUTH_TOKEN,
                    cached_token,
                    timedelta(seconds=content['expires_in'] - 600)
                )
        return {'access_token': cached_token}, error_message

    def send_request(
            self, request_type, request_path, data, convert_to_string=True,
            headers=None, extra_headers=None, account_payment=None, is_need_api_log=False):
        if not headers:
            headers, error_message = self._construct_api_headers(request_type, request_path, data)
            if not headers:
                return None, error_message

        if extra_headers:
            headers.update(extra_headers)

        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "data": json.dumps(data).replace(' ', '') if convert_to_string else data,
            "headers": headers,
        }

        if self.timeout:
            request_params['timeout'] = self.timeout

        return_response = None
        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error = None
            error_message = None
        except Exception as e:
            self.sentry_client.captureException()
            response = e.response
            error = str(e)
            error_message = "Failed"
            if return_response and 'error_message' in return_response:
                error_message = return_response['error_message']["indonesian"]
            if return_response and 'ErrorMessage' in return_response:
                error_message = return_response['ErrorMessage']["Indonesian"]
            application_id = self.account.last_application.id
            if not account_payment:
                account_payment = self.account.get_oldest_unpaid_account_payment()
                account_payment_id = str(account_payment.id) if account_payment else ""
            else:
                account_payment_id = account_payment.id
            streamer = ""
            if settings.ENVIRONMENT != 'prod':
                streamer = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())

            slack_error_message = "Application ID - {app_id}\n" \
                "Account Payment ID - {acc_payment_id}\n" \
                "Reason - {error_msg}".format(
                    app_id=str(application_id),
                    acc_payment_id=account_payment_id,
                    error_msg=str(error_message),
                )
            slack_messages = streamer + slack_error_message
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#bca-autodebit-alert", text=slack_messages
            )

        deduction_source = None

        if request_path == '/fund-collection':
            deduction_source = self.account.autodebetaccount_set.last().deduction_source

        autodebet_api_log_id = autodebet_response_logger(
            "[%s] %s" % (request_type.upper(), request_path),
            response, return_response, error, self.account, account_payment, request_params,
            "BCA", deduction_source
        )
        if is_need_api_log:
            return return_response, error_message, autodebet_api_log_id
        return return_response, error_message


class AutodebetXenditClient(object):
    def __init__(self, account, api_key, base_url):
        self.account = account
        self.api_key = api_key
        self.base_url = base_url
        self.sentry_client = get_julo_sentry_client()

    def send_request(self, request_type, request_path, data=None, account_payment=None,
                     headers=None):
        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "json": data,
            "headers": headers,
            "auth": (self.api_key, '')
        }

        return_response = None
        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error = None
            error_message = None
        except Exception as e:
            self.sentry_client.captureException()
            response = e.response
            error = str(e)
            error_message = "Failed"
            streamer = ''

            if return_response and 'message' in return_response:
                error_message = '{} - {}'.format(
                    return_response['error_code'],
                    return_response['message']
                )

            application_id = self.account.last_application.id
            if not account_payment:
                account_payment = self.account.get_oldest_unpaid_account_payment()
                account_payment_id = str(account_payment.id) if account_payment else ""
            else:
                account_payment_id = account_payment.id

            if settings.ENVIRONMENT != 'prod':
                streamer = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())

            slack_error_message = "Application ID - {app_id}\n" \
                "Account Payment ID - {acc_payment_id}\n" \
                "Reason - {error_msg}".format(
                    app_id=str(application_id),
                    acc_payment_id=account_payment_id,
                    error_msg=str(error_message),
                )
            slack_messages = streamer + slack_error_message
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#bri-autodebit-alert", text=slack_messages
            )
        autodebet_response_logger(
            "[%s] %s" % (request_type.upper(), request_path),
            response, return_response, error, self.account, account_payment, request_params,
            "BRI"
        )
        return return_response, error_message

    def create_payment_method(self, bri_customer_id, linked_account_id):
        url = "/payment_methods"
        request_method = "post"
        body = {
            "customer_id": bri_customer_id,
            "type": "DEBIT_CARD",
            "properties": {
                "id": linked_account_id
            }
        }

        return self.send_request(request_method, url, body)

    def get_payment_method(self, payment_method_id):
        url = "/payment_methods/" + str(payment_method_id)
        request_method = "get"
        return self.send_request(request_method, url)

    def create_direct_debit_payment(self, reference_id, payment_method_id, amount, enable_otp,
                                    account_payment=None):
        url = "/direct_debits"
        request_method = "post"
        body = {
            "reference_id": reference_id,
            "payment_method_id": payment_method_id,
            "currency": "IDR",
            "amount": amount,
            "enable_otp": enable_otp,
            "callback_url": settings.BASE_URL + "/api/autodebet/bri/v1/callback/transaction"
        }

        direct_debit_result, direct_debit_error = self.send_request(
            request_method,
            url,
            body,
            headers={"Idempotency-key": reference_id},
            account_payment=account_payment)

        if direct_debit_error:
            return direct_debit_result, direct_debit_error

        is_valid, payment_response, payment_error = self._get_payment_by_id(
            account_payment.account.id,
            direct_debit_result['id']
        )

        if is_valid:
            return payment_response, payment_error

        return direct_debit_result, direct_debit_error

    def validate_debit_payment_otp(self, transaction_id, otp_code):
        url = "/direct_debits/{}/validate_otp/".format(transaction_id)
        request_method = "post"
        body = {
            "otp_code": otp_code
        }

        return self.send_request(request_method, url, body)

    def get_account_balance(self, linked_account_id):
        url = "/linked_account_tokens/{}/accounts".format(linked_account_id)
        request_method = "get"

        return self.send_request(request_method, url)

    def unbind_linked_account_token(self, linked_account_id):
        url = "/linked_account_tokens/{}".format(linked_account_id)
        request_method = "delete"

        return self.send_request(request_method, url)

    def _get_payment_by_id(self, account_id, direct_debit_id):
        autodebet_testing_error_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AUTODEBET_TESTING_ERROR, is_active=True).last()

        if not autodebet_testing_error_feature:
            return False, None, None

        if account_id in autodebet_testing_error_feature.parameters['accounts']:
            payment_result, _ = self.send_request(
                'get', '/direct_debits/{}/'.format(direct_debit_id))

            if payment_result['status'] == 'FAILED':
                return True, {'error_code': payment_result['failure_code']}, \
                    payment_result['failure_code']

        return False, None, None

    def inquiry_bri_transaction(self, transaction_id):
        url = '/direct_debits/{}/'.format(transaction_id)
        request_method = 'get'

        return self.send_request(request_method, url)


def get_mandiri_autodebet_client(account, account_payment=None):
    return AutodebetMandiriClient(
        settings.AUTODEBET_MANDIRI_BASE_URL,
        settings.AUTODEBET_MANDIRI_CLIENT_ID,
        settings.AUTODEBET_MANDIRI_CHANNEL_ID,
        settings.AUTODEBET_MANDIRI_CLIENT_KEY,
        settings.AUTODEBET_MANDIRI_CLIENT_SECRET,
        settings.AUTODEBET_MANDIRI_MERCHANT_ID,
        settings.AUTODEBET_MANDIRI_TERMINAL_ID,
        settings.AUTODEBET_MANDIRI_PRIVATE_KEY,
        settings.AUTODEBET_MANDIRI_PUBLIC_KEY_LANDING_PAGE,
        settings.AUTODEBET_MANDIRI_CARD_ENCRYPTION_KEY,
        account,
        account_payment
    )


class AutodebetMandiriClient(object):
    def __init__(self, base_url, client_id, channel_id, client_key, client_secret, merchant_id,
                 terminal_id, private_key, public_key_landing_page, card_encryption_key, account,
                 account_payment):
        self.base_url = base_url
        self.client_id = client_id
        self.channel_id = channel_id
        self.client_key = client_key
        self.client_secret = client_secret
        self.merchant_id = merchant_id
        self.terminal_id = terminal_id
        self.private_key = private_key
        self.public_key_landing_page = public_key_landing_page
        self.card_encryption_key = card_encryption_key
        self.account = account
        self.account_payment = account_payment
        self.token = self.get_access_token()
        self.sentry_client = get_julo_sentry_client()

    def construct_api_headers(self, request_type, request_path, customer, data={}):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        relative_url = request_path[request_path.find('/directDebit'):]
        string_to_sign = self.generate_string_to_sign(request_type, relative_url, data)

        return {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.card_encryption_key, string_to_sign),
            'X-EXTERNAL-ID': self.generate_external_id(customer),
            'X-PARTNER-ID': self.client_id,
            'CHANNEL-ID': self.channel_id
        }, 'Success'

    def send_request(self, request_type, request_path, data, customer=None, headers=None,
                     is_need_api_log=False, is_need_journey_id=False):
        if not headers:
            headers, error_message = self.construct_api_headers(request_type, request_path,
                                                                customer, data)
            if not headers:
                return None, error_message

        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "data": json.dumps(data),
            "headers": headers
        }

        return_response = None

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error = None
            error_message = None
        except Exception as e:
            self.sentry_client.captureException()
            response = e.response
            error = str(e)
            error_message = "Failed"

            if return_response and 'responseMessage' in return_response:
                error_message = return_response['responseMessage']

        autodebet_api_log_id = autodebet_response_logger(
            "[%s] %s" % (request_type.upper(), request_path),
            response, return_response, error, self.account, self.account_payment, request_params,
            "MANDIRI"
        )
        if is_need_api_log:
            return return_response, error_message, autodebet_api_log_id

        if is_need_journey_id:
            return return_response, error_message, data['journeyID']

        return return_response, error_message

    def get_access_token(self):
        redis_client = get_redis_client()
        cached_token = redis_client.get(RedisKey.MANDIRI_CLIENT_AUTH_TOKEN)
        if cached_token:
            return cached_token

        relative_url = ':7778/directDebit/v3.0/access-token/b2b'
        private_key = self.private_key
        url = self.base_url + relative_url
        timestamp = timezone.localtime(timezone.now())
        x_timestamp = timestamp.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        string_to_sign = self.client_key + '|' + x_timestamp
        private_key_bytes = serialization.load_pem_private_key(
            private_key.encode(),
            password=None,
            backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )

        headers = {
            'X-TIMESTAMP': x_timestamp,
            'X-CLIENT-KEY': self.client_key,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers, data='{"grantType": "client_credentials"}')
        res = response.json()

        if response.status_code != 200:
            raise res['responseMessage']

        redis_client.set(
            RedisKey.MANDIRI_CLIENT_AUTH_TOKEN,
            res['accessToken'],
            timedelta(seconds=900)
        )
        return res['accessToken']

    def generate_string_to_sign(self, http_method, relative_url, request_body):
        timestamp = self.get_timestamp()
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

    def generate_external_id(self, customer_xid):
        now = timezone.localtime(timezone.now())
        return now.strftime('%y%m%d%H%M%S%f')[:-3] + str(customer_xid)

    def generate_signature_registration(self, data):
        enc = generate_sha512_data(
            self.card_encryption_key, 'JULO:{}:{}'.format(data, self.card_encryption_key)
        )
        return enc

    def registration_card_unbind(self, customer_xid, token):
        relative_url = '/directDebit/v3.0/registration-card-unbind'
        url = ':7778' + relative_url
        data = {
            'merchantID': self.merchant_id,
            'terminalID': self.terminal_id,
            'journeyID': self.generate_external_id(customer_xid),
            'token': token
        }
        return self.send_request('post', url, data, {})

    def create_payment_purchase_submit(
            self, purchase_id, bank_card_token, amount, purchase_product_type, customer_xid):
        relative_url = '/directDebit/v3.0/debit/payment-host-to-host'
        url = ':7778' + relative_url
        data = {
            'merchantID': self.merchant_id,
            'terminalID': self.terminal_id,
            'journeyID': purchase_id,
            'partnerReferenceNo': purchase_id,
            'bankCardToken': bank_card_token,
            'amount': {
                'value': format(amount, '.2f'),
                'currency': 'IDR'
            },
            'additionalInfo': {
                'productType': purchase_product_type
            }
        }
        return self.send_request('post', url, data, customer_xid)

    def get_timestamp(self):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        return timestamp

    def verify_otp(self, otp, customer_id, charge_token, journey_id):
        relative_url = '/directDebit/v3.0/otp-verification'
        url = ':7778' + relative_url
        data = {
            "merchantID": self.merchant_id,
            "terminalID": self.terminal_id,
            "journeyID": journey_id,
            "otp": otp,
            "chargeToken": charge_token,
            "additionalInfo": {
                "otpTransactionCode": "01"
            }
        }

        return self.send_request('post', url, data, customer_id)

    def request_otp(self, customer_xid, journey_id):
        relative_url = '/directDebit/v3.0/otp'
        url = ':7778' + relative_url
        data = {
            "merchantID": self.merchant_id,
            "terminalID": self.terminal_id,
            "journeyID": journey_id,
            "additionalInfo": {
                "otpTransactionCode": "01",
                "otpReasonCode": "01",
            }
        }
        return self.send_request('post', url, data, customer_xid)

    def construct_card_data(self, card_data):
        # card_data['bankCardNo'] = card_data['bankCardNo'][:-4] + '****'
        card_data = json.dumps(card_data).replace(' ', '')
        spaces_needed = 16 - (len(card_data) % 16)
        return card_data + ' ' * spaces_needed

    def registration_bind_card(self, data, customer_xid):
        card_data = self.construct_card_data(data)
        relative_url = '/MTIDDPaymentPortal/registrationSubmitSNAP'
        url = ':9773' + relative_url
        public_key_bytes = serialization.load_pem_public_key(
            self.public_key_landing_page.encode(),
            backend=default_backend()
        )
        encrypted_card_data = public_key_bytes.encrypt(
            card_data.encode(),
            padding.PKCS1v15()
        )
        encrypted_card_data = base64.b64encode(encrypted_card_data).decode()
        data = {
            "merchantID": self.merchant_id,
            "terminalID": self.terminal_id,
            "journeyID": self.generate_external_id(customer_xid),
            "isBindAndPay": "N",
            "custIdMerchant": str(customer_xid),
            "cardData": encrypted_card_data,
            "additionalInfo": {}
        }
        data_copy = copy.deepcopy(data)
        data_copy['cardData'] = ""
        data_copy = json.dumps(data_copy).replace(' ', '')
        headers = {
            "jwt": self.token,
            "X-SIGNATURE": self.generate_signature_registration(data_copy),
            "X-PARTNER-ID": self.client_id,
            "X-EXTERNAL-ID": self.generate_external_id(customer_xid),
            "Content-Type": "application/json"
        }

        return self.send_request(
            'post', url, data, customer=customer_xid, headers=headers, is_need_journey_id=True)

    def inquiry_purchase(self, customer_xid, original_partner_reference_no, transaction_date,
                         bank_card_token):
        relative_url = '/directDebit/v3.0/debit/status'
        url = ':7778' + relative_url
        data = {
            "merchantID": self.merchant_id,
            "terminalID": self.terminal_id,
            "journeyID": self.generate_external_id(customer_xid),
            "originalPartnerReferenceNo": original_partner_reference_no,
            "transactionDate": transaction_date,
            "bankCardToken": bank_card_token
        }
        return self.send_request('post', url, data, customer_xid)


def get_bni_autodebet_client(account=None):
    return AutodebetBniClient(
        settings.AUTODEBET_BNI_BASE_URL,
        settings.AUTODEBET_BNI_CLIENT_ID,
        settings.AUTODEBET_BNI_MERCHANT_CODE,
        settings.AUTODEBET_BNI_CLIENT_SECRET,
        settings.AUTODEBET_BNI_PRIVATE_KEY,
        settings.AUTODEBET_BNI_CHANNEL_ID,
        account=account,
    )


class AutodebetBniClient(object):
    def __init__(
        self,
        base_url,
        client_id,
        merchant_code,
        client_secret,
        private_key,
        channel_id,
        account=None,
        account_payment=None,
    ):
        self.base_url = base_url
        self.client_id = client_id
        self.merchant_code = merchant_code
        self.client_secret = client_secret
        self.private_key = private_key
        self.sentry_client = get_julo_sentry_client()
        self.account = account
        self.account_payment = account_payment
        self.channel_id = channel_id
        self.token = self.get_b2b_access_token()

    def get_timestamp(self):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        return timestamp

    def generate_string_to_sign(self, http_method, relative_url, request_body=None):
        timestamp = self.get_timestamp()
        minify_json = json.dumps(request_body, separators=(',', ':')) if request_body else ""
        hashed_request_body = generate_hex_sha256(minify_json)
        string_to_sign = '{}:{}:{}:{}:{}'.format(
            http_method.upper(), relative_url, self.token, hashed_request_body, timestamp
        )
        return string_to_sign

    def generate_external_id(self):
        unique_id = uuid.uuid4()
        hashed_bytes = hashlib.sha256(str(unique_id).encode()).digest()
        unique_string = hashlib.sha256(hashed_bytes).hexdigest()
        return unique_string[:32]

    def construct_api_headers(self, request_type, request_path, data=None):
        relative_url = request_path[request_path.find('/api')]
        string_to_sign = self.generate_string_to_sign(request_type, relative_url, data)

        return {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'CHANNEL-ID': self.channel_id,
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-EXTERNAL-ID': self.generate_external_id(),
            'X-PARTNER-ID': self.merchant_code,
            'X-CLIENT-KEY': self.client_id,
        }, 'Success'

    def send_request(
        self, request_type, request_path, data=None, headers=None, is_need_external_id=False
    ):
        if data is None:
            data = {}
        if not headers:
            headers, error_message = self.construct_api_headers(request_type, request_path, data)
            if not headers:
                return None, error_message

        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "headers": headers
        }
        if data != {}:
            request_params['data'] = json.dumps(data)

        return_response = None

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error = None
            error_message = None
        except Exception as e:
            self.sentry_client.captureException()
            response = e.response
            error = str(e)
            error_message = "Failed"

            if return_response and 'responseMessage' in return_response:
                error_message = return_response['responseMessage']

        autodebet_response_logger(
            "[%s] %s" % (request_type.upper(), request_path),
            response,
            return_response,
            error,
            self.account,
            self.account_payment,
            request_params,
            "BNI",
        )

        if is_need_external_id:
            return return_response, error_message, headers['X-EXTERNAL-ID']
        return return_response, error_message

    def get_b2b_access_token(self):
        redis_client = get_redis_client()
        cached_token = redis_client.get(RedisKey.BNI_CLIENT_B2B_TOKEN)
        if cached_token:
            return cached_token

        url = '/api/v1.0/access-token/b2b'
        string_to_sign = self.client_id + '|' + self.get_timestamp()
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(), password=None, backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        headers = {
            'Content-Type': 'application/json',
            'X-TIMESTAMP': self.get_timestamp(),
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
        }
        data = {
            "grantType": "client_credentials",
            "additionalInfo": {"merchantId": self.merchant_code},
        }

        response, error = self.send_request('post', url, data, headers=headers)
        if response and response['responseCode'] == '2001000':
            redis_client.set(
                RedisKey.BNI_CLIENT_B2B_TOKEN, response['accessToken'], timedelta(seconds=3599)
            )

        if error:
            raise AutodebetException(response['responseMessage'])

        return response['accessToken']

    def get_b2b2c_access_token(self, auth_code):
        redis_client = get_redis_client()
        cached_token = redis_client.get(RedisKey.BNI_CLIENT_B2B2C_TOKEN + auth_code)
        if cached_token:
            return cached_token
        url = '/api/v1.0/access-token/b2b2c'
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(), password=None, backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        string_to_sign = self.client_id + '|' + self.get_timestamp()

        headers = {
            'Authorization': 'Bearer {}'.format(self.token),
            'Content-Type': 'application/json',
            'X-TIMESTAMP': self.get_timestamp(),
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
        }
        data = {
            "grantType": "authorization_code",
            "authCode": auth_code,
            "additionalInfo": {"merchantId": self.merchant_code},
        }

        response, error = self.send_request('post', url, data, headers=headers)
        if response and response['responseCode'] == '2002000':
            redis_client.set(
                RedisKey.BNI_CLIENT_B2B2C_TOKEN + auth_code,
                response['accessToken'],
                timedelta(seconds=3599),
            )

        if error:
            raise AutodebetException(response['responseMessage'])

        return response['accessToken']

    def get_auth(self, mobile_phone_number):
        url = '/api/v1.0/get-auth-code'
        request_type = 'get'
        data = {
            "scopes": "CARD_REGISTRATION",
            "redirectUrl": "https://julo.co.id/ayoconnect/finish",
            "state": token_hex(16),
            "merchantId": self.merchant_code,
            "lang": "ID",
            "seamlessData": json.dumps({
                "mobileNumber": mobile_phone_number,
                "bankCode": BankCodes.BNI,
            }),
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret,
                                                   self.generate_string_to_sign(request_type, url)),
            'X-EXTERNAL-ID': self.generate_external_id(),
            'X-PARTNER-ID': self.merchant_code,
            'CHANNEL-ID': self.channel_id,
        }
        query_params = urlencode(data)
        url = url + '?' + query_params
        return self.send_request(
            request_type, url, headers=headers, is_need_external_id=True
        )

    def registration_account_binding(self, auth_code):
        request_type = 'post'
        url = '/api/v1.0/registration-account-binding'
        data = {
            "partnerReferenceNo": uuid.uuid4().hex,
            "authCode": auth_code,
            "merchantId": self.merchant_code,
        }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'X-TIMESTAMP': self.get_timestamp(),
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret,
                                                   self.generate_string_to_sign(request_type, url,
                                                                                data)),
            'X-PARTNER-ID': self.merchant_code,
            'X-EXTERNAL-ID': self.generate_external_id(),
            'CHANNEL-ID': self.channel_id,
        }
        response, error = self.send_request(request_type, url, data=data, headers=headers)
        return response, error

    def registration_account_unbinding(self, public_user_id, account_token, auth_code):
        url = '/api/v1.0/registration-account-unbinding'
        data = {
            "partnerReferenceNo": self.generate_external_id(),
            "merchantId": self.merchant_code,
            "additionalInfo": {
                "publicUserId": public_user_id,
                "accountToken": account_token,
                "bankCode": AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.BNI],
            },
        }

        b2bc_token = self.get_b2b2c_access_token(auth_code)

        string_to_sign = self.generate_string_to_sign('post', url, data)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'Authorization-Customer': 'Bearer {}'.format(b2bc_token),
            'CHANNEL-ID': self.channel_id,
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-EXTERNAL-ID': self.generate_external_id(),
            'X-PARTNER-ID': self.merchant_code,
            'X-CLIENT-KEY': self.client_id,
        }

        return self.send_request('post', url, data, headers=headers, is_need_external_id=True)

    def otp_verification(
        self,
        original_partner_reference_no,
        original_reference_no,
        action,
        otp,
        bank_card_token,
        public_user_id,
        otp_token,
        auth_code,
        external_id,
    ):
        url = '/api/v1.0/otp-verification'
        data = {
            "originalPartnerReferenceNo": original_partner_reference_no,
            "originalReferenceNo": original_reference_no,
            "action": action,
            "merchantId": self.merchant_code,
            "otp": otp,
            "bankCardToken": bank_card_token,
            "additionalInfo": {
                "bankCode": AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.BNI],
                "publicUserId": public_user_id,
                "otpToken": otp_token,
            },
        }

        b2b2c_token = self.get_b2b2c_access_token(auth_code)
        string_to_sign = self.generate_string_to_sign('post', '/api/v1.0/otp-verification', data)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'Authorization-Customer': 'Bearer {}'.format(b2b2c_token),
            'CHANNEL-ID': self.channel_id,
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-EXTERNAL-ID': external_id,
            'X-PARTNER-ID': self.merchant_code,
            'X-CLIENT-KEY': self.client_id,
        }

        return self.send_request('post', url, data, headers=headers)

    def create_debit_payment_host_to_host(self, public_user_id, account_token, auth_code, amount):
        url = '/api/v1.0/debit/payment-host-to-host'
        data = {
            "partnerReferenceNo": self.generate_external_id(),
            "bankCardToken": account_token,
            "merchantId": self.merchant_code,
            "amount": {
                "value": format(amount, '.2f'),
                "currency": "IDR"
            },
            "urlParam": [
                {
                    "url": "https://julo.co.id/ayoconnect/finish",
                    "type": "PAY_RETURN",
                    "isDeepLink": "N"
                }
            ],
            "additionalInfo": {
                "publicUserId": public_user_id,
                "remarks": "JULO payment",
                "bankCode": AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.BNI],
                "otpAllowed": "N"
            }
        }

        b2bc_token = self.get_b2b2c_access_token(auth_code)
        string_to_sign = self.generate_string_to_sign('post', url, data)

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'Authorization-Customer': 'Bearer {}'.format(b2bc_token),
            'CHANNEL-ID': self.channel_id,
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-EXTERNAL-ID': self.generate_external_id(),
            'X-PARTNER-ID': self.merchant_code,
            'X-CLIENT-KEY': self.client_id
        }

        return self.send_request('post', url, data, headers=headers, is_need_external_id=True)

    def inquiry_autodebet_status(self, external_id):
        request_type = 'get'
        url = '/api/v1.0/debit/status'
        url_request = '{}?merchantId={}&XExternalId={}'.format(url, self.merchant_code, external_id)
        string_to_sign = self.generate_string_to_sign(request_type, url)

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Bearer {}'.format(self.token),
            'X-TIMESTAMP': self.get_timestamp(),
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.merchant_code,
            'X-EXTERNAL-ID': external_id,
            'CHANNEL-ID': self.channel_id,
        }
        return self.send_request(request_type, url_request, data=None, headers=headers)


def get_dana_autodebet_client(account=None, account_payment=None):
    return AutodebetDanaClient(
        settings.DANA_LINKING_CLIENT_ID,
        settings.DANA_LINKING_CLIENT_SECRET,
        settings.DANA_LINKING_API_BASE_URL,
        settings.DANA_LINKING_WEB_BASE_URL,
        settings.DANA_LINKING_MERCHANT_ID,
        settings.DANA_LINKING_CHANNEL_ID,
        settings.DANA_LINKING_PUBLIC_KEY,
        settings.DANA_LINKING_PRIVATE_KEY,
        account,
        account_payment,
    )


class AutodebetDanaClient(object):
    def __init__(
        self,
        client_id,
        client_secret,
        api_base_url,
        web_base_url,
        merchant_id,
        channel_id,
        public_key,
        private_key,
        account=None,
        account_payment=None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_base_url = api_base_url
        self.web_base_url = web_base_url
        self.merchant_id = merchant_id
        self.channel_id = channel_id
        self.public_key = public_key
        self.private_key = private_key
        self.account = account
        self.account_payment = account_payment
        self.sentry_client = get_julo_sentry_client()

    def send_request(
        self,
        request_type: str,
        request_path: str,
        data: Dict,
        headers: Dict,
        partner_reference_no: Optional[str] = None,
    ) -> Tuple:
        # importing here due to circular import
        from juloserver.autodebet.tasks import (
            send_slack_alert_dana_failed_subscription_and_deduction,
        )

        request_params = {
            "url": "%s%s" % (self.api_base_url, request_path),
            "json": data,
            "headers": headers,
        }

        return_response = None
        response = None
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

            send_slack_alert_dana_failed_subscription_and_deduction.delay(
                error_message=error_message,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment.id if self.account_payment else None,
                application_id=self.account.last_application.id if self.account else None,
                original_partner_reference_no=partner_reference_no,
            )

        logger.info(
            {
                "action": "juloserver.autodebet.clients.AutodebetDanaClient.send_request",
                "url": request_params.get("url"),
                "data": data,
                "headers": headers,
                "response": return_response,
            }
        )
        autodebet_response_logger(
            "[%s] %s" % (request_type.upper(), request_path),
            response,
            return_response,
            error_message,
            self.account,
            self.account_payment,
            request_params,
            "DANA",
        )
        return return_response, error_message

    def _generate_partner_reference_no(self, account_payment_xid):
        now = timezone.localtime(timezone.now())
        return now.strftime('%Y%m%d%H%M%S') + str(account_payment_xid)

    def _generate_string_to_sign_asymmetric(
        self, timestamp: str, data: Dict, method: str, relative_url: str
    ) -> str:
        body = json.dumps(data, separators=(',', ':'))
        encrypted_data = generate_hex_sha256(body)
        string_to_sign = '%s:%s:%s:%s' % (method.upper(), relative_url, encrypted_data, timestamp)

        return string_to_sign

    def _get_auth_token(self) -> Tuple:
        cached_token = None
        redis_client = None
        try:
            redis_client = get_redis_client()
            cached_token = redis_client.get(dana_linking_redis_key.CLIENT_AUTH_TOKEN)
        except Exception:
            self.sentry_client.captureException()
        if str(None) != cached_token and cached_token:
            return cached_token, None
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        string_to_sign = self.client_id + '|' + timestamp
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'CHANNEL-ID': self.channel_id,
            'Content-Type': 'application/json',
        }
        data = {"grantType": "client_credentials"}
        response_data, error_message = self.send_request(
            'post', '/v1.0/access-token/b2b.htm', data, headers
        )
        token = None
        if response_data and response_data.get('responseMessage') == "Successful":
            token = response_data['accessToken']
            if redis_client:
                try:
                    redis_client.set(
                        dana_linking_redis_key.CLIENT_AUTH_TOKEN,
                        token,
                        timedelta(seconds=int(response_data['expiresIn']) - 600),
                    )
                except Exception:
                    self.sentry_client.captureException()
        return token, error_message

    def _generate_external_id(self, customer_xid):
        now = timezone.localtime(timezone.now())
        return now.strftime('%Y%m%d%H%M%S') + str(customer_xid)

    def direct_debit_autodebet(
        self, access_token, device_id, customer_xid, partner_reference_no, amount, due_date
    ):
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/debit/payment-host-to-host.htm'
        data = {
            "partnerReferenceNo": partner_reference_no,
            "merchantId": self.merchant_id,
            "amount": {"value": "{}.00".format(amount), "currency": "IDR"},
            "urlParams": [
                {"url": "https://www.julo.co.id/", "type": "PAY_RETURN", "isDeeplink": "N"},
                {
                    "url": settings.BASE_URL + '/webhook/autodebet/dana/v1/payment-notification',
                    "type": "NOTIFICATION",
                    "isDeeplink": "N",
                },
            ],
            "additionalInfo": {
                "productCode": '51051000100000000031',
                "order": {
                    "orderTitle": "Pembayaran Pinjaman JULO bulan {}".format(
                        format_date(due_date, "MMM yyyy", locale='id')
                    )
                },
                "mcc": "5732",
                "envInfo": {
                    "sourcePlatform": "IPG",
                    "terminalType": "APP",
                    "orderTerminalType": "APP",
                },
                "accessToken": access_token,
            },
        }

        string_to_sign = self._generate_string_to_sign_asymmetric(
            timestamp, data, request_type, request_path
        )
        token, _ = self._get_auth_token()
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'X-DEVICE-ID': device_id,
            'Content-Type': 'application/json',
            'X-EXTERNAL-ID': self._generate_external_id(customer_xid),
            'CHANNEL-ID': self.channel_id,
            'X-PARTNER-ID': self.client_id,
            'Authorization': 'Bearer {}'.format(token),
            'Authorization-Customer': 'Bearer {}'.format(access_token),
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, partner_reference_no
        )
        return response_data, error_message

    def inquiry_autodebet_status(
        self,
        customer_xid: int,
        original_partner_reference_no: str,
        original_reference_no: str,
    ) -> tuple:
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/debit/status.htm'
        data = {
            "originalPartnerReferenceNo": original_partner_reference_no,
            "originalReferenceNo": original_reference_no,
            "serviceCode": "55",
            "merchantId": self.merchant_id,
        }

        string_to_sign = self._generate_string_to_sign_asymmetric(
            timestamp, data, request_type, request_path
        )
        token, _ = self._get_auth_token()
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'Content-Type': 'application/json',
            'X-EXTERNAL-ID': self._generate_external_id(customer_xid),
            'CHANNEL-ID': self.channel_id,
            'X-PARTNER-ID': self.client_id,
            'Authorization': 'Bearer {}'.format(token),
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, original_partner_reference_no
        )
        return response_data, error_message
