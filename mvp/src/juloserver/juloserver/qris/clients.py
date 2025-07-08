"""
clients.py
"""
import requests

from juloserver.julo.utils import generate_guid, generate_hmac

from .exceptions import DokuApiError, DokuApiInterrupt
from .exceptions import ExpiredTokenDokuApiError
from .exceptions import EmailRegisteredDokuApiError
from .exceptions import PhoneRegisteredDokuApiError
from .exceptions import RegisteredDokuApiError


class DokuClient(object):
    def __init__(self, base_url, client_id, client_secret, shared_key, token, internal_systrace):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.shared_key = shared_key
        self.token = token
        self.internal_systrace = internal_systrace

    def post_request(self, url, data=None, json=None, **kwargs):
        """Wrapper for requests.post, matching its parameters"""
        response = requests.post(url, data=data, json=json, timeout=None, **kwargs)
        if not 200 <= response.status_code <= 299:
            raise DokuApiInterrupt(response.text)
        response = response.json()
        return response

    def get_fresh_token(self):
        url = self.base_url + 'signon'
        systrace = generate_guid()
        keystring = '{}{}{}'.format(self.client_id, self.shared_key, systrace)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "sharedKey": self.shared_key,
            "systrace": systrace,
            "words": words,
            "responseType": "JSON"
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] != "0000":
            error_message = response['responseMessage']
            raise DokuApiError(error_message, response['responseCode'])

        token = response['accessToken']
        expires_in = response['expiresIn']

        return token, expires_in, systrace

    def inquiry_qris(self, account_id, qr_code):
        url = self.base_url + "doInquiryQris"
        keystring = '{}{}{}{}'.format(
            self.client_id, account_id, self.shared_key, qr_code)
        words = generate_hmac(keystring, self.client_secret)

        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "qrCodeValue": qr_code,
            "words": words,
            "version": "3.0"
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != '0000':
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def payment_qris(self, account_id, qr_code, invoice,
                     amount, conveniences_fee=None,
                     transaction_id_qris=None):
        url = self.base_url + "doPaymentQris"
        keystring = '{}{}{}{}{}{}'.format(
            self.client_id, account_id,
            self.shared_key, self.token,
            qr_code, invoice
        )
        amount_str = '%s.00' % amount
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "words": words,
            "qrCodeValue": qr_code,
            "invoice": invoice,
            "amount": amount_str,
            "conveniencesFee": conveniences_fee,
            "transactionIdQris": transaction_id_qris,
            "version": "3.0"
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def register_customer(self, customer_name, customer_email, customer_phone=None):
        url = self.base_url + "signup"
        keystring = '{}{}{}{}'.format(
            self.client_id, self.shared_key, customer_email, self.internal_systrace
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "customerName": customer_name,
            "customerEmail": customer_email,
            "words": words,
            "version": "3.0"
        }
        if customer_phone:
            data.update({"customerPhone": customer_phone})

        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] == "2116":
            raise EmailRegisteredDokuApiError(response['responseMessage'])

        if response['responseCode'] == "2117":
            raise PhoneRegisteredDokuApiError(response['responseMessage'])

        if response['responseCode'] == "2118":
            raise RegisteredDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response['dokuId']

    def request_linking_account(self, account_id, send_by=1):
        url = self.base_url + "linkingaccount/init"
        keystring = '{}{}{}{}{}'.format(
            self.client_id, self.internal_systrace,
            self.shared_key, account_id, send_by
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "sendBy": send_by,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response['dokuId']

    def confirm_linking_account(self, account_id, otp):
        url = self.base_url + "linkingaccount/confirm"
        keystring = '{}{}{}{}{}'.format(
            self.client_id, self.internal_systrace,
            self.shared_key, account_id, otp
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "otp": otp,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response['dokuId']

    def top_up(self, account_id, amount, transaction_id):
        amount_str = '%s.00' % amount
        url = self.base_url + "cashback"
        keystring = '{}{}{}{}{}'.format(
            self.client_id, transaction_id, self.internal_systrace,
            self.shared_key, amount_str
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "accountId": account_id,
            "transactionId": transaction_id,
            "amount": amount_str,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def status_top_up(self, transaction_id):
        url = self.base_url + "checkstatustopup"
        keystring = '{}{}{}{}'.format(
            self.client_id, self.internal_systrace,
            transaction_id, self.shared_key
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "transactionId": transaction_id,
            "dpMallId": self.client_id,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def status_payment(self, transaction_id):
        url = self.base_url + "checkstatusqris"
        keystring = '{}{}{}{}{}'.format(
            self.client_id, self.internal_systrace,
            self.client_id, transaction_id, self.shared_key
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "transactionId": transaction_id,
            "dpMallId": self.client_id,
            "words": words,
            "version": "3.0"
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def void_top_up(self, transaction_id):
        url = self.base_url + "reverse_cashback"
        keystring = '{}{}{}'.format(
            self.client_id, transaction_id, self.shared_key
        )
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "transactionId": transaction_id,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response

    def check_balance(self):
        url = self.base_url + 'corporatesourceoffunds'
        keystring = '{}{}{}'.format(self.client_id, self.internal_systrace, self.shared_key)
        words = generate_hmac(keystring, self.client_secret)
        data = {
            "clientId": self.client_id,
            "accessToken": self.token,
            "words": words,
        }
        response = self.post_request(url, data=data)

        if response['responseCode'] in ["3009", "3010"]:
            raise ExpiredTokenDokuApiError(response['responseMessage'])

        if response['responseCode'] != "0000":
            raise DokuApiError(response['responseMessage'], response['responseCode'])

        return response
