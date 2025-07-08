from builtins import str
from builtins import object
import logging
import requests
import json
import datetime

from requests.auth import HTTPBasicAuth

from ..utils import encrypt_order_id_sepulsa
from . import get_julo_email_client
from ...monitors.notifications import notify_sepulsa_product_closed

from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_sentry_client, get_julo_sepulsa_client

from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    SepulsaMessage,
    SepulsaHTTPRequestType,
)
from juloserver.payment_point.exceptions import SepulsaException
from juloserver.payment_point.utils import string_payment_period
from requests.exceptions import ReadTimeout, ConnectionError

logger = logging.getLogger(__name__)


MINIMUM_BALANCE = 5000000


class SepulsaResponseCodes(object):

    GENERAL_ERROR = '99'
    ALL = ['00', '10', '20', '21', '22', '23', '24', '25', '50', '98', GENERAL_ERROR]
    FAILED = ['20', '21', '22', '23', '24', '25', '26', '50', '98', GENERAL_ERROR, '51']
    SUCCESS = ['00']
    PENDING = ['10']
    FAILED_VALIDATION_ELECTRICITY_ACCOUNT = ['20']
    PLN_HOURS_SERVER_OFF = [23, 24, 1]
    WRONG_NUMBER = '20'
    BILL_ALREADY_PAID = '50'
    PRODUCT_ISSUE = '21'
    TRAIN_ROUTE_NOT_FOUND = '50'
    REQUEST_TIMOUT = '23'
    PAYMENT_OVER_LIMIT = '26'
    TRAIN_TICKET_ERROR_RESPONSE = ('20', '23', '99')
    INTERNET_ERROR_RESPONSE = (WRONG_NUMBER, BILL_ALREADY_PAID, REQUEST_TIMOUT, PAYMENT_OVER_LIMIT)

    # response code are defined in Julo
    READ_TIMEOUT = '500'


class SepulsaHTTPCodes(object):
    # 450: "450 Product Closed Temporarily"
    FAILED = [450]

    FORBIDDEN = 403
    MISSING_OR_UNACCEPTABLE_DATA = 406
    DUPLICATE_ORDER_ID = 422
    PRODUCT_CLOSED_TEMPORARILY = 450


