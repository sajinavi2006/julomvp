from builtins import str
from past.builtins import basestring
from builtins import object
import hashlib
from rest_framework.response import Response
from rest_framework import status, exceptions
from rest_framework.views import exception_handler
from .models import BukalapakInterest

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


def generate_customer_xid(customer_id):
    xid = int(hashlib.sha1(str(customer_id)).hexdigest(), 16) % (10 ** 10)
    # has to be 10 digits
    if xid < 1000000000:
        xid = xid + 1000000000
    return xid

def response_template(data=None, status=status.HTTP_200_OK, success=True, message=''):
    response_dict = {
        'success': success,
        'data': data,
        'msg': message}
    return Response(status=status, data=response_dict)

def html_response(data=None):
    return Response(data)

def success_response(data):
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


def get_late_fee_rules(limit):

    if limit == 1000000:
        return 5000
    elif limit == 2000000:
        return 10000
    elif limit == 3000000:
        return 15000

    return 5000


def get_interest_rate(id):
    # get last two digit number
    last_digit = id % 100

    termin = BukalapakInterest.objects.filter(last_digit_max__gte=last_digit,last_digit_min__lt=last_digit).first()

    if termin:
        return termin.interest_rate
    else:
        return 0.0

