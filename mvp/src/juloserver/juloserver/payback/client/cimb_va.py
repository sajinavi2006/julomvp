import json
import requests
import logging
import uuid

from django.conf import settings
from django.utils import timezone

from datetime import timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from juloserver.payback.constants import (
    RedisKey,
    CimbVAConst,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import (
    wrap_sha512_with_base64,
    generate_sha256_rsa,
    generate_hex_sha256,
)


logger = logging.getLogger(__name__)


def cimb_response_logger(
    account, request_type, request_path, request_params, response, errors, error_message
):
    logger.info(
        {
            'action': 'cimb_response_logger - {}'.format(request_type),
            'account_id': account.id,
            'error_message': error_message,
            'request_path': request_path,
            'request': json.dumps(request_params),
            'response': response,
            'error': errors,
        }
    )



def get_cimb_snap_client(account):
    return CimbSnapClient(
        account,
        settings.CIMB_SNAP_CLIENT_KEY,
        settings.CIMB_SNAP_CLIENT_SECRET,
        settings.CIMB_SNAP_PRIVATE_KEY,
        settings.CIMB_SNAP_BASE_URL,
    )


def get_environment_flag():
    setting_env = settings.ENVIRONMENT
    if setting_env == 'prod':
        return 'production'
    return 'alpha'


class CimbSnapClient(object):
    def __init__(self, account, client_key, client_secret, private_key, base_url):
        self.account = account
        self.client_key = client_key
        self.client_secret = client_secret
        self.private_key = private_key
        self.base_url = base_url
        self.sentry_client = get_julo_sentry_client()
        self.environment = get_environment_flag()

    def generate_customer_no(self, va_number):
        prefix = CimbVAConst.PARTNER_SERVICE_ID
        if va_number.startswith(prefix):
            return va_number[len(prefix) :]
        return va_number

    def _get_x_timestamp(self):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        return timestamp

    def _get_string_to_sign(self, http_method, relative_url, request_body, token, x_timestamp):
        minify_json = json.dumps(request_body, separators=(',', ':'))
        hashed_request_body = generate_hex_sha256(minify_json)
        string_to_sign = '{}:{}:{}:{}:{}'.format(
            http_method.upper(), relative_url, token, hashed_request_body, x_timestamp
        )
        return string_to_sign

    def _get_string_to_sign_b2b(self, x_timestamp):
        return self.client_key + '|' + x_timestamp

    def _get_private_key_bytes(self):
        private_key_bytes = serialization.load_pem_private_key(
            self.private_key.encode(), password=None, backend=default_backend()
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return private_key_bytes

    def _get_signature(self, http_method, relative_url, token, request_body, x_timestamp):
        string_to_sign = self._get_string_to_sign(
            http_method, relative_url, request_body, token, x_timestamp
        )
        return wrap_sha512_with_base64(self.client_secret, string_to_sign)

    def _get_signature_b2b(self, x_timestamp):
        string_to_sign = self._get_string_to_sign_b2b(x_timestamp)
        private_key_bytes = self._get_private_key_bytes()
        return generate_sha256_rsa(private_key_bytes, string_to_sign)

    def _request_auth_token(self):
        x_timestamp = self._get_x_timestamp()
        redis_client = get_redis_client()
        cached_token = redis_client.get(RedisKey.CIMB_CLIENT_AUTH_TOKEN)
        error_message = None

        relative_url = "/api-manager-external/{}/v1.0/access-token/b2b".format(self.environment)

        if not cached_token:
            auth_token_response, error_message = self.send_request(
                "post",
                relative_url,
                {"grantType": "client_credentials"},
                headers={
                    "Content-type": "application/json",
                    "X-TIMESTAMP": x_timestamp,
                    "X-CLIENT-KEY": self.client_key,
                    "X-SIGNATURE": self._get_signature_b2b(x_timestamp),
                },
            )

            if not error_message:
                cached_token = auth_token_response['accessToken']
                redis_client.set(
                    RedisKey.CIMB_CLIENT_AUTH_TOKEN,
                    cached_token,
                    timedelta(seconds=int(auth_token_response['expiresIn'])),
                )

        return cached_token, error_message

    def _construct_api_headers(self, http_method, relative_url, request_body, x_timestamp):
        access_token, error_message = self._request_auth_token()

        if error_message:
            return None, error_message

        return {
            "Content-type": "application/json",
            "Authorization": "Bearer %s" % access_token,
            "X-TIMESTAMP": x_timestamp,
            "X-SIGNATURE": self._get_signature(
                http_method, relative_url, access_token, request_body, x_timestamp
            ),
            "X-EXTERNAL-ID": self.generate_external_id(),
            "CHANNEL-ID": CimbVAConst.CHANNEL_ID,
            "X-PARTNER-ID": self.client_key,
        }, None

    def generate_external_id(self):
        return str(uuid.uuid4())

    def send_request(self, request_type, request_path, data, headers=None):

        x_timestamp = self._get_x_timestamp()
        if not headers:
            headers, error_message = self._construct_api_headers(
                http_method=request_type,
                relative_url=request_path,
                request_body=data,
                x_timestamp=x_timestamp,
            )
            if error_message:
                return None, error_message

        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "data": json.dumps(data),
            "headers": headers,
        }

        return_response = None
        errors = None
        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            return_response = response.json()
            response.raise_for_status()
            error_message = None
        except Exception as e:
            self.sentry_client.captureException()
            errors = str(e)
            response = e.response

            error_message = ""
            if return_response and 'httpCode' in return_response:
                error_message = "[%s]" % return_response['httpCode']
            if return_response and 'httpMessage' in return_response:
                error_message = "%s %s" % (error_message, return_response['httpMessage'])
            if error_message == "":
                error_message = "Failed"

        cimb_response_logger(
            self.account,
            request_type,
            request_path,
            request_params,
            return_response,
            errors,
            error_message,
        )

        return return_response, error_message

    def get_payment_status(self, va_number, transaction_id):
        relative_url = "/api-manager-external/{}/v1.0/transfer-va/status".format(self.environment)
        data = {
            "partnerServiceId": "% 8s" % CimbVAConst.PARTNER_SERVICE_ID,
            "virtualAccountNo": va_number,
            "inquiryRequestId": transaction_id,
            "paymentRequestId": transaction_id,
            "customerNo": self.generate_customer_no(va_number),
        }
        return self.send_request("post", relative_url, data)
