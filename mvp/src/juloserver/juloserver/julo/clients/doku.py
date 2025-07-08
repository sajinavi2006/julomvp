import hashlib
import json
import logging
import requests  # noqa
import uuid
import pytz
from datetime import timedelta
from django.utils import timezone
from typing import Dict, Optional, Tuple
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import generate_hex_sha256, generate_sha256_rsa, wrap_sha512_with_base64
from juloserver.julo.clients.constants import RedisKey, DOKUSnapResponseCode
from juloserver.ovo.models import OvoWalletAccount
from juloserver.ovo.constants import OvoWalletAccountStatusConst
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.clients import autodebet_response_logger
from juloserver.payback.tasks import store_payback_api_log

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class DokuClientException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class DokuSnapClient(object):
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        private_key: str,
        account: Account = None,
        account_payment: AccountPayment = None,
        customer_id: int = None,
        loan_id: int = None,
        payback_transaction_id: int = None,
    ):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.private_key = private_key
        self.access_token, _ = self._get_access_token()
        self.account = account
        self.account_payment = account_payment
        self.customer_id = customer_id
        self.loan_id = loan_id
        self.payback_transaction_id = payback_transaction_id

    def send_request(
        self,
        request_type: str,
        request_path: str,
        data: Dict,
        headers: Dict,
        is_autodebet: bool = False,
        is_store_payback_log: bool = False,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
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
                "action": "juloserver.julo.clients.DokuSnapClient.send_request",
                "url": request_params.get("url"),
                "data": data,
                "headers": headers,
                "response": return_response,
            }
        )

        if is_autodebet:
            autodebet_response_logger(
                "[%s] %s" % (request_type.upper(), request_path),
                response,
                return_response,
                error_message,
                self.account,
                self.account_payment,
                request_params,
                "OVO",
            )

        if is_store_payback_log:
            store_payback_api_log.delay(
                url="[%s] %s" % (request_type.upper(), request_path),
                request_params=data,
                vendor="doku",
                response=response,
                return_response=return_response,
                customer_id=self.customer_id,
                loan_id=self.loan_id,
                account_payment_id=self.account_payment.id if self.account_payment else None,
                payback_transaction_id=self.payback_transaction_id,
                error_message=error_message,
                header=headers,
            )

        return return_response, error_message

    def _get_access_token(self) -> Tuple[Optional[str], Optional[str]]:
        cached_token = None
        redis_client = None

        try:
            redis_client = get_redis_client()
            cached_token = redis_client.get(RedisKey.DOKU_CLIENT_ACCESS_TOKEN)
        except:
            sentry_client.captureException()
        if cached_token:
            return cached_token, None

        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        string_to_sign = self.client_id + '|' + timestamp
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(), password=None, backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
            'Content-Type': 'application/json',
        }
        data = {"grantType": "client_credentials"}
        response_data, error_message = self.send_request(
            'post', '/authorization/v1/access-token/b2b', data, headers
        )

        access_token = None
        if (
            response_data
            and response_data.get('responseCode') == DOKUSnapResponseCode.SUCCESS_B2B_TOKEN
        ):
            access_token = response_data['accessToken']
            if redis_client:
                try:
                    redis_client.set(
                        RedisKey.DOKU_CLIENT_ACCESS_TOKEN,
                        access_token,
                        timedelta(seconds=int(response_data['expiresIn']) - 600),
                    )
                except Exception:
                    sentry_client.captureException()
        return access_token, error_message

    def _generate_string_to_sign(
        self,
        http_method: str,
        relative_url: str,
        request_body: Dict,
    ):
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        minify_json = json.dumps(request_body, separators=(',', ':'))
        hashed_request_body = generate_hex_sha256(minify_json)
        string_to_sign = '{}:{}:{}:{}:{}'.format(
            http_method.upper(), relative_url, self.access_token, hashed_request_body, timestamp
        )
        return string_to_sign

    def _generate_external_id(self, customer_xid: str) -> str:
        unique_id = uuid.uuid4()
        hashed_bytes = hashlib.sha256(str(unique_id).encode()).digest()
        unique_int = int.from_bytes(hashed_bytes, byteorder='big')
        return str(unique_int)[:36]

    def inquiry_status(
        self,
        partner_service_id: str,
        customer_no: str,
        virtual_account_no: str,
        transaction_id: str,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        request_type = 'post'
        request_path = '/orders/v1.0/transfer-va/status'
        total_spaces = len(partner_service_id.rjust(8)) - len(partner_service_id)
        data = {
            "partnerServiceId": partner_service_id.rjust(total_spaces + len(partner_service_id)),
            "customerNo": customer_no,
            "virtualAccountNo": virtual_account_no.rjust(total_spaces + len(virtual_account_no)),
            "inquiryRequestId": transaction_id,
            "additionalInfo": {},
        }
        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(customer_no),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json',
        }

        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, is_store_payback_log=True
        )

        return response_data, error_message


