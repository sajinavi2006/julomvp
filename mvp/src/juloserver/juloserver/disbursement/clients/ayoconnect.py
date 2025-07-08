import functools
import json
import logging
import time
from builtins import object, str
from functools import partial
from http import HTTPStatus

import requests

from django.utils import timezone

from juloserver.grab.models import PaymentGatewayApiLog, PaymentGatewayLogIdentifier
from juloserver.disbursement.tasks import send_payment_gateway_vendor_api_alert_slack
from juloserver.disbursement.exceptions import AyoconnectApiError
from juloserver.disbursement.utils import generate_unique_id, encrypt_request_payload, \
    replace_ayoconnect_transaction_id_in_url
from juloserver.disbursement.constants import (AyoconnectConst, AyoconnectURLs,
                                               AyoconnectErrorCodes)
from juloserver.julo.utils import format_nexmo_voice_phone_number

try:
    from decorator import decorator
except ImportError:
    def decorator(caller):
        """ Turns caller into a decorator.
        Unlike decorator module, function signature is not preserved.
        :param caller: caller(f, *args, **kwargs)
        """

        def decor(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return caller(f, *args, **kwargs)

            return wrapper

        return decor

logger = logging.getLogger(__name__)


def __retry_internal(f, exceptions=Exception, tries=-1, delay=0, backoff=1, logger=logger):
    """
    Executes a function and retries it if it failed.
    :param f: the function to execute.
    :param exceptions: an exception or a tuple of exceptions to catch. default: Exception.
    :param tries: the maximum number of attempts. default: -1 (infinite).
    :param delay: initial delay between attempts. default: 0.
    :param backoff: multiplier applied to delay between attempts. default: 1 (no backoff).
    :param logger: logger.warning(fmt, error, delay) will be called on failed attempts.
                   default: retry.logging_logger. if None, logging is disabled.
    :returns: the result of the f function.
    """
    _tries, _delay = tries, delay
    while _tries:
        try:
            return f()
        except exceptions as e:
            _tries -= 1
            if not _tries:
                raise

            if logger is not None:
                logger.warning('{} retrying in {} seconds...'.format(e, _delay))

            time.sleep(_delay)
            _delay *= backoff


def mapping_delay(counter):
    """
    mapping delay by the counter
    so when the api reach first retry it will directly retry,
    when api reach second retry it will wait for 5 sec and so on.
    """

    if counter == 2:
        return 5
    elif counter == 3:
        return 25

    return 1


def create_payment_gateway_api_log(data_to_be_logged: dict = None):
    """
    record log data to payment_gateway_api_log table
    """
    payment_gateway_api_log = PaymentGatewayApiLog.objects.create(
        customer_id=data_to_be_logged.get("customer_id"),
        application_id=data_to_be_logged.get("application_id"),
        payment_gateway_vendor_id=data_to_be_logged.get("payment_gateway_vendor_id"),
        request_data=data_to_be_logged.get("request_data"),
        response=data_to_be_logged.get("response"),
        error_code=data_to_be_logged.get("error_code"),
        http_status_code=data_to_be_logged.get("http_status_code"),
        api_url=data_to_be_logged.get("api_url"),
        correlation_id=data_to_be_logged.get("correlation_id"),
        transaction_id=data_to_be_logged.get("transaction_id"),
        beneficiary_id=data_to_be_logged.get("beneficiary_id"),
    )
    return payment_gateway_api_log


def encrypt_request_header_and_payload(header_and_payload: dict):
    """
    encrypt request header and payload
    request header and payload that wnat to encrypted must be a dictionary type
    """
    str_header_and_payload = json.dumps(header_and_payload)  # convert to str
    return encrypt_request_payload(str_header_and_payload)


def retry(exceptions=Exception, tries=-1, delay=0, backoff=1, logger=logger):
    """Returns a retry decorator.
    :param exceptions: an exception or a tuple of exceptions to catch. default: Exception.
    :param tries: the maximum number of attempts. default: -1 (infinite).
    :param delay: initial delay between attempts. default: 0. (in seconds)
    :param backoff: multiplier applied to delay between attempts. default: 1 (no backoff).
    :param logger: logger.warning(fmt, error, delay) will be called on failed attempts.
                   default: retry.logging_logger. if None, logging is disabled.
    :returns: a retry decorator.
    """

    @decorator
    def retry_decorator(f, *fargs, **fkwargs):
        args = fargs if fargs else list()
        kwargs = fkwargs if fkwargs else dict()
        return __retry_internal(
            partial(f, *args, **kwargs),
            exceptions, tries, delay, backoff, logger)

    return retry_decorator


class AyoconnectClient(object):
    """
        Client For Ayoconnect API request
    """
    timeout = 20
    bypass_sleep = False

    def __init__(
            self, base_url, client_id, client_secret, merchant_code, latitude, longitude,
            ip_address):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.merchant_code = merchant_code
        self.server_latitude = latitude
        self.server_longitude = longitude
        self.ip_address = ip_address

    def get_token(self, log_data=None) -> dict:
        """
        Get ayoconnect oauth token to use for API calls
        https://juloprojects.atlassian.net/wiki/spaces/PV/pages/3101163521/JULO+Payment+Gateway+Ayoconnect#Ayoconnect-Oauth
        """
        if log_data is None:
            log_data = {}
        query_param = "?grant_type=client_credentials"
        relative_url = AyoconnectURLs.ACCESS_TOKEN_URL
        url = "{}{}{}".format(self.base_url, relative_url, query_param)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        logger.info({
            "action": "AyoconnectClient.get_token",
            "data": data
        })

        header_and_payload = {
            "header": headers,
            "payloads": data
        }
        encrypted_request = encrypt_request_header_and_payload(header_and_payload)

        try:
            response = requests.post(url, headers=headers, data=data)
            json_response = response.json()
        except (requests.RequestException, requests.JSONDecodeError) as err:
            log_data["request_data"] = encrypted_request
            log_data["response"] = str(err)
            log_data["error_code"] = None
            log_data["http_status_code"] = None
            log_data["api_url"] = AyoconnectURLs.ACCESS_TOKEN_URL
            payment_gateway_api_log = create_payment_gateway_api_log(log_data)

            PaymentGatewayLogIdentifier.objects.create(
                payment_gateway_api_log=payment_gateway_api_log,
                identifier=log_data.get("customer_id"),
                query_param="grant_type=client_credentials"
            )
            raise AyoconnectApiError(str(err))

        if log_data:
            error_code = None
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
                response_errors = json_response.get("errors")
                if response_errors and response_errors[0]:
                    error_code = response_errors[0].get("code")
            log_data["request_data"] = encrypted_request
            log_data["response"] = json_response
            log_data["error_code"] = error_code
            log_data["http_status_code"] = json_response.get("code") if json_response.get(
                "code") else response.status_code
            log_data["api_url"] = AyoconnectURLs.ACCESS_TOKEN_URL
            payment_gateway_api_log = create_payment_gateway_api_log(log_data)

            PaymentGatewayLogIdentifier.objects.create(
                payment_gateway_api_log=payment_gateway_api_log,
                identifier=log_data.get("customer_id"),
                query_param="grant_type=client_credentials"
            )

        if response.status_code != HTTPStatus.OK:
            error_response = {
                "status_code": response.status_code,
                "error": json_response.get("Error")
            }
            raise AyoconnectApiError("Failed to get token: {}".format(error_response))

        return json_response

    def add_beneficiary(self, user_token: str, bank_account: str, swift_bank_code: str,
                        phone_number: str, counter: int = 0, log_data=None,
                        is_without_retry: bool = False) -> dict:
        """
        Register a customer bank account to ayoconnect to be used for disbursement
        https://juloprojects.atlassian.net/wiki/spaces/PV/pages/3101163521/JULO+Payment+Gateway+Ayoconnect#Create-Customer-beneficiary
        """
        if log_data is None:
            log_data = {}
        relative_url = AyoconnectURLs.BENEFICIARY_URL
        url = "{}{}".format(self.base_url, relative_url)
        unique_id = generate_unique_id()

        headers = {
            "Authorization": "Bearer {}".format(user_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "A-Correlation-ID": unique_id,
            "A-Merchant-Code": self.merchant_code,
            "A-Latitude": self.server_latitude,
            "A-Longitude": self.server_longitude
        }

        payloads = {
            "transactionId": unique_id,
            "phoneNumber": format_nexmo_voice_phone_number(phone_number),
            "customerDetails": {
                "ipAddress": "192.168.100.12"
            },
            "beneficiaryAccountDetails": {
                "accountNumber": bank_account,
                "bankCode": swift_bank_code
            }
        }

        logger.info({
            "action": "AyoconnectClient.add_beneficiary",
            "headers": headers,
            "payload": payloads
        })

        header_and_payload = {
            "header": headers,
            "payloads": payloads
        }
        encrypted_request = encrypt_request_header_and_payload(header_and_payload)

        try:
            response = requests.post(url, headers=headers, json=payloads)
            result = response.json()
        except (requests.RequestException, requests.JSONDecodeError) as e:
            logger.exception({
                "action": "AyoconnectClient.add_beneficiary",
                "message": "Unexpected error",
                "error": str(e),
                "payload": payloads
            })
            log_data["request_data"] = encrypted_request
            log_data["response"] = str(e)
            log_data["error_code"] = None
            log_data["http_status_code"] = None
            log_data["api_url"] = relative_url
            log_data["correlation_id"] = unique_id
            log_data["transaction_id"] = unique_id
            log_data["beneficiary_id"] = None
            create_payment_gateway_api_log(log_data)
            raise AyoconnectApiError("Unexpected error: {}".format(str(e)))

        error_code = None
        if log_data:
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
                response_errors = result.get("errors")
                if response_errors and response_errors[0]:
                    error_code = response_errors[0].get("code")
            log_data["request_data"] = encrypted_request
            log_data["response"] = result
            log_data["error_code"] = error_code
            log_data["http_status_code"] = result.get("code") if result.get(
                "code") else response.status_code
            log_data["api_url"] = relative_url
            log_data["correlation_id"] = unique_id
            log_data["transaction_id"] = unique_id
            log_data["beneficiary_id"] = result.get("beneficiary_id")
            create_payment_gateway_api_log(log_data)

        if is_without_retry:
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
                logger.error({
                    "action": "AyoconnectClient.add_beneficiary",
                    "message": "Unexpected error",
                    "error": response.status_code,
                    "payload": payloads
                })
                raise AyoconnectApiError(
                    message="Failed add beneficiary because status code is {}".format(
                        response.status_code
                    ),
                    error_code=error_code,
                )

            return result

        if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            message = result
            error_response = {
                "status_code": response.status_code,
                "error": message
            }
            if response.status_code in AyoconnectConst.RETRYABLE_STATUS_CODES:
                if response.status_code == HTTPStatus.UNAUTHORIZED:
                    # refresh token
                    try:
                        token_resp = self.get_token(log_data=log_data)
                        user_token = token_resp.get("accessToken")
                    except AyoconnectApiError as err:
                        logger.error({
                            "action": "AyoconnectClient.add_beneficiary",
                            "message": "Unexpected error",
                            "error": str(err),
                            "payload": payloads
                        })
                        raise AyoconnectApiError("Failed add beneficiary, {}".format(str(err)))

                if counter == 3:
                    logger.info({
                        "action": "AyoconnectClient.add_beneficiary",
                        "message": "max threshold for retry already reached",
                        "payload": payloads
                    })
                    send_payment_gateway_vendor_api_alert_slack.delay(
                        uri_path=url,
                        err_message=error_response,
                        req_header=headers,
                        payload=payloads,
                    )
                    raise AyoconnectApiError("Failed add beneficiary, {}".format(error_response))
                else:
                    counter += 1
                    # delay and retry
                    delay = mapping_delay(counter)
                    time.sleep(delay)
                    return self.add_beneficiary(user_token, bank_account, swift_bank_code,
                                                phone_number,
                                                counter,
                                                log_data)
            elif response.status_code == HTTPStatus.PRECONDITION_FAILED:
                if counter == 3:
                    logger.info({
                        "action": "AyoconnectClient.add_beneficiary",
                        "message": "max threshold for retry pre-conditional already reached",
                        "payload": payloads
                    })
                    send_payment_gateway_vendor_api_alert_slack.delay(
                        uri_path=url,
                        err_message=error_response,
                        req_header=headers,
                        payload=payloads,
                    )
                    raise AyoconnectApiError("Failed add beneficiary, {}".format(error_response))
                else:
                    # handle for error a_correlation_id and transaction_id
                    if message.get("errors") and isinstance(message.get("errors"), list) and \
                            message.get("errors")[0].get("code") in {
                            AyoconnectErrorCodes.A_CORRELATION_ID_ALREADY_USED,
                            AyoconnectErrorCodes.TRANSACTION_ID_INVALID
                    }:
                        counter += 1
                        # delay and retry
                        delay = mapping_delay(counter)
                        time.sleep(delay)
                        return self.add_beneficiary(user_token, bank_account, swift_bank_code,
                                                    phone_number,
                                                    counter,
                                                    log_data)
                    else:
                        raise AyoconnectApiError(
                            "Failed add beneficiary, {}".format(error_response))
            else:
                raise AyoconnectApiError("Failed add beneficiary, {}".format(error_response))
        elif response.status_code in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            return result

    def create_disbursement(
            self, user_token: str, ayoconnect_customer_id: str, beneficiary_id: str, amount: str,
            unique_id: str, remark: str = None, log_data=None, n_retry=1) -> dict:
        """
        Request a disbursement to Ayoconnect
        https://juloprojects.atlassian.net/wiki/spaces/PV/pages/3101163521/JULO+Payment+Gateway+Ayoconnect#Create-Disbursement
        """
        if log_data is None:
            log_data = {}
        relative_url = AyoconnectURLs.DISBURSEMENT_URL
        url = "{}{}".format(self.base_url, relative_url)
        a_correlation_id = unique_id

        headers = {
            "Authorization": "Bearer {}".format(user_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "A-Correlation-ID": a_correlation_id,
            "A-Merchant-Code": self.merchant_code,
            "A-Latitude": self.server_latitude,
            "A-Longitude": self.server_longitude,
            "A-IP-Address": self.ip_address,
            "A-TimeStamp": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        payloads = {
            "transactionId": unique_id,
            "customerId": ayoconnect_customer_id,
            "beneficiaryId": beneficiary_id,
            "amount": amount,
            "currency": "IDR",
            "remark": remark if remark else "Grab Disbursement"
        }

        logger.info({
            "action": "AyoconnectClient.create_disbursement",
            "headers": headers,
            "payload": payloads
        })

        result = self.hit_ayoconnect_with_retry(data={
            'url': url,
            'headers': headers,
            'payload': payloads,
            'n_retry': n_retry,
            'log_data': log_data
        }, method="POST")

        response = result.get('response')
        error = result.get('error')
        is_error = result.get('is_error')

        header_and_payload = {
            "header": headers,
            "payloads": payloads
        }
        encrypted_request = encrypt_request_header_and_payload(header_and_payload)

        if is_error:
            logger.exception({
                "action": "AyoconnectClient.create_disbursement",
                "headers": headers,
                "message": "AyoconnectClient Error: {}".format(error),
                "error": str(error),
                "payload": payloads
            })
            log_data["request_data"] = encrypted_request
            log_data["response"] = str(error)
            log_data["error_code"] = None
            log_data["http_status_code"] = None
            log_data["api_url"] = relative_url
            log_data["correlation_id"] = unique_id
            log_data["transaction_id"] = unique_id
            log_data["beneficiary_id"] = beneficiary_id
            create_payment_gateway_api_log(log_data)
            raise AyoconnectApiError(message="Failed create disbursement, {}".format(error))

        error_code = None
        if log_data:
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
                response_errors = response.json().get("errors")
                if response_errors and response_errors[0]:
                    error_code = response_errors[0].get("code")
            log_data["request_data"] = encrypted_request
            log_data["response"] = response.json()
            log_data["error_code"] = error_code
            log_data["http_status_code"] = response.json().get("code") if response.json().get(
                "code") else response.status_code
            log_data["api_url"] = relative_url
            log_data["correlation_id"] = unique_id
            log_data["transaction_id"] = unique_id
            log_data["beneficiary_id"] = beneficiary_id
            create_payment_gateway_api_log(log_data)

        # if status not 200 it will raise error
        if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            message = response.json()
            error_response = {
                "status_code": response.status_code,
                "error": message
            }
            raise AyoconnectApiError(
                message="Failed create disbursement, {}".format(error_response),
                transaction_id=message.get("transactionId"),
                error_code=error_code,
            )

        elif response.status_code in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            return response.json()

    def hit_ayoconnect_with_retry(self, data, method):
        '''
        retry when
        1. timeout
        2. got 401 status codes, in this time we request the token again to ayoconnect
        '''
        url = data.get('url')
        headers = data.get('headers')
        timeout = self.timeout
        n_retry = data.get('n_retry', 1)
        payload = data.get('payload')
        log_data = data.get('log_data', None)

        is_check_disburse_status = False
        is_get_merchant_balance = False

        if method.upper() == 'GET':
            if AyoconnectURLs.DISBURSEMENT_STATUS_URL in url:
                is_check_disburse_status = True
            elif AyoconnectURLs.MERCHANT_BALANCE_URL in url:
                is_get_merchant_balance = True

        error = None
        is_error = False
        response = None
        for counter in range(n_retry):
            try:
                if method.upper() == 'POST':
                    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                elif method.upper() == 'GET':
                    response = requests.get(url, headers=headers, timeout=timeout)

                status_code = None
                try:
                    status_code = response.status_code
                except (TypeError, ValueError):
                    pass

                logger.info({
                    "action": "AyoconnectClient.hit_ayoconnect_with_retry",
                    "method": method.upper(),
                    "url": url,
                    "headers": headers,
                    "payload": payload,
                    "status_code": status_code,
                    "n_retry": n_retry
                })

                error = None
                is_error = False
                # retry refresh token
                if response.status_code == HTTPStatus.UNAUTHORIZED:
                    error = AyoconnectApiError("Unauthorized: {}".format(response.status_code))
                    is_error = True

                    token_resp = self.get_token(log_data=log_data)
                    user_token = token_resp.get("accessToken")
                    headers.update({"Authorization": "Bearer {}".format(user_token)})
                    continue
                # retry for status code 412 (invalid transaction or correlation id)
                # but it's only for check disburse status so far
                if response.status_code == HTTPStatus.PRECONDITION_FAILED and (
                        is_check_disburse_status or is_get_merchant_balance):
                    message = response.json()
                    if message.get("errors") and isinstance(message.get("errors"), list) and \
                            message.get("errors")[0].get("code") in {
                            AyoconnectErrorCodes.A_CORRELATION_ID_ALREADY_USED,
                            AyoconnectErrorCodes.TRANSACTION_ID_INVALID
                    }:
                        unique_id = generate_unique_id()
                        req_correlation_id = unique_id
                        url = replace_ayoconnect_transaction_id_in_url(url, unique_id)
                        headers.update({"A-Correlation-ID": req_correlation_id})
                        continue
                break
            except requests.exceptions.Timeout as e:
                # just in case other api will use this
                # retry timeout only allow for check disburse status so far.
                error = e
                is_error = True
                if is_check_disburse_status:
                    if not self.bypass_sleep:
                        time.sleep(mapping_delay(counter=counter))
                    continue
                break
            except (requests.exceptions.RequestException, AyoconnectApiError) as e:
                error = e
                is_error = True
                break

        return {
            'response': response,
            'error': error,
            'is_error': is_error
        }

    def get_disbursement_status(
            self, user_token: str, ayoconnect_customer_id: str, beneficiary_id: str,
            a_correlation_id: str, reference_id: str = None, log_data=None, n_retry=1) -> dict:
        """
        Check disbursement status to Ayoconnect
        https://juloprojects.atlassian.net/wiki/spaces/PV/pages/3101163521/JULO+Payment+Gateway+Ayoconnect#Get-Disbursement-Status
        """
        if log_data is None:
            log_data = {}
        unique_id = generate_unique_id()
        req_correlation_id = unique_id
        transaction_id = unique_id
        query_param_ref_num = None
        relative_url = "{}/{}".format(AyoconnectURLs.DISBURSEMENT_STATUS_URL, a_correlation_id)
        query_param_txn_id = "?transactionId={}".format(transaction_id)
        if reference_id:
            query_param_ref_num = "&transactionReferenceNumber={}".format(reference_id)
        query_param_beneficiary_and_cust = "&beneficiaryId={}&customerId={}".format(
            beneficiary_id, ayoconnect_customer_id
        )
        full_query_param = "".join(filter(None, (
            query_param_txn_id, query_param_ref_num, query_param_beneficiary_and_cust)))
        url = "{}{}{}".format(self.base_url, relative_url, full_query_param)

        headers = {
            "Authorization": "Bearer {}".format(user_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "A-Correlation-ID": req_correlation_id,
            "A-Merchant-Code": self.merchant_code,
            "A-Latitude": self.server_latitude,
            "A-Longitude": self.server_longitude,
            "A-IP-Address": self.ip_address,
            "A-TimeStamp": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        logger.info({
            "action": "AyoconnectClient.get_disbursement_status",
            "headers": headers,
            "full_url": url
        })

        result = self.hit_ayoconnect_with_retry({
            'url': url,
            'headers': headers,
            'n_retry': n_retry
        }, "GET")

        response = result.get('response')
        error = result.get('error')
        is_error = result.get('is_error')

        if is_error:
            logger.exception({
                "action": "AyoconnectClient.get_disbursement_status",
                "headers": headers,
                "message": "AyoconnectClient Error: {}".format(error),
                "error": str(error),
                "full_url": url
            })
            encrypted_request = encrypt_request_header_and_payload(headers)
            log_data["request_data"] = encrypted_request
            log_data["response"] = str(error)
            log_data["error_code"] = None
            log_data["http_status_code"] = None
            log_data["api_url"] = AyoconnectURLs.DISBURSEMENT_STATUS_URL
            log_data["correlation_id"] = req_correlation_id
            log_data["transaction_id"] = transaction_id
            log_data["beneficiary_id"] = beneficiary_id
            payment_gateway_api_log = create_payment_gateway_api_log(log_data)

            PaymentGatewayLogIdentifier.objects.create(
                payment_gateway_api_log=payment_gateway_api_log,
                identifier=a_correlation_id,
                query_param=full_query_param
            )
            raise AyoconnectApiError(error)

        if log_data:
            error_code = None
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
                response_errors = response.json().get("errors")
                if response_errors and response_errors[0]:
                    error_code = response_errors[0].get("code")
            encrypted_request = encrypt_request_header_and_payload(headers)
            log_data["request_data"] = encrypted_request
            log_data["response"] = response.json()
            log_data["error_code"] = error_code
            log_data["http_status_code"] = response.json().get("code") if response.json().get(
                "code") else response.status_code.value
            log_data["api_url"] = AyoconnectURLs.DISBURSEMENT_STATUS_URL
            log_data["correlation_id"] = req_correlation_id
            log_data["transaction_id"] = transaction_id
            log_data["beneficiary_id"] = beneficiary_id
            payment_gateway_api_log = create_payment_gateway_api_log(log_data)

            PaymentGatewayLogIdentifier.objects.create(
                payment_gateway_api_log=payment_gateway_api_log,
                identifier=a_correlation_id,
                query_param=full_query_param
            )

        if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            message = response.json()
            error_response = {
                "status_code": response.status_code,
                "error": message
            }
            send_payment_gateway_vendor_api_alert_slack.delay(
                uri_path=url,
                err_message=error_response,
                req_header=headers,
                query_param=full_query_param
            )
            raise AyoconnectApiError(
                message=message,
                http_code=response.status_code,
                transaction_id=transaction_id
            )

        elif response.status_code in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            return response.json()

    def get_merchant_balance(self, user_token: str, n_retry=1) -> dict:
        """
        Get merchant balance to Ayoconnect
        https://juloprojects.atlassian.net/wiki/spaces/PV/pages/3101163521/JULO+Payment+Gateway+Ayoconnect#Get-Merchant-Balance
        """
        unique_id = generate_unique_id()
        query_param = "?transactionId={}".format(unique_id)
        relative_url = AyoconnectURLs.MERCHANT_BALANCE_URL
        url = "{}{}{}".format(self.base_url, relative_url, query_param)

        headers = {
            "Authorization": "Bearer {}".format(user_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "A-Correlation-ID": unique_id,
            "A-Merchant-Code": self.merchant_code,
        }

        logger.info({
            "action": "AyoconnectClient.get_merchant_balance",
            "headers": headers,
            "full_url": url
        })

        result = self.hit_ayoconnect_with_retry({
            'url': url,
            'headers': headers,
            'n_retry': n_retry
        }, "GET")

        response = result.get('response')
        error = result.get('error')
        is_error = result.get('is_error')

        if is_error:
            logger.exception({
                "action": "AyoconnectClient.get_merchant_balance",
                "headers": headers,
                "message": "AyoconnectClient Error: {}".format(error),
                "error": str(error),
                "full_url": url
            })
            raise AyoconnectApiError(error)

        if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            message = response.json()
            error_response = {
                "status_code": response.status_code,
                "error": message
            }
            send_payment_gateway_vendor_api_alert_slack.delay(
                uri_path=url,
                err_message=error_response,
                req_header=headers,
            )
            raise AyoconnectApiError(
                message=message,
                http_code=response.status_code,
                transaction_id=unique_id
            )

        elif response.status_code in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
            return response.json()
