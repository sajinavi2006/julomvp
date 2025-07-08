from __future__ import division
from past.builtins import basestring
from past.utils import old_div
from builtins import object
import hashlib
import datetime

from babel.numbers import format_number

from rest_framework.response import Response
from rest_framework import status, exceptions
from rest_framework.views import exception_handler

from juloserver.julo.statuses import (
    LoanStatusCodes,
    ApplicationStatusCodes,
)

from time import time

def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)
    if response:
        error_message = response.data.get('detail', '')

        if error_message:
            response.data = {}
            response.data['success'] = False
            response.data['data'] = None
            response.data['msg'] = error_message
        elif not isinstance(list(response.data.values())[0], basestring):
            data = response.data
            response.data = {}
            response.data['success'] = False
            response.data['data'] = data
            response.data['msg'] = "validation failed"
    return response


class CustomExceptionHandlerMixin(object):
    """
        Deprecated class since migrate to standardized_api_response.mixin.StandardizedExceptionHandlerMixin
    """
    # override rest framework handle exception,
    # because we don't want change existing API response by define custom exception_handler
    def handle_exception(self, exc):
        """
        Handle any exception that occurs, by returning an appropriate response,
        or re-raising the error.
        """
        if isinstance(exc, (exceptions.NotAuthenticated,
                            exceptions.AuthenticationFailed)):
            # WWW-Authenticate header for 401 responses, else coerce to 403
            auth_header = self.get_authenticate_header(self.request)

            if auth_header:
                exc.auth_header = auth_header
            else:
                exc.status_code = status.HTTP_403_FORBIDDEN

        exception_handler = custom_exception_handler

        context = self.get_exception_handler_context()
        response = exception_handler(exc, context)

        if response is None:
            raise

        response.exception = True
        return response

def response_template(data=None, status=status.HTTP_200_OK, success=True, message=''):
    response_dict = {
        'success': success,
        'status_code': status,
        'data': data,
        'msg': message}
    return Response(status=status, data=response_dict)


def success_response(data=None):
    return response_template(data)

def created_response(data):
    return response_template(data, status.HTTP_201_CREATED)

def server_error_response(message=None):
    if not message:
        message = ("ups! something went wrong Please try again. "
                   "If you keep seeing this message please contact our customer services")
    return response_template(
        None, status.HTTP_500_INTERNAL_SERVER_ERROR, False, message)

def not_found_response(message, data=None):
    return response_template(
        data, status.HTTP_404_NOT_FOUND, False, message)

def general_error_response(message, data=None):
    return response_template(
        data, status.HTTP_400_BAD_REQUEST, False, message)

def convert_timestamp(item_date_object):
    if isinstance(item_date_object, datetime.datetime):
        return item_date_object.__str__()

def spoof_text(text, number):
    word = []
    i = 1
    for char in text:
        if char == " ":
            i = 0
        elif i > 2:
            char = "*"
        word.append(char)
        i+=1

    return ''.join(word)

def spoofing_response(response, field, number):
    for data in response:
        data[field] = spoof_text(data[field], number)

    return response

def generate_lenderbucket_xid():
    return int(time()*1000)

def masked_transfer_amount(amount):
    str_transfer_amount = format_number(amount, locale = 'id_ID')
    return str_transfer_amount[:-7] + len(str_transfer_amount[-7:]) * "*"


def split_total_repayment_amount(total_amount):
    MAX_AMOUNT = 10**9 # one billion
    MIN_AMOUNT = 10**4 # ten thousand
    res = []
    int_res = old_div(total_amount,MAX_AMOUNT)
    rest = total_amount-int_res*MAX_AMOUNT
    res = [MAX_AMOUNT]*int_res + ([rest] if rest else [])
    # check if last amount too small
    if len(res) > 1 and res[-1] < MIN_AMOUNT:
        res[-1] = res[-1] + MIN_AMOUNT
        res[-2] = res[-2] - MIN_AMOUNT
    return res


def add_thousand_separator(amount_str, separator="."):
    result = []
    for index, number in enumerate(reversed(amount_str)):
        if index != 0 and index % 3 == 0:
            result.append(separator)
        result.append(number)
    result.reverse()
    return "".join(result)


def mapping_loan_and_application_status_code(loan_status_code):
    if loan_status_code == LoanStatusCodes.LENDER_APPROVAL:
        return ApplicationStatusCodes.LENDER_APPROVAL

    if loan_status_code in (
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
    ):
        return ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED

    if loan_status_code == LoanStatusCodes.FUND_DISBURSAL_FAILED:
        return ApplicationStatusCodes.FUND_DISBURSAL_FAILED

    if loan_status_code in (
        LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        LoanStatusCodes.SPHP_EXPIRED,
        LoanStatusCodes.LENDER_REJECT,
        LoanStatusCodes.GRAB_AUTH_FAILED,
        LoanStatusCodes.TRANSACTION_FAILED
    ):
        return ApplicationStatusCodes.APPLICATION_DENIED

    if loan_status_code == LoanStatusCodes.CURRENT:
        return ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL

    return loan_status_code
