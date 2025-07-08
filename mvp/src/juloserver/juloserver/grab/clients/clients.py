from builtins import str
from builtins import object
import functools
from functools import partial
from http import HTTPStatus
from requests.exceptions import Timeout
from celery import task
from typing import Optional
import time
import requests
import json
import logging
from django.conf import settings
from django.db.models import Q
from rest_framework import status
from requests.models import Response
from juloserver.grab.clients.request_constructors import GrabRequestDataConstructor
from juloserver.grab.clients.paths import GrabPaths
from juloserver.grab.constants import GrabErrorCodes, GrabErrorMessage, GrabApiLogConstants
from juloserver.grab.models import GrabAPILog, GrabLoanData, GrabCustomerData, GrabTransactions
from juloserver.grab.utils import GrabUtils
from juloserver.julo.models import Application, Loan
from juloserver.monitors.notifications import send_message_normal_format
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.grab.exceptions import GrabApiException

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
        return __retry_internal(partial(f, *args, **kwargs), exceptions, tries, delay, backoff, logger)

    return retry_decorator


@task(name="send_grab_api_timeout_alert_slack", queue="send_grab_api_timeout_alert_slack")
def send_grab_api_timeout_alert_slack(setting_env=None, response=None, uri_path=None, customer_id=None,
                                      application_id=None, slack_channel="#grab-dev", loan_id=None, phone_number=None,
                                      err_message=None):
    if not setting_env:
        setting_env = settings.ENVIRONMENT.upper()
    msg_header = "\n\n*GRAB API Timeout*"
    if setting_env != 'PROD':
        msg_header += " *(TESTING PURPOSE ONLY FROM %s)*" % (setting_env)
    msg = "\n\tURL : [{}]{}\n\tCustomer : {}\n\tPhone Number : {}\n\tApplication ID : {}\n\tLoan : {}\n\tError Message : {}\n\n".format(
        response.status_code if response else HTTPStatus.INTERNAL_SERVER_ERROR, uri_path, customer_id, phone_number, application_id, loan_id, err_message)
    send_message_normal_format(msg_header + msg, slack_channel)


def add_grab_api_log(headers=None, response=None, api_type=None, uri_path=None, application_id=None,
                     customer_id=None, loan_id=None, body=None, grab_customer_data=None):
    req = None
    error_code = None
    if headers:
        req = str(headers) + ' body :' + str(body) if body else str(headers)

    if response is not None:
        res_code = response.status_code
        content = str(response.content)
    else:
        res_code = 0
        content = "No response Received"
    if res_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED, 0}:
        try:
            response_content = json.loads(response.content)
            if 'error' in response_content and 'code' in response_content['error']:
                error_code = response_content['error']['code']
            else:
                error_code = None
        except ValueError as e:
            pass

    grab_api_log = GrabAPILog.objects.create(
        request=req,
        response=content,
        http_status_code=res_code,
        api_type=api_type,
        application_id=application_id,
        loan_id=loan_id,
        customer_id=customer_id,
        query_params=uri_path,
        grab_customer_data_id=grab_customer_data.id,
        external_error_code=error_code
    )
    return grab_api_log