class JuloSepulsaClient(object):
    """JULO SEPULSA"""
    def __init__(self, base_url, username, secret_key):
        self.base_url = base_url
        self.username = username
        self.secret_key = secret_key

    def send_request(self, request_type, request_path, data=None, return_json=True, timeout=30):
        request_params = {
            "url": "%s%s" % (self.base_url, request_path),
            "json": data,
            "auth": HTTPBasicAuth(self.username, self.secret_key),
            "headers": {
                'User-Agent': self.username,
                'Content-type': 'application/json'
            },
            "timeout": timeout,
        }
        response = None
        return_response = None
        error = None

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            logger.info(
                {
                    'action': 'JuloSepulsaClient.send_request',
                    'url': request_path,
                    'request_headers': request_params['headers'],
                    'request_data': data,
                    'response_status_code': response.status_code,
                    'response_data': response.content.decode(),
                }
            )
            return_response = response.json()
            response.raise_for_status()

        except (ReadTimeout, ConnectionError) as e:
            get_julo_sentry_client().captureException()
            return_response = {'response_code': SepulsaResponseCodes.READ_TIMEOUT}
            error = SepulsaMessage.READ_TIMEOUT_ERROR
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action': "JuloSepulsaClient.send_request",
                'error': str(e),
            })
            error = "Error"
            if return_response and 'message' in return_response:
                error = return_response['message']

        if response and response.status_code == SepulsaHTTPCodes.PRODUCT_CLOSED_TEMPORARILY:
            return_response = {'response_code': SepulsaHTTPCodes.PRODUCT_CLOSED_TEMPORARILY}

        if not return_json:
            return response, error
        return return_response, error

    def _create_order_id(self, sepulsa_transaction):
        order_str = '%s-%s-%s' % (
            sepulsa_transaction.id,
            str(sepulsa_transaction.product.product_id),
            sepulsa_transaction.customer_id)
        order_id = encrypt_order_id_sepulsa(order_str)
        sepulsa_transaction.update_safely(order_id=order_id)
        return order_id

    def _handle_response_for_internet_bill(self, response, error):
        from juloserver.payment_point.services.internet_related import (
            get_error_message_for_internet_bill,
        )

        if error:
            return response, error

        # handle for failed response code
        error_message = get_error_message_for_internet_bill(response)
        if error_message:
            return response, error_message

        return response, error

    def get_balance(self):
        url = self.base_url + 'getBalance'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }

        logger.info({
            'action': "get_balance_sepulsa",
            'url': url,
            'headers': headers
        })
        response = requests.get(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers)
        logger.info({
            'action': "result_get_balance_sepulsaa",
            'response': response
        })
        if response.status_code != requests.codes.ok:
            raise JuloException(
                'Sepulsa get balance failed. result: %s' %
                (response.content)
            )
        response = json.loads(response.content)
        try:
            balance = response['balance']
        except Exception as e:
            balance = 0
        return balance

    def get_balance_and_check_minimum(self):
        balance = self.get_balance()
        is_below_minimum = balance < MINIMUM_BALANCE
        return balance, is_below_minimum

    def create_transaction(self, sepulsa_transaction):
        response = None
        product = sepulsa_transaction.product
        if product.type == SepulsaProductType.MOBILE and \
                product.category in SepulsaProductCategory.PRE_PAID_AND_DATA:
            response = self.create_mobile_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.ELECTRICITY and \
                product.category == SepulsaProductCategory.ELECTRICITY_PREPAID:
            response = self.create_electricity_prepaid_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.ELECTRICITY and \
                product.category == SepulsaProductCategory.ELECTRICITY_POSTPAID:
            response = self.create_electricity_postpaid_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.EWALLET:
            response = self.create_ewallet_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.BPJS:
            response = self.create_bpjs_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.MOBILE and \
                product.category in SepulsaProductCategory.POSTPAID:
            response = self.create_mobile_postpaid_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.PDAM:
            response = self.create_pdam_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.TRAIN_TICKET:
            response = self.create_train_ticket_transaction(sepulsa_transaction)
        elif product.type == SepulsaProductType.E_WALLET_OPEN_PAYMENT:
            response = self.create_ewallet_open_payment_transaction(sepulsa_transaction)
        else:
            raise JuloException(
                'Sepulsa create transaction failed. reason: Product not being recognized.'
            )

        content = response.content
        if response.status_code not in SepulsaHTTPCodes.FAILED:
            try:
                response = json.loads(content)
            except Exception:
                get_julo_sentry_client().captureException()
                response = {'content': content.decode()}
        else:
            response = {'content': content.decode()}

        logger.info({
            'action': "result_of_creating_transaction",
            'response': response,
            'sepulsa_transaction_id': sepulsa_transaction.id
        })

        return response

    def create_mobile_transaction(self, sepulsa_transaction):
        # generate order_id
        order_id = self._create_order_id(sepulsa_transaction)

        # posting mobile transaction to sepulsa
        url = self.base_url + 'transaction/mobile.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': sepulsa_transaction.phone_number,
            'product_id': sepulsa_transaction.product.product_id,
            'order_id': order_id
        }
        logger.info({
            'action': "create_mobile_transaction_sepulsa",
            'url': url,
            'headers': headers,
            'data': data
        })
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, json=data)
        logger.info({
            'action': "result_create_mobile_transaction_sepulsa",
            'response': response,
            'sepulsa_transaction_id': sepulsa_transaction.id
        })
        if response.status_code != requests.codes.created:
            if response.status_code == requests.codes.blocked_by_windows_parental_controls:
                notify_sepulsa_product_closed(sepulsa_transaction)
            if not sepulsa_transaction.loan:
                raise JuloException(
                    'Sepulsa create mobile transaction failed. result: %s' %
                    (response.content)
                )

        return response

    def get_account_electricity(self, meter_number, product_id, is_payment_point=False):
        url = self.base_url + 'inquire/electricity.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': meter_number,
            'product_id': product_id,
        }
        logger.info({
            'action': "get_account_electricity",
            'url': url,
            'headers': headers,
            'data': data
        })
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, json=data)
        logger.info(
            {
                'action': 'result_get_account_electricity',
                'url': url,
                'request_headers': headers,
                'request_data': data,
                'response_status_code': response.status_code,
                'response_data': response.content.decode(),
            }
        )
        if response.status_code not in (requests.codes.created, requests.codes.ok) \
                and not is_payment_point:
            raise JuloException(
                'Sepulsa get account electricity failed. result: %s' %
                (response.content)
            )
        try:
            response = json.loads(response.content)
        except Exception as e:
            response = response.content.decode()
        return response

    def create_electricity_prepaid_transaction(self, sepulsa_transaction):
        # generate order_id
        order_id = self._create_order_id(sepulsa_transaction)

        if not sepulsa_transaction.phone_number:
            application = sepulsa_transaction.customer.application_set.last()
            phone_number = application.mobile_phone_1 if application else None
            sepulsa_transaction.update_safely(phone_number=phone_number)

        # posting electricity transaction to sepulsa
        url = self.base_url + 'transaction/electricity.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': sepulsa_transaction.phone_number,
            'meter_number': sepulsa_transaction.customer_number,
            'product_id': sepulsa_transaction.product.product_id,
            'order_id': order_id
        }
        logger.info({
            'action': "create_electricity_prepaid_transaction_sepulsa",
            'url': url,
            'headers': headers,
            'data': data
        })
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, json=data)
        logger.info({
            'action': "result_create_electricity_prepaid_transaction_sepulsa",
            'response': response
        })
        if response.status_code != requests.codes.created:
            raise JuloException(
                'Sepulsa create electricity prepaid transaction failed. result: %s' %
                (response.content)
            )

        return response

    def get_transaction_detail(self, sepulsa_transaction):
        # get transaction detail from sepulsa
        url = '%stransaction/%s%s' % (self.base_url, sepulsa_transaction.transaction_code, '.json')
        headers = {
            'User-Agent': self.username,
            'transaction_id': sepulsa_transaction.transaction_code,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "get_transaction_detail_sepulsa",
            'url': url,
            'headers': headers,
        })
        response = requests.get(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers)
        logger.info({
            'action': "result_get_transaction_detail_sepulsa",
            'response': response
        })
        if response.status_code != requests.codes.ok:
            raise SepulsaException(
                'Sepulsa get transaction detail failed. result: %s' %
                (response.content)
            )
        try:
            response = json.loads(response.content)
        except Exception as e:
            response = response.content.decode()
        return response

    def get_product_list(self, type):
        url = self.base_url + 'product.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "get_product_list_sepulsa",
            'url': url,
            'headers': headers,
            'type': type
        })
        params = {
            'type': type,
        }
        response = requests.get(
            url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, params=params
        )
        if response.status_code != requests.codes.ok:
            raise JuloException(
                'Sepulsa get transaction detail failed. result: %s' % response.content
            )
        response = json.loads(response.content)
        return response

    def inquire_electricity_postpaid_information(self, meter_number, product_id):
        url = self.base_url + 'inquire/electricity_postpaid.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "inquire_electricity_postpaid_information",
            'url': url,
            'headers': headers,
            'meter_number': meter_number,
            'product_id': product_id,
        })
        data = {
            'customer_number': meter_number,
            'product_id': product_id,
        }

        try:
            response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                     headers=headers, json=data)
            logger.info(
                {
                    'action': 'result_inquire_electricity_postpaid_information',
                    'url': url,
                    'request_headers': headers,
                    'request_data': data,
                    'response_status_code': response.status_code,
                    'response_data': response.content.decode(),
                }
            )
            if response.ok:
                response_body = response.json()
            else:
                # Sepulsa responses 403, 406, 422, 450 when error by data, but body is not JSON
                # Note: 5xx cases also come in here

                if response.status_code != SepulsaHTTPCodes.MISSING_OR_UNACCEPTABLE_DATA:
                    sentry_client = get_julo_sentry_client()
                    sentry_client.captureMessage({
                        'error': f'Sepulsa response: {response.status_code}. Please check it',
                        **data
                    })

                response_body = response.content.decode()
            return True, response.status_code, response_body
        except requests.exceptions.ReadTimeout:
            # do not need to capture to Sentry
            return False, None, None
        except requests.exceptions.RequestException:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

            return False, None, None

    def create_electricity_postpaid_transaction(self, sepulsa_transaction):
        order_id = self._create_order_id(sepulsa_transaction)

        if not sepulsa_transaction.phone_number:
            application = sepulsa_transaction.customer.application_set.last()
            phone_number = application.mobile_phone_1 if application else None
            sepulsa_transaction.update_safely(phone_number=phone_number)

        # posting electricity transaction to sepulsa
        url = self.base_url + 'transaction/electricity_postpaid.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': sepulsa_transaction.customer_number,
            'product_id': sepulsa_transaction.product.product_id,
            'order_id': order_id
        }
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info({
            'action': "result_create_electricity_prepaid_transaction_sepulsa",
            'response': response,
            'sepulsa_transaction_id': sepulsa_transaction.id,
            'loan_id': sepulsa_transaction.loan.id
        })
        return response

    def inquire_bpjs(self, product_id, period_payment, bpjs_number):
        url = self.base_url + 'inquire/bpjs_kesehatan.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "inquire_bpjs_information",
            'url': url,
            'headers': headers,
            'customer_number': bpjs_number,
            'product_id': product_id,
        })
        payment_period = string_payment_period(period_payment)
        data = {
            'customer_number': bpjs_number,
            'product_id': product_id,
            'payment_period': payment_period,
        }
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info(
            {
                'action': 'result_inquire_bpjs_information',
                'url': url,
                'request_headers': headers,
                'request_data': data,
                'response_status_code': response.status_code,
                'response_data': response.content.decode(),
            }
        )
        try:
            response = json.loads(response.content)
        except Exception:
            response = response.content.decode()
        return response

    def inquire_mobile_postpaid(self, product_id, mobile_number):
        url = self.base_url + 'inquire/mobile_postpaid.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "inquire_mobile_postpaid_information",
            'url': url,
            'headers': headers,
            'customer_number': mobile_number,
            'product_id': product_id,
        })
        data = {
            'customer_number': mobile_number,
            'product_id': product_id,
        }
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info(
            {
                'action': 'result_inquire_mobile_postpaid_information',
                'url': url,
                'request_headers': headers,
                'request_data': data,
                'response_status_code': response.status_code,
                'response_data': response.content.decode(),
            }
        )
        try:
            response = json.loads(response.content)
        except Exception:
            response = response.content.decode()
        return response

    def create_ewallet_transaction(self, sepulsa_transaction):
        order_id = self._create_order_id(sepulsa_transaction)

        url = self.base_url + 'transaction/ewallet.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': sepulsa_transaction.phone_number,
            'product_id': sepulsa_transaction.product.product_id,
            'order_id': order_id
        }
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info({
            'action': "result_create_ewallet_transaction_sepulsa",
            'response': response,
            'sepulsa_transaction_id': sepulsa_transaction.id,
            'loan_id': sepulsa_transaction.loan.id
        })

        return response

    def create_ewallet_open_payment_transaction(self, sepulsa_transaction):
        order_id = self._create_order_id(sepulsa_transaction)

        url = self.base_url + 'v3/transaction/ewallet_open_payment'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_id': sepulsa_transaction.phone_number,
            'product_code': sepulsa_transaction.product.product_id,
            'order_id': order_id,
            'amount': sepulsa_transaction.customer_price_regular,
        }
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info({
            'action': "result_create_ewallet_open_payment_transaction",
            'request': data,
            'headers': headers,
            'response': response,
            'sepulsa_transaction_id': sepulsa_transaction.id,
        })

        return response

    def inquiry_ewallet_open_payment_transaction(self, mobile_phone_number, product_code, amount):
        url = self.base_url + 'v3/inquiry/ewallet_open_payment'

        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_id': mobile_phone_number,
            'product_code': product_code,
            'amount': amount,
        }
        response = None
        try:
            response = requests.post(
                url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers, json=data
            )
            response_status = response.status_code
            response = response.json()

            logger.info({
                'mobile_phone_number': mobile_phone_number,
                'request': data,
                'action': "inquiry_ewallet_open_payment_transaction",
                'response': response,
            })
            if response_status != requests.codes.ok:
                return False

            if response['response_code'] in SepulsaResponseCodes.SUCCESS:
                return True

        except Exception as err:
            logger.error({
                'mobile_phone_number': mobile_phone_number,
                'request': data,
                'action': "inquiry_ewallet_open_payment_transaction",
                'message': 'inquiry_ewallet_open_payment_transaction exception',
                'response': response,
                'error': err,
            })
        return False

    def create_mobile_postpaid_transaction(self, sepulsa_transaction):
        order_id = self._create_order_id(sepulsa_transaction)

        url = self.base_url + 'transaction/mobile_postpaid.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        data = {
            'customer_number': sepulsa_transaction.phone_number,
            'product_id': sepulsa_transaction.product.product_id,
            'order_id': order_id
        }
        logger.info({
            'action': "create_mobile_postpaid_transaction_sepulsa",
            'url': url,
            'headers': headers,
            'data': data
        })
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info({
            'action': "result_create_mobile_postpaid_transaction_sepulsa",
            'response': response
        })

        return response

    def create_bpjs_transaction(self, sepulsa_transaction):
        order_id = self._create_order_id(sepulsa_transaction)

        url = self.base_url + 'transaction/bpjs_kesehatan.json'
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        payment_period = string_payment_period(sepulsa_transaction.paid_period)
        data = {
            'customer_number': sepulsa_transaction.customer_number,
            'product_id': sepulsa_transaction.product.product_id,
            'payment_period': payment_period,
            'order_id': order_id
        }
        logger.info({
            'action': "create_bpjs_transaction_sepulsa",
            'url': url,
            'headers': headers,
            'data': data
        })
        response = requests.post(url, auth=HTTPBasicAuth(self.username, self.secret_key),
                                 headers=headers, json=data)
        logger.info({
            'action': "result_create_ewallet_transaction_sepulsa",
            'response': response
        })

        return response

    def get_transaction_detail_by_order_id(self, sepulsa_transaction):
        # using transaction list history api filtered by order_id
        url = '%stransaction.json?order_id=%s' % (self.base_url, sepulsa_transaction.order_id)
        headers = {
            'User-Agent': self.username,
            'Content-type': 'application/json'
        }
        logger.info({
            'action': "get_transaction_detail_sepulsa_by_order_id",
            'url': url,
            'headers': headers,
        })
        response = requests.get(
            url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers)
        logger.info({
            'action': "result_get_transaction_detail_sepulsa_by_order_id",
            'response': response
        })
        if response.status_code != requests.codes.ok:
            raise SepulsaException(
                'Sepulsa get transaction detail failed. result: %s' %
                (response.content)
            )
        try:
            response = json.loads(response.content)
        except Exception as e:
            response = response.content.decode()
        return response

    def create_pdam_transaction(self, sepulsa_transaction):
        data = {
            'customer_number': sepulsa_transaction.customer_number,
            'product_id': sepulsa_transaction.product.product_id,
            'operator_code': sepulsa_transaction.product.product_desc,
            'order_id': self._create_order_id(sepulsa_transaction)
        }
        api_response, _ = self.send_request('post', 'transaction/pdam.json', data=data, return_json=False)
        return api_response


    def create_train_ticket_transaction(self, sepulsa_transaction):
        train_transaction = sepulsa_transaction.traintransaction_set.last()
        reference_number = train_transaction.reference_number if train_transaction else ""
        data = {
            'customer_id': sepulsa_transaction.customer_number,
            'product_code': sepulsa_transaction.product.product_id,
            'reference_number': reference_number,
            'order_id': self._create_order_id(sepulsa_transaction)
        }
        api_response, _ = self.send_request('post', 'v3/transaction/train', data=data, return_json=False)
        return api_response

    def inquiry_internet_bill_info(self, customer_number: str, product_id: int, endpoint: str):
        data = {"customer_number": customer_number, "product_id": product_id}
        response, error = self.send_request(SepulsaHTTPRequestType.POST, endpoint, data=data)
        logger.info(
            {
                'action': "inquiry_internet_bill_info",
                'data': data,
                'endpoint': endpoint,
                'response': response,
                'error': error,
            }
        )
        return self._handle_response_for_internet_bill(response, error)

    def get_transaction_detail_ewallet_open_payment(self, sepulsa_transaction):
        url = self.base_url+ 'v3/transaction/ewallet_open_payment/{}'.format(
            sepulsa_transaction.transaction_code
        )
        headers = {
            'User-Agent': self.username,
            'transaction_id': sepulsa_transaction.transaction_code,
            'Content-type': 'application/json'
        }
        response = requests.get(url, auth=HTTPBasicAuth(self.username, self.secret_key), headers=headers)
        if response.status_code != requests.codes.ok:
            raise SepulsaException(
                'Sepulsa get transaction detail ewallet open payment failed. result: %s' %
                (response.content)
            )
        try:
            response = json.loads(response.content)
        except Exception as e:
            response = response.content.decode()
        logger.info({
            'action': "get_transaction_detail_ewallet_open_payment",
            'headers': headers,
            'response': response
        })
        return response


def get_sepulsa_transaction_general(sepulsa_transaction):
    julo_sepulsa_client = get_julo_sepulsa_client()
    if sepulsa_transaction.product.type == SepulsaProductType.E_WALLET_OPEN_PAYMENT:
        return julo_sepulsa_client.get_transaction_detail_ewallet_open_payment(
            sepulsa_transaction
        )

    return julo_sepulsa_client.get_transaction_detail(
        sepulsa_transaction
    )
