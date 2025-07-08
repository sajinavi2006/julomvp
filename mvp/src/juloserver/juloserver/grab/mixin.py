import logging
from builtins import str

from django.http import HttpRequest
from django.views.generic import View
from past.builtins import basestring
from builtins import object

from rest_framework import status, exceptions
from rest_framework.request import Request
from rest_framework.views import exception_handler
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.standardized_api_response.mixin import (
    DEFAULT_EXCLUDE_FIELDS_NAME_IN_ERROR_MESSAGE,
    UncaughtExceptionResponse
)
sentry_client = get_julo_sentry_client()

logger = logging.getLogger(__name__)


def _extract_log_data(exc, context):
    logger_data = {'exc': str(exc)}
    if not context and not isinstance(context, dict):
        return logger_data

    view = context.get('view')
    args = context.get('args')
    kwargs = context.get('kwargs')
    request = context.get('request')

    logger_data.update(args=args, kwargs=kwargs)
    if view and isinstance(view, View):
        logger_data.update(view_name=str(view))

    if request and isinstance(request, Request) or isinstance(request, HttpRequest):
        logger_data.update(request_url=request.get_full_path())

    return logger_data


def standardized_exception_handler(exc, context, exclude_raise_error_sentry_in_status_code,
                                   exclude_field_name_in_error_message):
    if not exclude_field_name_in_error_message:
        exclude_field_name_in_error_message = DEFAULT_EXCLUDE_FIELDS_NAME_IN_ERROR_MESSAGE
    else:
        exclude_field_name_in_error_message.update(DEFAULT_EXCLUDE_FIELDS_NAME_IN_ERROR_MESSAGE)
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    if not hasattr(exc, 'status_code') or \
            exc.status_code not in exclude_raise_error_sentry_in_status_code:
        logger.exception(_extract_log_data(exc, context))
        sentry_client.captureException()

    # Call DRF default exception handler first, to get the standard error
    # response for certain exceptions.
    response = exception_handler(exc, context)

    if response is None:
        response = UncaughtExceptionResponse(exc)
    else:
        error_message = response.data.get('detail', '')

        if error_message:
            response.data = {'success': False, 'data': None, 'errors': [error_message]}
        elif not isinstance(list(response.data.values())[0], basestring):
            data = response.data
            errors_messages = {}
            for key in data:
                for error in data[key]:
                    error_message = '{}'.format(error)
                    if key in exclude_field_name_in_error_message:
                        error_message = error
                    errors_messages[key] = error_message
            response.data = {'success': False, 'data': None, 'errors': errors_messages}
    return response


class GrabStandardizedExceptionHandlerMixin(object):
    exclude_raise_error_sentry_in_status_code = {}
    exclude_field_name_in_error_message = {}

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

        exception_handler = standardized_exception_handler

        context = self.get_exception_handler_context()
        response = exception_handler(
            exc, context, self.exclude_raise_error_sentry_in_status_code, self.exclude_field_name_in_error_message
        )

        if response is None:
            raise

        response.exception = True
        return response
