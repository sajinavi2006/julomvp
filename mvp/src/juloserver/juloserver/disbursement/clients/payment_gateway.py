import base64
import hashlib
import hmac
import logging
import requests
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.disbursement.exceptions import (
    PaymentGatewayApiError,
    PaymentGatewayAPIInternalError,
)

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class Vendor:
    DOKU = "doku"


@dataclass
class TransferResponse:
    transaction_id: int
    object_transfer_id: str
    object_transfer_type: str
    transaction_date: str
    status: str
    amount: str
    bank_id: int
    bank_account: str
    bank_account_name: str
    bank_code: str
    preferred_pg: str
    message: Optional[str]
    can_retry: bool


@dataclass
class InquiryResponse:
    bank_id: int
    bank_account: str
    bank_account_name: str
    bank_code: str
    preferred_pg: str
    validation_result: Dict[str, Any]


class PaymentGatewayClient:
    API_ENDPOINTS = {
        'validate_bank_account': '/api/payment-gateway/v1/verify-bank-account',
        'transfer': '/api/payment-gateway/v1/transfer',
        'get_transfer_detail': '/api/payment-gateway/v1/transfer',
    }

    def __init__(self, base_url: str, client_id: str, secret_key: str, api_key):
        """
        Initialize the Payment Gateway client.

        Args:
            base_url: Base URL of the API
            client_id: Client ID for authentication
            secret_key: Secret key for HMAC authentication
        """
        self.base_url = base_url
        self.client_id = client_id
        self.secret_key = secret_key
        self.api_key = api_key

    def _generate_signature(self, method: str, path: str, timestamp: float) -> dict:
        """
        Generate headers with HMAC signature

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path
            client_id: Client ID
            api_key: API key
            secret_key: Secret key for signing

        Returns:
            dict: Headers to include in the request
        """
        api_key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()
        string_to_sign = f"{method.upper()}{path}{self.client_id}{api_key_hash}{timestamp}"
        h = hmac.new(self.secret_key.encode(), string_to_sign.encode(), hashlib.sha256)
        signature = base64.b64encode(h.digest()).decode()

        return {'signature': signature, 'api_key_hash': api_key_hash}

    def _make_request(self, method: str, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make an authenticated request to the API."""
        url = f"{self.base_url}{path}"

        # Generate signature
        timestamp = time.time()
        signature_data = self._generate_signature(method, path, timestamp)

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Api-Key ' + signature_data['api_key_hash'],
            'signature': signature_data['signature'],
            'client_id': self.client_id,
            'timestamp': str(timestamp),
        }

        error = None
        is_error = False

        logger.info(
            'start_payment_gateway_client_request|'
            'path={}, method={}, data={}'.format(path, method, data)
        )
        try:
            response = requests.request(method=method, url=url, json=data, headers=headers)
            status_code, response_json = response.status_code, response.json()
        except Exception as e:
            logger.exception('payment_gateway_client_make_request_exception|error={}'.format(e))
            sentry_client.captureException()
            error = PaymentGatewayApiError('PaymentGatewayClient uncaught exception!')
            return {'response': None, 'error': error, 'is_error': True}

        if HTTP_400_BAD_REQUEST <= status_code < HTTP_500_INTERNAL_SERVER_ERROR:
            error = PaymentGatewayAPIInternalError('internal error', http_code=status_code)
            is_error = True
        elif HTTP_500_INTERNAL_SERVER_ERROR <= status_code:
            error = PaymentGatewayApiError('gateway service error', http_code=status_code)
            is_error = True

        logger.info(
            'finish_payment_gateway_client_request|'
            'path={}, method={}, data={}, error={}, status_code={}, response={}'.format(
                path, method, data, error, status_code, response_json
            )
        )

        return {'response': response_json, 'error': error, 'is_error': is_error}

    def validate_bank_account(
        self,
        bank_account: str,
        bank_id: int,
        bank_account_name: str,
        preferred_pg: str = '',
    ) -> Dict[str, Any]:
        """
        Validate bank account details.

        Args:
            bank_account: Bank account number
            bank_id: internal Bank id
            bank_account_name: Name of the account holder
            preferred_pg: Preferred payment gateway (default: DOKU)

        Returns:
            BankInquiryResponse object containing validation results
        """
        data = {
            "bank_account": bank_account,
            "bank_id": bank_id,
            "bank_account_name": bank_account_name,
        }
        if preferred_pg:
            data['preferred_pg'] = preferred_pg

        response = self._make_request('POST', self.API_ENDPOINTS['validate_bank_account'], data)
        if not response['is_error']:
            response['response'] = InquiryResponse(**response['response']['data'])

        return response

    def create_disbursement(
        self,
        bank_account: str,
        bank_id: int,
        bank_account_name: str,
        object_transfer_id: str,
        object_transfer_type: str,
        amount: str,
        callback_url: str,
        preferred_pg: str = '',
    ) -> Dict[str, Any]:
        """
        Create a bank transfer.

        Args:
            bank_account: Bank account number
            bank_id: internal Bank id
            bank_account_name: Name of the account holder
            object_transfer_id: Transfer ID
            object_transfer_type: Type of transfer
            amount: Transfer amount
            callback_url: URL for transfer status callbacks
            preferred_pg: Preferred payment gateway (default: DOKU)

        Returns:
            TransferResponse object containing transfer details
        """
        data = {
            "bank_account": bank_account,
            "bank_id": bank_id,
            "bank_account_name": bank_account_name,
            "object_transfer_id": object_transfer_id,
            "object_transfer_type": object_transfer_type,
            "amount": amount,
            "callback_url": callback_url,
        }
        if preferred_pg:
            data['preferred_pg'] = preferred_pg

        response = self._make_request('POST', self.API_ENDPOINTS['transfer'], data)
        if not response['is_error']:
            response['response'] = TransferResponse(**response['response']['data'])

        return response

    def get_transfer_status(
        self,
        preferred_pg: str,
        object_transfer_id: Optional[str] = None,
        object_transfer_type: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get the status of a transfer.

        Args:
            preferred_pg: Preferred payment gateway
            object_transfer_id: Optional transfer ID
            object_transfer_type: Optional transfer type
            transaction_id: Optional transaction ID

        Returns:
            List of TransferResponse objects containing transfer status
        """
        params = {"preferred_pg": preferred_pg}

        if object_transfer_id:
            params["object_transfer_id"] = object_transfer_id
        if object_transfer_type:
            params["object_transfer_type"] = object_transfer_type
        if transaction_id:
            params["transaction_id"] = transaction_id

        response = self._make_request('GET', self.API_ENDPOINTS['get_transfer_detail'], params)
        if not response['is_error']:
            response['response'] = [
                TransferResponse(**transfer) for transfer in response['response']['data']
            ]

        return response
