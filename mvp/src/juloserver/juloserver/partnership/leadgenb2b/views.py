import logging

from django.conf import settings
from django.http import HttpResponseNotFound, HttpResponseNotAllowed
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from juloserver.julo.models import Partner
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.partnership.api_response import error_response
from juloserver.partnership.constants import HTTPGeneralErrorMessage
from juloserver.partnership.exceptions import APIUnauthorizedError, APIError
from juloserver.partnership.utils import response_template
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    standardized_exception_handler,
)
from juloserver.partnership.security import PartnershipJWTAuthentication
from juloserver.partnership.leadgenb2b.security import LeadgenAPIAuthentication

from rest_framework import status, exceptions
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from typing import Any

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class LeadgenWebview(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipJWTAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            error_response = response_template(
                message=exc.detail,
                status=exc.status_code,
            )
            return error_response

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(HTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        if isinstance(exc, Exception):

            # For local dev directly raise the exception
            if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
                return exc

            sentry_client.captureException()

            error_response = response_template(
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            return error_response

        return super().handle_exception(exc)

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body

        # Check if url contains partner name
        partner_name = kwargs.get('partner_name')
        if not partner_name:
            return HttpResponseNotFound(HTTPGeneralErrorMessage.PAGE_NOT_FOUND)

        is_partner_exists = Partner.objects.filter(
            name=partner_name,
            is_active=True,
        ).exists()

        if not is_partner_exists:
            return HttpResponseNotFound(HTTPGeneralErrorMessage.PAGE_NOT_FOUND)

        request.partner_name = partner_name
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)

        return response

    def _log_request(
        self,
        request_body: bytes,
        request: Request,
        response: Response,
    ) -> None:
        authorization = request.META.get('HTTP_AUTHORIZATION', None)
        now = timezone.localtime(timezone.now())
        timestamp = "{}+07:00".format(now.strftime("%Y-%m-%dT%H:%M:%S"))

        # Log Headers
        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_AUTHORIZATION': authorization,
        }

        # Log every API Request and Response
        # Note: Should eliminate PII data after development complete on this log
        data = ''
        if hasattr(response, "data"):
            data = response.data
        elif hasattr(response, "url"):
            data = response.url

        data_to_log = {
            "action": "leadgenb2b_view_logs",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.build_absolute_uri(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": data,
        }

        logger.info(data_to_log)


class LeadgenStandardAPIView(StandardizedExceptionHandlerMixin, APIView):
    """
    Standarize Partnership Leadgen API View
    """

    permission_classes = []
    authentication_classes = [LeadgenAPIAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            err_response = error_response(
                message=exc.detail,
                status=exc.status_code,
            )
            return err_response

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(HTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        if isinstance(exc, Exception):

            # For local dev directly raise the exception
            if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
                return exc

            err_response = error_response(
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

            sentry_client.captureException()
            logger.exception(
                {
                    'action': 'leadgen_standard_api_view',
                    'error': str(exc),
                }
            )

            return err_response


class LeadgenStandardizedExceptionHandlerMixin(object):
    exclude_raise_error_sentry_in_status_code = {}
    exclude_field_name_in_error_message = {}

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

        if isinstance(exc, APIError):
            meta = None
            message = None
            data = {}
            errors = {}
            if exc.detail:
                if exc.detail.get('meta'):
                    meta = exc.detail.get('meta')
                if exc.detail.get('message'):
                    message = exc.detail.get('message')
                if exc.detail.get('data'):
                    data = exc.detail.get('data')
                if exc.detail.get('errors'):
                    errors = exc.detail.get('errors')

            err_response = error_response(
                meta=meta,
                data=data,
                errors=errors,
                message=message,
                status=exc.status_code,
            )
            return err_response

        exception_handler = standardized_exception_handler
        context = self.get_exception_handler_context()
        response = exception_handler(
            exc,
            context,
            self.exclude_raise_error_sentry_in_status_code,
            self.exclude_field_name_in_error_message,
        )

        if response is None:
            raise

        response.exception = True
        return response
