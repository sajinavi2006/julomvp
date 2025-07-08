import logging

from django.conf import settings
import requests  # noqa

from juloserver.julo.utils import generate_sha1_md5
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.ovo.constants import (
    OvoUrl,
    OvoConst,
)
import copy

logger = logging.getLogger(__name__)


def get_ovo_client():
    return OvoClient(
        settings.FASPAY_API_BASE_URL,
    )


class OvoClient(object):
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
                    logger.error({
                        'action': 'juloserver.ovo.clients.send_request',
                        'error': error_message,
                        'data': data,
                        'request_path': request_params['url']
                    })
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

            logger.error({
                'action': 'juloserver.ovo.clients.send_request',
                'error': response,
                'data': data,
                'request_path': request_params['url']
            })

        return return_response, error_message

    def create_transaction_data(self, transaction_data):
        # need multiply by 100 because 3rd party need it.
        transaction_data_temp = copy.deepcopy(transaction_data)
        transaction_data_temp['bill_total'] *= 100
        return self.send_request('post', OvoUrl.CREATE_TRANSACTION_DATA, transaction_data_temp)

    def push_to_pay(self, transaction_data):
        return self.send_request('post', OvoUrl.PUSH_TO_PAY, payload=transaction_data)

    def inquiry_payment_status(self, transaction_id, account_payment_xid):
        faspay_user_id = settings.FASPAY_USER_ID
        faspay_password = settings.FASPAY_PASSWORD
        signature_keystring = '{}{}{}'.format(
            faspay_user_id, faspay_password, account_payment_xid)
        julo_signature = generate_sha1_md5(signature_keystring)
        transaction_data = {
            'request': "Inquiry Payment Status",
            'trx_id': transaction_id,
            'merchant_id': OvoConst.MERCHANT_ID,
            'bill_no': account_payment_xid,
            'signature': julo_signature
        }

        return self.send_request('post', OvoUrl.INQUIRY_PAYMENT_STATUS, transaction_data)
