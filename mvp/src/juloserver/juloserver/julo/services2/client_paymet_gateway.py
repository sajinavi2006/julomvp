import requests
import hashlib
import pytz
import logging

from datetime import datetime
from django.conf import settings
from rest_framework import status as http_status

from juloserver.payment_gateway.services.authentications import SignatureGenerator

logger = logging.getLogger(__name__)


class ClientPaymentGateway:
    class API:
        VERIFY_BANK_ACCOUNT = '/api/payment-gateway/v1/verify-bank-account'
        TRANSFER_BANK = '/api/payment-gateway/v1/transfer'

    def __init__(self, client_id, api_key):
        self.host = settings.PAYMENT_GATEWAY_BASE_URL
        self.secret_key = settings.PG_API_SECRET_KEY
        self.client_id = client_id
        self.api_key = api_key

    def _generate_headers(self, method, path, timestamp):
        sign_data = SignatureGenerator.generate_signature(
            method=method,
            path=path,
            client_id=self.client_id,
            api_key=self.api_key,
            secret_key=self.secret_key,
            timestamp=timestamp,
        )
        api_key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()
        return {
            'AUTHORIZATION': 'api-key ' + api_key_hash,
            'SIGNATURE': sign_data['X-Signature'],
            'TIMESTAMP': timestamp,
            'CLIENT_ID': self.client_id,
        }

    def verify_bank_account(self, payload: dict) -> dict:
        """
        Sample Payload
        payload = {
            "bank_account": "1234567890",
            "bank_code": "001",
            "bank_account_name": "John Doe",
            "preferred_pg": "vendor",
        }
        """
        method = 'POST'
        path = self.API.VERIFY_BANK_ACCOUNT
        api_url = self.host + path
        datetime_now = datetime.now(tz=pytz.timezone("Asia/Jakarta")).timestamp()
        headers = self._generate_headers(
            method=method,
            path=path,
            timestamp=str(datetime_now),
        )
        try:
            response = requests.post(api_url, headers=headers, json=payload)
            result = response.json()
            if response.status_code == http_status.HTTP_200_OK:
                return result
            else:
                """
                This condition to create logger status 400, 401, 429, 500
                """
                logger.error(
                    {
                        "action": "ClientPaymentGatewayVerifyBankAccount",
                        "method": method,
                        "url": api_url,
                        "status_code": response.status_code,
                        "data": result,
                    }
                )
                return result

        except Exception as err:
            errors = {
                "action": "ClientPaymentGatewayVerifyBankAccount",
                "method": method,
                "url": api_url,
                "error": str(err),
            }
            logger.error(errors)
            raise err

    def disbursement_transfer_bank(self, loan_id, req_data) -> dict:
        resp = {
            "success": False,
        }
        path = self.API.TRANSFER_BANK
        api_url = self.host + self.API.TRANSFER_BANK
        datetime_now = datetime.now(tz=pytz.timezone("Asia/Jakarta")).timestamp()
        headers = self._generate_headers(
            method="POST",
            path=path,
            timestamp=str(datetime_now),
        )
        payload = req_data
        log_content = {
            "action": "disbursement_transfer_bank",
            "loan_id": loan_id,
            "api_url": api_url,
            "header": headers,
            "payload": payload,
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload)
            if response.status_code == http_status.HTTP_200_OK:
                resp["success"] = True
                resp["data"] = response.json()
                log_content["response_http_status"] = response.status_code
                log_content["response"] = response.json()
                logger.info(log_content)
                return resp

            else:
                resp["data"] = response.json()
                log_content["response_http_status"] = response.status_code
                log_content["response"] = response.json()
                logger.error(log_content)
                return resp

        except Exception as error:
            log_content["internal_error"] = str(error)
            logger.error(log_content)
            return resp
