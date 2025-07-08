from builtins import object, str

from past.builtins import basestring
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from rest_framework.views import exception_handler

from juloserver.julo.constants import NotPremiumAreaConst

from .constants import CreditMatrixV19, CreditMatrixWebApp


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    if response is not None:
        errors = []
        if not isinstance(list(response.data.values())[0], basestring):
            for key in response.data:
                errors += response.data[key]

            response.data = {}
            response.data['errors'] = errors
        else:
            error = list(response.data.values())[0]
            response.data = {}
            response.data['errors'] = [error]
    return response


def custom_error_messages_for_required(message, type=None):

    messages = {
        "blank": str(message + " Harus Diisi"),
        "null": str(message + " Harus Diisi"),
        "required": str(message + " Harus Diisi"),
        "invalid": str(message + " Tidak Valid"),
    }
    return messages


class CustomExceptionHandlerMixin(object):
    """
    Deprecated class since migrate to
    standardized_api_response.mixin.StandardizedExceptionHandlerMixin
    """

    # override rest framework handle exception,
    # because we don't want change existing API response by define custom exception_handler
    def handle_exception(self, exc):
        """
        Handle any exception that occurs, by returning an appropriate response,
        or re-raising the error.
        """
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
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


def response_failed(message):
    return Response(status=HTTP_400_BAD_REQUEST, data={'is_success': False, 'message': message})


def response_not_found(message):
    return Response(status=HTTP_404_NOT_FOUND, data={'is_success': False, 'message': message})


def get_type_transaction_sepulsa_product(product):
    if product.type == 'mobile':
        return product.category
    elif product.type == 'electricity':
        return '%s_%s' % (product.type, product.category)


def response_template(content=None, success=True, error_code='', error_message=''):
    response_dict = {
        'success': success,
        'content': content,
        'error_code': error_code,
        'error_message': error_message,
    }
    return response_dict


def success_template(content):
    return response_template(content)


def failure_template(error_code, error_message):
    return response_template(None, False, error_code, error_message)


def application_have_facebook_data(application):
    fb_data_exist = False
    try:
        fb_data_exist = True if application.facebook_data else False
    except Exception:
        fb_data_exist = False
    return fb_data_exist


def get_max_loan_amount_by_score(credit_score):
    max_amount = CreditMatrixV19.MAX_LOAN_AMOUNT_BY_SCORE[credit_score.score]
    if credit_score.score == 'B-' and credit_score.score_tag:
        max_amount = CreditMatrixV19.B_MINUS_MAX_LOAN_AMOUNT_BY_TAG[credit_score.score_tag]
    return max_amount


def get_max_loan_amount_and_duration_by_score(credit_score):
    if credit_score.inside_premium_area:
        return (
            get_max_loan_amount_by_score(credit_score),
            CreditMatrixV19.MAX_LOAN_DURATION_BY_SCORE[credit_score.score],
        )
    else:
        return (
            NotPremiumAreaConst.MAX_LOAN_AMOUNT_BY_SCORE[credit_score.score],
            NotPremiumAreaConst.MAX_LOAN_DURATION_BY_SCORE[credit_score.score],
        )


def get_max_loan_amount_and_duration_webapp(credit_score):
    return (
        CreditMatrixWebApp.MAX_LOAN_AMOUNT_BY_SCORE[credit_score.score],
        CreditMatrixWebApp.MAX_LOAN_DURATION_BY_SCORE[credit_score.score],
    )


def mask_fullname_each_word(name):
    words = name.split()
    masked_words = []

    for word in words:
        if len(word) == 1:
            masked_words.append(word)
        elif len(word) == 2:
            masked_word = word[0] + '*'
            masked_words.append(masked_word)
        else:
            masked_word = word[0] + '*' * (len(word) - 2) + word[-1]
            masked_words.append(masked_word)

    return ' '.join(masked_words)
