import json
from typing import (
    Optional,
    Dict,
    Tuple,
)
from datetime import timedelta
import requests  # noqa
from urllib.parse import urlencode
from secrets import token_hex
from babel.dates import format_date
import datetime
import logging

from django.utils import timezone
from django.conf import settings

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.clients import autodebet_response_logger
from juloserver.dana_linking.models import DanaWalletAccount
from juloserver.integapiv1.utils import generate_signature_asymmetric
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import generate_hex_sha256

from juloserver.dana_linking.constants import RedisKey, DanaWalletAccountStatusConst

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class DanaLinkingClient(object):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_base_url: str,
        web_base_url: str,
        merchant_id: str,
        channel_id: str,
        public_key: str,
        private_key: str,
        account: Account = None,
        account_payment: AccountPayment = None,
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

    def send_request(
        self,
        request_type: str,
        request_path: str,
        data: Dict,
        headers: Dict,
        is_autodebet: bool = False,
    ) -> Tuple:
        from juloserver.autodebet.constants import AutodebetVendorConst, AutodebetStatuses
        from juloserver.autodebet.models import AutodebetAccount
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

        logger.info(
            {
                "action": "juloserver.dana_linking.clients.DanaLinkingClient.send_request",
                "url": request_params.get("url"),
                "data": data,
                "headers": headers,
                "response": return_response,
            }
        )
        if (
            error_message
            and str(error_message).lower() == 'invalid customer token'
            and self.account
        ):
            try:
                dana_wallet_account = DanaWalletAccount.objects.filter(account=self.account).last()
                if dana_wallet_account:
                    dana_wallet_account.update_safely(status=DanaWalletAccountStatusConst.DISABLED)
                _filter = {
                    "account": self.account,
                    "is_deleted_autodebet": False,
                    "vendor": AutodebetVendorConst.DANA,
                    "activation_ts__isnull": False,
                    "is_use_autodebet": True,
                }
                existing_autodebet_account = AutodebetAccount.objects.filter(**_filter)
                existing_autodebet_account.update(
                    deleted_request_ts=timezone.localtime(timezone.now()),
                    deleted_success_ts=timezone.localtime(timezone.now()),
                    is_deleted_autodebet=True,
                    is_use_autodebet=False,
                    status=AutodebetStatuses.REVOKED,
                    notes="Unlink from DANA side",
                )
                send_slack_alert_dana_failed_subscription_and_deduction.delay(
                    error_message="Unlink from DANA side by customer",
                    account_id=self.account.id,
                )

            except Exception as exe:
                logger.error(exe)
        if is_autodebet:
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

    def _generate_external_id(self, customer_xid):
        now = timezone.localtime(timezone.now())
        return now.strftime('%Y%m%d%H%M%S') + str(customer_xid)

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
            cached_token = redis_client.get(RedisKey.CLIENT_AUTH_TOKEN)
        except Exception:
            sentry_client.captureException()
        if cached_token:
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
                        RedisKey.CLIENT_AUTH_TOKEN,
                        cached_token,
                        timedelta(seconds=int(response_data['expiresIn']) - 600),
                    )
                except Exception:
                    sentry_client.captureException()
        return token, error_message

    def apply_token(
        self, grant_type: str, auth_code: Optional[str] = "", refresh_token: Optional[str] = ""
    ) -> Tuple:
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        string_to_sign = self.client_id + '|' + timestamp
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'Content-Type': 'application/json',
        }
        data = {
            "grantType": grant_type,
            "authCode": auth_code,
            "refreshToken": refresh_token,
            "additionalInfo": {},
        }
        response_data, error_message = self.send_request(
            'post', '/v1.0/access-token/b2b2c.htm', data, headers
        )
        return response_data, error_message

    def check_balance(
        self,
        access_token: str,
        device_id: str,
        customer_xid: int,
        is_autodebet: bool,
    ) -> Tuple:
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/balance-inquiry.htm'
        data = {"additionalInfo": {"accessToken": access_token}}
        string_to_sign = self._generate_string_to_sign_asymmetric(
            timestamp, data, request_type, request_path
        )
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-PARTNER-ID': self.client_id,
            'Authorization': 'Bearer {}'.format(self._get_auth_token()),
            'Authorization-customer': 'Bearer {}'.format(access_token),
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'Content-Type': 'application/json',
            'X-EXTERNAL-ID': self._generate_external_id(customer_xid),
            'X-DEVICE-ID': device_id,
            'CHANNEL-ID': self.channel_id,
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, is_autodebet
        )
        return response_data, error_message

    def construct_oauth_url(self, customer_xid: int) -> str:
        data = {
            "partnerId": self.client_id,
            "timestamp": timezone.localtime(timezone.now()).replace(microsecond=0).isoformat(),
            "externalId": self._generate_external_id(customer_xid),
            "channelId": self.channel_id,
            "scopes": "MINI_DANA,QUERY_BALANCE,PUBLIC_ID,CASHIER,AGREEMENT_PAY",
            "redirectUrl": "https://julo.co.id/dana/binding/v1/finish",
            "state": token_hex(8),
        }
        query_params = urlencode(data)
        return self.web_base_url + '/v1.0/get-auth-code?' + query_params

    def direct_debit_payment(
        self, customer_xid: int, amount: int, account_payment_xid: int, due_date: datetime
    ) -> tuple:
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/debit/payment.htm'
        data = {
            "partnerReferenceNo": self._generate_partner_reference_no(account_payment_xid),
            "merchantId": self.merchant_id,
            "amount": {"value": "{}.00".format(amount), "currency": "IDR"},
            "urlParams": [
                {"url": "https://www.julo.co.id/", "type": "PAY_RETURN", "isDeeplink": "N"},
                {
                    "url": settings.BASE_URL + '/api/dana-linking/webhook/v1/payment_notification',
                    "type": "NOTIFICATION",
                    "isDeeplink": "N",
                },
            ],
            "disabledPayMethods": "CREDIT_CARD",
            "payOptionDetails": [{"payMethod": "BALANCE", "payOption": "DANA"}],
            "additionalInfo": {
                "productCode": '51051000100000000001',
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
            },
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
        response_data, error_message = self.send_request(request_type, request_path, data, headers)
        return response_data, error_message

    def unbind_dana_account(self, access_token, device_id, customer_xid):
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/registration-account-unbinding.htm'
        data = {
            "merchantId": self.merchant_id,
            "additionalInfo": {
                "accessToken": access_token,
            }
        }
        string_to_sign = self._generate_string_to_sign_asymmetric(
            timestamp, data, request_type, request_path
        )
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self._get_auth_token()),
            'Authorization-customer': 'Bearer {}'.format(access_token),
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(customer_xid),
            'X-DEVICE-ID': device_id,
            'CHANNEL-ID': self.channel_id,
        }
        response_data, error_message = self.send_request(request_type, request_path, data, headers)
        return response_data, error_message

    def apply_ott(self, access_token, device_id, customer_xid):
        timestamp = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        request_type = 'post'
        request_path = '/v1.0/qr/apply-ott.htm'
        data = {
            "userResources": [
                "OTT"
            ],
            "additionalInfo": {
                "accessToken": access_token,
            }
        }
        string_to_sign = self._generate_string_to_sign_asymmetric(
            timestamp, data, request_type, request_path
        )
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(self._get_auth_token()),
            'Authorization-customer': 'Bearer {}'.format(access_token),
            'X-TIMESTAMP': timestamp,
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(customer_xid),
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'X-DEVICE-ID': device_id,
            'CHANNEL-ID': self.channel_id,
        }
        response_data, error_message = self.send_request(request_type, request_path, data, headers)
        return response_data, error_message
