from rest_framework.views import APIView

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import (
    not_found_response,
    success_response,
    forbidden_error_response,
    general_error_response,
    internal_server_error_response,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.serializers.application_serializer import (
    JuloStarterApplicationSerializer,
)
from juloserver.application_form.serializers.reapply_serializer import JuloStarterReapplySerializer
from juloserver.application_form.services.julo_starter_service import submit_form, reapply
from juloserver.application_form.services.common import parse_param
from juloserver.application_form.constants import (
    JuloStarterFormResponseCode,
    JuloStarterReapplyResponseCode,
)
from juloserver.pin.utils import transform_error_msg
from juloserver.apiv2.services import is_otp_validated
from juloserver.apiv2.constants import ErrorMessage

logger = JuloLog(__name__)
julo_sentry_client = get_julo_sentry_client()


class ApplicationUpdate(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = JuloStarterApplicationSerializer

    def patch(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=self.request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'Failed to submit data',
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        app_version = request.META.get('HTTP_X_APP_VERSION')
        if not app_version:
            logger.error(
                {
                    'message': 'Invalid params from app_version',
                    'app_version': app_version,
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return general_error_response('Invalid params')

        validated_data = serializer.validated_data
        validated_data['app_version'] = app_version

        if validated_data.get('mobile_phone_1') and not is_otp_validated(
            kwargs.get('pk'), validated_data.get('mobile_phone_1')
        ):
            logger.warning(
                {
                    "message": "Mismatch in mobile phone number",
                    "process": "check_validated_otp",
                    "data": str(serializer.validated_data),
                    "app_version": app_version,
                    "application": kwargs.get('pk'),
                }
            )
            return general_error_response(ErrorMessage.PHONE_NUMBER_MISMATCH)

        result, data = submit_form(request.user, kwargs.get('pk'), validated_data)
        if result == JuloStarterFormResponseCode.APPLICATION_NOT_FOUND:
            logger.error(
                {
                    'message': 'Application not found',
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return not_found_response(message=data)

        if result in (
            JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW,
            JuloStarterFormResponseCode.NOT_FINISH_LIVENESS_DETECTION,
            JuloStarterFormResponseCode.USER_NOT_ALLOW,
        ):
            logger.error(
                {
                    'message': 'Failed to submit',
                    'reason': str(result),
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return forbidden_error_response(message=data)

        if result in (
            JuloStarterFormResponseCode.INVALID_PHONE_NUMBER,
            JuloStarterFormResponseCode.EMAIL_ALREADY_EXIST,
        ):
            logger.error(
                {
                    'message': 'Failed to submit',
                    'reason': str(result),
                    'application': kwargs.get('pk'),
                },
                request=request,
            )
            return general_error_response(data)

        return success_response(data)


class ApplicationReapply(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }

    @parse_param(serializer_class=JuloStarterReapplySerializer)
    def post(self, request, *args, **kwargs):
        result, data = reapply(request.user, kwargs['validated_data'])

        if result == JuloStarterReapplyResponseCode.SUCCESS:
            return success_response(data)

        if result in (
            JuloStarterReapplyResponseCode.CUSTOMER_CAN_NOT_REAPPLY,
            JuloStarterReapplyResponseCode.USER_HAS_NO_PIN,
        ):
            return forbidden_error_response(data)

        if result in (
            JuloStarterReapplyResponseCode.APPLICATION_NOT_FOUND,
            JuloStarterReapplyResponseCode.DEVICE_NOT_FOUND,
        ):
            return not_found_response(data)

        if result == JuloStarterReapplyResponseCode.SERVER_ERROR:
            return internal_server_error_response(data)