class DokuSnapOvoClient(DokuSnapClient):
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        private_key: str,
        ovo_wallet_account: OvoWalletAccount = None,
        account: Account = None,
        account_payment: AccountPayment = None,
        is_autodebet: bool = False,
    ):
        DokuSnapClient.__init__(
            self, base_url, client_id, client_secret, private_key, account, account_payment
        )
        self.ovo_wallet_account = ovo_wallet_account
        self.account = account
        self.account_payment_id = account_payment.id if account_payment else None
        self.is_autodebet = is_autodebet

    # OVO TOKENIZATION DIRECT DEBIT
    def ovo_registration_binding(self, body: Dict):
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        request_type = 'post'
        request_path = '/direct-debit/core/v1/registration-account-binding'

        data = {
            "phoneNo": body['phone_number'],
            "additionalInfo": {
                "channel": "EMONEY_OVO_SNAP",
                "custIdMerchant": body['customer_xid'],
                "successRegistrationUrl": body['success_url'],
                "failedRegistrationUrl": body['failed_url'],
            },
        }
        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(body['customer_xid']),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json',
        }

        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment_id,
                is_autodebet=self.is_autodebet,
            )

        return response_data, error_message

    def _get_b2b2c_access_token(self) -> Tuple[Optional[str], Optional[str]]:
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        from juloserver.autodebet.constants import AutodebetVendorConst, AutodebetStatuses
        from juloserver.autodebet.models import AutodebetAccount
        from juloserver.account.models import Account
        if not self.ovo_wallet_account:
            raise DokuClientException("OvoWalletAccount not found")

        # NEED TO ALWAYS HIT B2B2C TO CHECK UNLINKED FROM OVO APP
        # if (
        #     self.ovo_wallet_account.access_token
        #     and self.ovo_wallet_account.access_token_expiry_time
        #     > timezone.localtime(timezone.now())
        # ):
        #     return self.ovo_wallet_account.access_token

        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        string_to_sign = self.client_id + '|' + timestamp
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(), password=None, backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        headers = {
            'X-TIMESTAMP': timestamp,
            'X-CLIENT-KEY': self.client_id,
            'X-SIGNATURE': generate_sha256_rsa(private_key_bytes, string_to_sign),
            'Content-Type': 'application/json',
        }
        data = {
            "grantType": "authorization_code",
            "authCode": self.ovo_wallet_account.auth_code,
            "additionalInfo": {},
        }
        request_path = '/authorization/v1/access-token/b2b2c'
        response_data, error_message = self.send_request(
            'post', request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                is_autodebet=self.is_autodebet,
            )

        if response_data and response_data.get('responseCode') == "2007400":
            self.ovo_wallet_account.access_token = response_data['accessToken']
            self.ovo_wallet_account.access_token_expiry_time = response_data[
                'accessTokenExpiryTime'
            ]
            self.ovo_wallet_account.refresh_token = response_data['refreshToken']
            self.ovo_wallet_account.refresh_token_expiry_time = response_data[
                'refreshTokenExpiryTime'
            ]
            self.ovo_wallet_account.save()

            return response_data['accessToken']
        elif response_data and response_data.get('responseCode') == "4017400":
            self.ovo_wallet_account.status = OvoWalletAccountStatusConst.DISABLED
            self.ovo_wallet_account.save()
            account_object = Account.objects.filter(
                id=self.ovo_wallet_account.account_id
            ).last()
            _filter = {
                "account": account_object,
                "is_deleted_autodebet": False,
                "vendor": AutodebetVendorConst.OVO,
                "activation_ts__isnull": False,
                "is_use_autodebet": True,
            }
            existing_autodebet_account = AutodebetAccount.objects.filter(**_filter)
            if existing_autodebet_account:
                existing_autodebet_account.update(
                    deleted_request_ts=timezone.localtime(timezone.now()),
                    deleted_success_ts=timezone.localtime(timezone.now()),
                    is_deleted_autodebet=True,
                    is_use_autodebet=False,
                    status=AutodebetStatuses.REVOKED,
                    notes="Doku response 4017400",
                )

        return None

    def balance_inquiry(self):
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        if not self.ovo_wallet_account:
            raise DokuClientException("OvoWalletAccount not found")

        b2b2c_access_token = self._get_b2b2c_access_token()
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        request_type = 'post'
        request_path = '/direct-debit/core/v1/balance-inquiry'

        data = {
            "additionalInfo": {
                "channel": "EMONEY_OVO_SNAP",
            }
        }
        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(""),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Authorization-customer': 'Bearer {}'.format(b2b2c_access_token),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json',
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment_id,
                is_autodebet=self.is_autodebet,
            )

        return response_data, error_message

    def generate_reference_no(self):
        unique_id = uuid.uuid4()
        hashed_bytes = hashlib.sha256(str(unique_id).encode()).digest()
        unique_string = hashlib.sha256(hashed_bytes).hexdigest()
        return unique_string[:32]

    def payment(self, body: Dict):
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        if not self.ovo_wallet_account:
            raise DokuClientException("OvoWalletAccount not found")

        b2b2c_access_token = self._get_b2b2c_access_token()
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        request_type = 'post'
        request_path = '/direct-debit/core/v1/debit/payment-host-to-host'

        data = {
            "partnerReferenceNo": body["partner_reference_number"],
            "amount": {
                "value": "{}.00".format(str(body["amount"])),
                "currency": "IDR",
            },
            "additionalInfo": {
                "channel": "EMONEY_OVO_SNAP",
                "successPaymentUrl": body["success_url"],
                "failedPaymentUrl": body["failed_url"],
                "paymentType": body['payment_type'],
            },
            "payOptionDetails": [
                {
                    "payMethod": "CASH",
                    "transAmount": {
                        "value": "{}.00".format(str(body["amount"])),
                        "currency": "IDR",
                    },
                    "feeAmount": {"value": "0.00", "currency": "IDR"},
                }
            ],
        }
        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)
        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(""),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Authorization-customer': 'Bearer {}'.format(b2b2c_access_token),
            'Content-Type': 'application/json',
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment_id,
                is_autodebet=self.is_autodebet,
            )
        return response_data, error_message

    def ovo_unbinding(self):
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        request_type = 'post'
        request_path = '/direct-debit/core/v1/registration-account-unbinding'
        b2b2c_access_token = self._get_b2b2c_access_token()
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        data = {"tokenId": b2b2c_access_token, "additionalInfo": {"channel": "EMONEY_OVO_SNAP"}}

        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)

        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(""),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json',
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment_id,
                is_autodebet=self.is_autodebet,
            )
        return response_data, error_message

    def ovo_inquiry_payment(self, partner_reference_no, amount, reference_no=None):
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        request_type = 'post'
        request_path = '/orders/v1.0/debit/status'
        timestamp = timezone.now().astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        data = {
            "originalPartnerReferenceNo": partner_reference_no,
            "originalReferenceNo": reference_no,
            "serviceCode": "54",
            "amount": {"value": str(amount) + ".00", "currency": "IDR"},
            "merchantId": self.client_id,
        }
        string_to_sign = self._generate_string_to_sign(request_type, request_path, data)

        headers = {
            'X-TIMESTAMP': timestamp,
            'X-SIGNATURE': wrap_sha512_with_base64(self.client_secret, string_to_sign),
            'X-PARTNER-ID': self.client_id,
            'X-EXTERNAL-ID': self._generate_external_id(""),
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Content-Type': 'application/json',
        }
        response_data, error_message = self.send_request(
            request_type, request_path, data, headers, self.is_autodebet
        )
        if error_message:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=error_message,
                topic=request_path,
                account_id=self.account.id if self.account else None,
                account_payment_id=self.account_payment_id,
                is_autodebet=self.is_autodebet,
            )
        return response_data, error_message
