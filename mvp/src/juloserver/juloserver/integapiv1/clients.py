import copy
import hashlib
import json
import logging
import uuid

from django.conf import settings
import requests  # noqa
from django.utils import timezone

from juloserver.integapiv1.constants import (
    FaspayUrl,
    FaspayPaymentChannelCode,
)
from juloserver.integapiv1.utils import generate_signature_asymmetric
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import generate_hex_sha256

logger = logging.getLogger(__name__)


def get_faspay_client():
    return FaspayClient(
        settings.FASPAY_API_BASE_URL,
    )


class FaspayClient(object):
    def __init__(self, base_url):
        self.base_url = base_url
        self.sentry_client = get_julo_sentry_client()

    def send_request(self, request_type, request_path, data=None, payload=None):
        request_params = {
            'url': "%s%s" % (self.base_url, request_path),
            'json': data,
            'data': payload,
        }

        return_response = None
        error_message = None

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            try:
                return_response = response.json()
                if return_response and 'errors' in return_response:
                    if len(return_response['errors']) > 0:
                        error_message = return_response['errors'][0]
                        return_response = None
                elif return_response and 'response_error' in return_response:
                    if return_response['response_error']:
                        error_message = return_response['response_error']['response_desc']
                        return_response = None
                elif return_response and 'response_code' in return_response:
                    if return_response['response_code'] != "00":
                        error_message = return_response['response_desc']
                        return_response = None

                if not return_response:
                    logger.error(
                        {
                            'action': 'juloserver.integapiv1.clients.send_request',
                            'error': error_message,
                            'data': data,
                            'request_path': request_params['url'],
                        }
                    )
            except ValueError:
                error_message = response.text
            response.raise_for_status()
        except Exception as e:
            self.sentry_client.captureException()
            response = str(e)
            exception_type = type(e).__name__

            if not error_message:
                error_message = response

            if exception_type == 'ReadTimeout':
                error_message = exception_type

            logger.error(
                {
                    'action': 'juloserver.integapiv1.clients.send_request',
                    'error': response,
                    'data': data,
                    'request_path': request_params['url'],
                }
            )

        return return_response, error_message

    def create_transaction_data(self, transaction_data):
        # need multiply by 100 because 3rd party need it.
        transaction_data_temp = copy.deepcopy(transaction_data)
        transaction_data_temp['bill_total'] *= 100
        return self.send_request('post', FaspayUrl.CREATE_TRANSACTION_DATA, transaction_data_temp)

    def update_transaction_data(self, transaction_data):
        # need multiply by 100 because 3rd party need it.
        transaction_data_temp = copy.deepcopy(transaction_data)
        transaction_data_temp['bill_total'] *= 100
        return self.send_request('post', FaspayUrl.UPDATE_TRANSACTION_DATA, transaction_data_temp)


def get_faspay_snap_client(merchant_id: str = None):
    if merchant_id is None:
        merchant_id = settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID

    return FaspaySnapClient(
        settings.FASPAY_SNAP_OUTBOUND_BASE_URL,
        settings.FASPAY_SNAP_OUTBOUND_CHANNEL_ID,
        merchant_id,
        settings.FASPAY_SNAP_OUTBOUND_PRIVATE_KEY,
    )


class FaspaySnapClient(object):
    def __init__(self, base_url, channel_id, merchant_id, private_key):
        self.base_url = base_url
        self.channel_id = channel_id
        self.merchant_id = merchant_id
        self.private_key = private_key
        self.sentry_client = get_julo_sentry_client()

    def get_timestamp(self):
        now = timezone.localtime(timezone.now())
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'
        return timestamp

    def generate_string_to_sign(self, http_method, relative_url, request_body=None):
        timestamp = self.get_timestamp()
        minify_json = json.dumps(request_body, separators=(',', ':')) if request_body else ""
        hashed_request_body = generate_hex_sha256(minify_json)
        string_to_sign = '{}:{}:{}:{}'.format(
            http_method.upper(), relative_url, hashed_request_body, timestamp
        )
        return string_to_sign

    def generate_external_id(self):
        unique_id = uuid.uuid4()
        hashed_bytes = hashlib.sha256(str(unique_id).encode()).digest()
        unique_int = int.from_bytes(hashed_bytes, byteorder='big')
        return str(unique_int)[:36]

    def construct_api_headers(self, request_type, request_path, data=None):
        relative_url = request_path[request_path.find('/v1.0'):]
        string_to_sign = self.generate_string_to_sign(request_type, relative_url, data)

        return {
            'Content-Type': 'application/json',
            'CHANNEL-ID': self.channel_id,
            'X-TIMESTAMP': self.get_timestamp(),
            'X-SIGNATURE': generate_signature_asymmetric(self.private_key, string_to_sign),
            'X-EXTERNAL-ID': self.generate_external_id(),
            'X-PARTNER-ID': self.merchant_id,
        }, 'Success'

    def send_request(self, request_type, request_path, data=None, headers=None):
        if data is None:
            data = {}
        if not headers:
            headers, error_message = self.construct_api_headers(request_type, request_path, data)
            if not headers:
                return None, error_message

        request_params = {"url": "%s%s" % (self.base_url, request_path), "headers": headers}
        if data != {}:
            request_params['data'] = json.dumps(data)

        return_response = None
        error_message = None
        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            try:
                return_response = response.json()
            except ValueError:
                error_message = response.text
            response.raise_for_status()
        except Exception as e:
            self.sentry_client.captureException()
            error_message = str(e)

            if return_response and 'responseMessage' in return_response:
                error_message = return_response['responseMessage']

        logger.info(
            {
                "action": "juloserver.julo.clients.FaspaySnapClient.send_request",
                "url": request_params.get("url"),
                "data": data,
                "headers": headers,
                "response": return_response,
            }
        )

        return return_response, error_message

    def inquiry_status(
        self,
        customer_no,
        virtual_account,
        channel_code,
        payment_method_code,
        transaction_id,
        inquiry_request_id,
    ):
        url = '/v1.0/transfer-va/status'
        data = {
            "partnerServiceId": payment_method_code.rjust(8),
            "customerNo": customer_no,
            "virtualAccountNo": virtual_account,
            "additionalInfo": {"channelCode": channel_code},
        }

        if inquiry_request_id:
            data["inquiryRequestId"] = inquiry_request_id
        else:
            data["additionalInfo"]["trxId"] = transaction_id

        spaces_count = len(data["partnerServiceId"]) - len(data["partnerServiceId"].strip())
        data["customerNo"] = data["customerNo"].rjust(len(data["customerNo"]) + spaces_count)
        if channel_code == FaspayPaymentChannelCode.BNI:
            data["additionalInfo"]["trxId"] = virtual_account

        return self.send_request('post', url, data)
    
    def create_transaction_va_data(self, transaction_data):
        url = '/v1.0/transfer-va/create-va'
        return self.send_request('post', url, transaction_data)