class GrabClient(object):
    @staticmethod
    def log_grab_api_call(headers, response, api_type, uri_path, application_id=None,
                          customer_id=None, loan_id=None, body=None,
                          grab_customer_data=None):

        setting_env = settings.ENVIRONMENT.upper()
        default_slack_channel = "#grab-dev"
        if response is not None and response.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
            msg_header = "\n\n*GRAB API Failed*"
            if setting_env != 'PROD':
                msg_header += " *(TESTING PURPOSE ONLY FROM %s)*" % (setting_env)
            msg = "\n\tURL : [{}]{}\n\tCustomer : {}\n\tApplication : {}\n\tLoan : {}\n\n".format(
                response.status_code, uri_path, customer_id, application_id, loan_id)
            send_message_normal_format(msg_header + msg, default_slack_channel)

        try:
            grab_api_log = add_grab_api_log(
                headers=headers, response=response,
                api_type=api_type, application_id=application_id,
                customer_id=customer_id, loan_id=loan_id, uri_path=uri_path,
                body=body, grab_customer_data=grab_customer_data
            )
            return grab_api_log
        except Exception as e:
            logger.exception(e)

    @staticmethod
    def check_account_on_grab_side(phone_number, application_id=None, customer_id=None, loan_id=None):
        url, uri_path = GrabPaths.build_url(
            GrabPaths.LINK_GRAB_ACCOUNT, GrabRequestDataConstructor.GET)
        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.GET,
                                                                       uri_path,
                                                                       phone_number)
        try:
            response = requests.get(url, headers=headers)
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.GET,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path)
            return json.loads(response.content)
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response,
                             api_type=GrabRequestDataConstructor.GET, application_id=application_id,
                             customer_id=customer_id, loan_id=loan_id, uri_path=uri_path)
            raise e

    @staticmethod
    def get_loan_offer(phone_number, application_id=None, customer_id=None, loan_id=None):
        url, uri_path = GrabPaths.build_url(GrabPaths.LOAN_OFFER, GrabRequestDataConstructor.GET, "&product_type="
                                            + GrabRequestDataConstructor.APPLICATION_CODE)
        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.GET,
                                                                       uri_path,
                                                                       phone_number)
        grab_customer_data = GrabCustomerData.objects.filter(phone_number=phone_number).last()
        response = requests.get(url, headers=headers)
        if not isinstance(response, requests.Response) or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise GrabApiException(
                GrabUtils.create_error_message(
                    GrabErrorCodes.GLO_API_ERROR, GrabErrorMessage.API_TIMEOUT_ERROR_OFFER)
            )
        GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.GET,
                                     application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                     uri_path=uri_path, grab_customer_data=grab_customer_data)
        return json.loads(response.content)

    @staticmethod
    def construct_response_from_log(api_log: GrabAPILog) -> Response:
        response = Response()
        response.status_code = HTTPStatus.OK
        response.headers = {"Content-Type": "application/json"}
        response._content = api_log.response
        if isinstance(response._content, str):
            response._content = response._content.encode("utf-8")
        return response

    @staticmethod
    def fetch_application_submission_log(application_id, customer_id) -> Optional[Response]:
        api_log = GrabAPILog.objects.filter(
            application_id=application_id,
            customer_id=customer_id,
            query_params__contains=GrabPaths.APPLICATION_CREATION,
            http_status_code__in=[HTTPStatus.OK, HTTPStatus.CREATED]
        )
        if not api_log.exists():
            return None

        return GrabClient.construct_response_from_log(api_log.last())

    @staticmethod
    def check_and_update_application_creation_response(response: Response) -> Response:
        if response.status_code != HTTPStatus.CONFLICT:
            return response

        response_content = response.content.decode("utf-8")
        if GrabApiLogConstants.ERROR_APPLICATION_ALREADY_EXISTS_RESPONSE in response_content:
            response.status_code = HTTPStatus.OK
        return response

    @staticmethod
    @retry(Timeout, delay=5, tries=3)
    def submit_application_creation(application_id=None, customer_id=None, loan_id=None):
        url, uri_path = GrabPaths.build_url(
            GrabPaths.APPLICATION_CREATION, GrabRequestDataConstructor.POST)
        application_creation_request, headers = GrabRequestDataConstructor. \
            construct_application_creation_request(application_id)
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()

        try:
            response = requests.post(url, headers=headers,
                                     json=application_creation_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)

            response = GrabClient.check_and_update_application_creation_response(response)

            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, body=application_creation_request.to_dict(),
                                         grab_customer_data=grab_customer_data)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=application_creation_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    @retry(Timeout, delay=5, tries=3)
    def submit_application_updation(application_id=None, customer_id=None, loan_id=None):
        url, uri_path = GrabPaths.build_url(
            GrabPaths.APPLICATION_UPDATION, GrabRequestDataConstructor.PUT)
        application_updation_request, headers = GrabRequestDataConstructor. \
            construct_application_updation_request(application_id)
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()
        application_log = GrabAPILog.objects.filter(
            application_id=application_id,
            query_params__contains=GrabPaths.APPLICATION_CREATION,
            http_status_code=status.HTTP_200_OK,
        )
        if not application_log.exists():
            application = Application.objects.get(id=application_id)
            if application.application_status_id in \
                    {ApplicationStatusCodes.FORM_PARTIAL, ApplicationStatusCodes.FORM_CREATED,
                     ApplicationStatusCodes.FORM_PARTIAL_EXPIRED}:
                return
            return

        try:
            response = requests.put(url, headers=headers,
                                    json=application_updation_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.PUT,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, body=application_updation_request.to_dict(),
                                         grab_customer_data=grab_customer_data)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.PUT,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=application_updation_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    def submit_loan_creation(application_id=None, customer_id=None,
                             loan_id=None, txn_id=None):
        response = None
        url, uri_path = GrabPaths.build_url(
            GrabPaths.LOAN_CREATION, GrabRequestDataConstructor.POST)
        loan_creation_request, headers, txn_id = GrabRequestDataConstructor.construct_loan_creation_request(
            loan_id, txn_id)
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()

        try:
            response = requests.post(url, headers=headers, json=loan_creation_request.to_dict())
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, body=loan_creation_request.to_dict(),
                                         grab_customer_data=grab_customer_data)

            grab_loan_data = GrabLoanData.objects.filter(loan_id=loan_id).last()
            grab_loan_data.update_safely(auth_transaction_id=txn_id,
                                         auth_called=True)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response,
                             api_type=GrabRequestDataConstructor.GET, application_id=application_id,
                             customer_id=customer_id, loan_id=loan_id, uri_path=uri_path,
                             body=loan_creation_request.to_dict())
            raise e

    @staticmethod
    def get_pre_disbursal_check(phone_number, bank_code, bank_account_number,
                                application_id=None, customer_id=None, loan_id=None):
        url, uri_path = GrabPaths.build_url(GrabPaths.PRE_DISBURSAL_CHECK, GrabRequestDataConstructor.GET,
                                            "&bank_code=" + str(bank_code) + "&bank_account_number="
                                            + str(bank_account_number))
        headers = GrabRequestDataConstructor.construct_headers_request(GrabRequestDataConstructor.POST,
                                                                       uri_path,
                                                                       phone_number)
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()

        response = requests.post(url, headers=headers)
        try:
            response = requests.post(url, headers=headers)
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, grab_customer_data=grab_customer_data)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    def submit_disbursal_creation(disbursement_id, application_id=None, customer_id=None,
                                  loan_id=None, txn_id=None):
        url, uri_path = GrabPaths.build_url(
            GrabPaths.DISBURSAL_CREATION, GrabRequestDataConstructor.POST)
        disbursal_creation_request, headers, txn_id = GrabRequestDataConstructor. \
            construct_disbursal_creation_request(disbursement_id, txn_id)
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()
        try:
            response = requests.post(url, headers=headers,
                                     json=disbursal_creation_request.to_dict())
            if response.status_code in {HTTPStatus.INTERNAL_SERVER_ERROR,
                                        HTTPStatus.GATEWAY_TIMEOUT}:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response,
                                         api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id,
                                         loan_id=loan_id,
                                         uri_path=uri_path,
                                         body=disbursal_creation_request.to_dict(),
                                         grab_customer_data=grab_customer_data)

            grab_loan_data = GrabLoanData.objects.filter(loan_id=loan_id).last()
            grab_loan_data.update_safely(capture_called=True)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=disbursal_creation_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    def submit_cancel_loan(loan_id, application_id=None, customer_id=None, txn_id=None):
        """
        CHECK FOR CANCEL LOAN CALLED NEEDED OR NOT
        """
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()
            auth_log = GrabAPILog.objects.filter(
                loan_id=loan_id,
                query_params__contains=GrabPaths.LOAN_CREATION,
                http_status_code=status.HTTP_200_OK
            )
            auth_exist = auth_log.exists()
            auth_count = auth_log.count()

            capture_cancel = GrabAPILog.objects.filter(
                loan_id=loan_id,
                http_status_code=status.HTTP_200_OK
            ).filter(Q(query_params__contains=GrabPaths.DISBURSAL_CREATION)
                     | Q(query_params__contains=GrabPaths.CANCEL_LOAN))

            capture_cancel_count = capture_cancel.count()
            if not auth_exist or (auth_count <= capture_cancel_count):
                return

        url, uri_path = GrabPaths.build_url(GrabPaths.CANCEL_LOAN, GrabRequestDataConstructor.POST)
        loan_cancellation_request, headers, txn_id = GrabRequestDataConstructor. \
            construct_cancel_loan_request(loan_id, txn_id)

        try:
            response = requests.post(url, headers=headers, json=loan_cancellation_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, body=loan_cancellation_request.to_dict(),
                                         grab_customer_data=grab_customer_data)

            grab_loan_data = GrabLoanData.objects.filter(loan_id=loan_id).last()
            grab_loan_data.update_safely(cancel_called=True)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=loan_cancellation_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    @retry(Timeout, tries=6, delay=5, backoff=5)
    def trigger_loan_sync_api(loan_id, application_id=None, customer_id=None):
        response = None
        loan = Loan.objects.filter(
            id=loan_id, loan_status_id__in=set(
                LoanStatusCodes.grab_current_until_180_dpd() + (
                    LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                    LoanStatusCodes.FUND_DISBURSAL_FAILED,
                    LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                    LoanStatusCodes.PAID_OFF,
                    LoanStatusCodes.HALT
                )
            )
        ).exists()
        if not loan:
            logger.exception({
                "task": 'GrabClient.trigger_loan_sync_api',
                "exception": "Loan status not in matching for loan_sync_api",
                "loan_id": loan_id,
                "application_id": application_id,
                "customer_id": customer_id
            })
            return
        url, uri_path = GrabPaths.build_url(GrabPaths.LOAN_SYNC_API, GrabRequestDataConstructor.PUT)
        loan_sync_api_request, headers = GrabRequestDataConstructor. \
            construct_loan_sync_api_request(loan_id)
        try:
            logger.info({
                'task': 'trigger_loan_sync_api_response_logging',
                'action': 'logging_request',
                'loan_id': loan_id,
                'application_id': application_id,
                'customer_id': customer_id,
                'request_url': url,
                'request_body': loan_sync_api_request.to_dict(),
                'headers': headers
            })
            response = requests.put(url, headers=headers, json=loan_sync_api_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            logger.info({
                'task': 'trigger_loan_sync_api_response_logging',
                'action': 'logging_response',
                'loan_id': loan_id,
                'application_id': application_id,
                'customer_id': customer_id,
                'request_url': url,
                'request_body': loan_sync_api_request.to_dict(),
                'headers': headers,
                'response_status_code': response.status_code,
                'response_content': response.content if response is not None else None
            })
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
                GrabClient.log_grab_api_call(
                    headers=headers, response=response, api_type=GrabRequestDataConstructor.PUT,
                    application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                    uri_path=uri_path, body=loan_sync_api_request.to_dict()
                )
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.PUT,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=loan_sync_api_request.to_dict())
            raise e

    @staticmethod
    @retry(Timeout, delay=5, tries=3)
    def trigger_push_notification(application_id=None, customer_id=None, loan_id=None):
        grab_customer_data = None
        if customer_id:
            grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer_id).last()
        url, uri_path = GrabPaths.build_url(
            GrabPaths.PUSH_NOTIFICATION, GrabRequestDataConstructor.POST)
        push_notification_request, headers = GrabRequestDataConstructor. \
            construct_push_notification_request(application_id=application_id, loan_id=loan_id)

        try:
            response = requests.post(url, headers=headers, json=push_notification_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            GrabClient.log_grab_api_call(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                                         application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                                         uri_path=uri_path, body=push_notification_request.to_dict(),
                                         grab_customer_data=grab_customer_data)
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer_id, loan_id=loan_id,
                             uri_path=uri_path, body=push_notification_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e

    @staticmethod
    @retry(Timeout, delay=5, tries=3)
    def trigger_repayment_trigger_api(
            loan_id, grab_txn, overdue_amount=None, application_id=None):
        """
            Used To trigger the repayment trigger API,
            need to pass the LoanID to run this function
        """
        response = None
        logger.info({
            "action": "trigger_repayment_trigger_api",
            "status": "starting_deduction_attempt",
            "loan_id": loan_id,
            "grab_txn": grab_txn.id
        })
        grab_api_log = None
        loan = Loan.objects.select_related('customer').filter(pk=loan_id).last()
        if not loan:
            raise GrabApiException("LoanID is not valid for triggering "
                                   "repayment API: LoanID-{}".format(loan_id))
        customer = loan.customer
        if not customer:
            raise GrabApiException("Customer is not valid for triggering "
                                   "repayment API: LoanID-{}".format(loan.id))

        grab_customer_data = GrabCustomerData.objects.filter(customer=customer).last()

        if not grab_customer_data:
            raise GrabApiException("GrabCustomerData is not valid for triggering "
                                   "repayment API: CustomerID-{}".format(customer.id))
        grab_txn.status = GrabTransactions.IN_PROGRESS
        grab_txn.save(update_fields=['udate', 'status'])
        url, uri_path = GrabPaths.build_url(
            GrabPaths.DEDUCTION_API, GrabRequestDataConstructor.POST)
        deduction_api_request, headers = GrabRequestDataConstructor. \
            contruct_repayment_trigger_api(
                loan.loan_xid, grab_txn, customer, overdue_amount=overdue_amount)
        try:
            response = requests.post(url, headers=headers, json=deduction_api_request.to_dict())
            if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise Timeout(response=response, request=response.request)
            if response.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
                grab_txn.status = GrabTransactions.FAILED
                grab_api_log = GrabClient.log_grab_api_call(
                    headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                    application_id=application_id, customer_id=customer.id, loan_id=loan_id,
                    uri_path=uri_path, body=deduction_api_request.to_dict(),
                    grab_customer_data=grab_customer_data)
                logger.info({
                    "action": "trigger_repayment_trigger_api",
                    "status": "failed_deduction_attempt",
                    "loan_id": loan_id,
                    "grab_txn": grab_txn.id,
                    "response_code": response.status_code,
                    "response": response.content
                })
            else:
                logger.info({
                    "action": "trigger_repayment_trigger_api",
                    "status": "success_deduction_attempt",
                    "loan_id": loan_id,
                    "grab_txn": grab_txn.id,
                    "response": response.content,
                    "status_code": response.status_code
                })

            grab_txn.grab_api_log_id = grab_api_log.id if grab_api_log else grab_api_log
            grab_txn.save()
            logger.info({
                "action": "trigger_repayment_trigger_api",
                "status": "ending_deduction_attempt",
                "loan_id": loan_id,
                "grab_txn": grab_txn.id
            })
            return response
        except Timeout as e:
            add_grab_api_log(headers=headers, response=response, api_type=GrabRequestDataConstructor.POST,
                             application_id=application_id, customer_id=customer.id, loan_id=loan_id,
                             uri_path=uri_path, body=deduction_api_request.to_dict(),
                             grab_customer_data=grab_customer_data)
            raise e
