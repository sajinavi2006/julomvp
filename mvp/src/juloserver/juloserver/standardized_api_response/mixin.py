import logging
from builtins import str

from django.http import HttpRequest
from django.views.generic import View
from past.builtins import basestring
from builtins import object
import copy
import time
from rest_framework import status, exceptions
from rest_framework.request import Request
from rest_framework.views import exception_handler
from django.utils.translation import ugettext_lazy as _
from juloserver.julo.clients import get_julo_sentry_client
from rest_framework.response import Response

from juloserver.julo.services2.fraud_check import get_client_ip_from_request
from juloserver.standardized_api_response.utils import internal_server_error_response
from juloserver.julo.constants import ApiLoggingConst

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

DEFAULT_EXCLUDE_FIELDS_NAME_IN_ERROR_MESSAGE = {'latitude', 'longitude',
                                                'new_phone_number', 'old_phone_number'}
api_logger = logging.getLogger('api.request')


class UncaughtExceptionResponse(Response):
    def __init__(self, exception):
        message = "%s: %s" % (exception.__class__.__name__, str(exception))
        response_dict = {
            'success': False,
            'status': 'error',
            'error_message': message}
        super(UncaughtExceptionResponse, self).__init__(
            data=response_dict, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


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
            response.data = {}
            response.data['success'] = False
            response.data['data'] = None
            response.data['errors'] = [error_message]
        elif not isinstance(list(response.data.values())[0], basestring):
            data = response.data
            errors_messages = []
            for key in data:
                for error in data[key]:
                    error_message = '%s %s' % (_(key).capitalize(), error)
                    if key in exclude_field_name_in_error_message:
                        error_message = error
                    errors_messages.append(error_message)
            response.data = {}
            response.data['success'] = False
            response.data['data'] = None
            response.data['errors'] = errors_messages
    return response


class StandardizedExceptionHandlerMixin(object):
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


class StrictStandardizedExceptionHandlerMixin(StandardizedExceptionHandlerMixin):
    """
    This mixin is used to handle exceptions in strict mode.
    All uncought exceptions or exceptions that are not extends APIException
    will have the same error message 'Terjadi kesalahan pada server'
    """
    def handle_exception(self, exc):
        response = super(StrictStandardizedExceptionHandlerMixin, self).handle_exception(exc)

        if isinstance(response, UncaughtExceptionResponse):
            return internal_server_error_response('Terjadi kesalahan pada server.')

        return response


class LoggingHandler:
    def __init__(self, logging_data_conf, request):
        self.logging_data_conf = logging_data_conf
        self.request = request
        self._init_log_content()

    def _init_log_content(self):
        self.log_content = {
            'action': 'logging_api_info',
            'ip_address': get_client_ip_from_request(self.request),
            'method': self.request.method,
            'path': self.request.path,
            'request_params': self.request.GET.dict(),
            'request_body': None,
            'payload_size': None,
            'response_status': None,
            'response_body': None,
            'elapsed': None,
        }

    def parse_headers(self):
        prefix = self.logging_data_conf.get('header_prefix')
        exclude_fields = self.logging_data_conf.get('exclude_fields', {}).get('header', [])
        header_data = {}
        if prefix:
            for header_key, header_value in self.request.META.items():
                if header_key.startswith(prefix):
                    header_data[header_key] = (
                        header_value if header_key not in exclude_fields else '******'
                    )

            self.log_content['header_data'] = header_data

    def parse_request(self):
        method = self.request.method
        request_data = None

        if method == 'GET':
            request_data = self.request.GET
        elif method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            request_data = self.request.data
        if self.request.FILES:
            self.log_content['files_info'] = {
                k: {v.name: v.size} for k, v in self.request.FILES.items()
            }

        try:
            if self.logging_data_conf.get('exclude_fields', {}).get('request'):
                request_data = copy.deepcopy(request_data)
                self._hide_value(request_data, self.logging_data_conf['exclude_fields']['request'])
        except Exception as e:
            api_logger.warning('parse_request_failed|err={}'.format(str(e)))

        self.log_content['request_body'] = request_data

    def parse_response(self, response, exception=None):
        response_data = response.data
        if self.logging_data_conf.get('exclude_fields', {}).get('response'):
            response_data = copy.deepcopy(response_data)
            self._hide_value(response_data, self.logging_data_conf['exclude_fields']['response'])

        if exception:
            self.log_content['exception'] = exception
        self.log_content['response_body'] = response_data
        self.log_content['payload_size'] = len(response_data) if response_data else 0

    @staticmethod
    def _hide_value(data, exclude_fields):
        for list_fields in exclude_fields:
            list_fields_len = len(list_fields)
            current_data = data
            for count, field in enumerate(list_fields, start=1):
                if field not in current_data:
                    break

                if count == list_fields_len:
                    current_data[field] = '******'
                    break
                if not isinstance(current_data[field], dict):
                    api_logger.warning(
                        'hide_value_for_api_request_log_failed|'
                        'data={}, exclude_fields={}'.format(current_data[field], exclude_fields)
                    )
                    break
                current_data = current_data[field]


class LoggingHandlerMixin:
    """
        This is the handler to log api request/response data:
        If you want to exclude some sensitive data, you can create a exclude_fields as a
        class variable:
            >>> class TestView(LoggingHandlerMixin, APIView):
            >>>     logging_data_conf = {
            >>>         'log_data': ['request', 'response', 'header'],
            >>>         'header_prefix': 'HTTP',
            >>>         'exclude_fields': {'header': ('HTTP_AUTHORIZATION',),
            >>>                            'request': (('phone_number',), ('credential', 'pin'))},
            >>>         'log_success_response': True #if you want to log data for status < 400
            >>>     }
            >>> # the log result will be hidden: {'HTTP_AUTHORIZATION': '******'} and
            >>> # {'username': 'tester_1', 'phone_number': ******, 'credential': {'pin': ******}}
        * Noted: - Always include header_prefix if you want to log header data
                 - exclude_fields['header'] doesn't contain inner dictionary so we don't put
                   the nested tuple format like request/response
    """

    def dispatch(self, request, *args, **kwargs):
        """
        Extend from this function rest_framework.views.APIView.dispatch
        Be careful if we upgrade the rest_framework library
        """
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers  # deprecate?

        # handle logging request data
        is_logging_data = False
        if hasattr(self, 'logging_data_conf'):
            is_logging_data = True
            start_time = time.time()
            raw_exception = None

        try:
            self.initial(request, *args, **kwargs)

            # Get the appropriate handler method
            if request.method.lower() in self.http_method_names:
                handler = getattr(self, request.method.lower(),
                                  self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            response = handler(request, *args, **kwargs)

        except Exception as exc:
            raw_exception = str(exc)
            response = self.handle_exception(exc)

        if is_logging_data:
            response_status = response.status_code
            if response_status >= 400 or self.logging_data_conf.get('log_success_response'):
                logging_handler = LoggingHandler(self.logging_data_conf, self.request)
                if ApiLoggingConst.LOG_REQUEST in self.logging_data_conf['log_data']:
                    logging_handler.parse_request()
                if ApiLoggingConst.LOG_HEADER in self.logging_data_conf['log_data']:
                    logging_handler.parse_headers()
                if ApiLoggingConst.LOG_RESPONSE in self.logging_data_conf['log_data']:
                    logging_handler.parse_response(response, raw_exception)

                logging_handler.log_content['elapsed'] = time.time() - start_time
                logging_handler.log_content['response_status'] = response_status
                api_logger.info(logging_handler.log_content)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response


class StandardizedExceptionHandlerMixinV2(
    LoggingHandlerMixin, StrictStandardizedExceptionHandlerMixin
):
    """
        This is new APIView extended from both LoggingHanlderMixin and
        StrictStandardizedExceptionHandlerMixin:
         - Log request/response data
         - Normal like error message for uncaught exception
    """
    pass
