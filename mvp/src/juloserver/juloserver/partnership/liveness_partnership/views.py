import logging

from django.conf import settings
from django.http import HttpResponseNotAllowed

from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.partnership.constants import PartnershipHttpStatusCode
from juloserver.partnership.liveness_partnership.exceptions import APIForbiddenError
from juloserver.partnership.liveness_partnership.security import PartnershipLivenessAuthentication
from juloserver.partnership.liveness_partnership.constants import (
    LivenessHTTPGeneralErrorMessage,
    LivenessType,
)
from juloserver.partnership.liveness_partnership.services import (
    process_smile_liveness,
    process_passive_liveness,
)
from juloserver.partnership.liveness_partnership.serializers import LivenessImageUploadSerializer
from juloserver.partnership.liveness_partnership.utils import (
    liveness_error_response,
    liveness_success_response,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class ParntershipLivenessAPIView(StandardizedExceptionHandlerMixin, APIView):
    """
    This API will using for Partnership Liveness API View
    """

    permission_classes = []
    authentication_classes = [PartnershipLivenessAuthentication]

    def handle_exception(self, exc: Exception) -> Response:

        if isinstance(exc, APIForbiddenError):
            return liveness_error_response(
                status=exc.status_code,
                message=exc.detail,
            )

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(LivenessHTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        # For local dev directly raise the exception
        if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
            raise exc

        sentry_client.captureException()
        response_err = liveness_error_response(
            message=LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

        logger.exception(
            {
                'action': 'mf_standard_api_view',
                'error': str(exc),
            }
        )
        return response_err


class LivenessSettingsView(ParntershipLivenessAPIView):

    def get(self, request: Request) -> Response:
        if hasattr(request, 'liveness_configuration'):
            liveness_configuration = request.liveness_configuration
            detection_types = liveness_configuration.detection_types
            if detection_types:
                result = []
                liveness_type = [
                    LivenessType.PASSIVE,
                    LivenessType.SMILE,
                ]
                # process checking value detection_types
                for detection_type in liveness_type:
                    value = detection_types.get(detection_type)
                    if isinstance(value, bool):  # Check if the value is a boolean
                        if value:  # Only add if the value is True
                            result.append(detection_type)
                    else:
                        logger.warning(
                            {
                                "action": "LivenessSettingsView",
                                "message": "Invalid value for key {}".format(detection_type),
                                "client_id": liveness_configuration.client_id,
                            }
                        )

                # checking result detection_types
                # return 500 failed get detection_types
                if not result:
                    logger.warning(
                        {
                            "action": "LivenessSettingsView",
                            "message": "failed get detection_types value",
                            "client_id": liveness_configuration.client_id,
                        }
                    )
                    return liveness_error_response(
                        message=LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                response = {'steps': result}
                return liveness_success_response(
                    data=response,
                    status=status.HTTP_200_OK,
                )
            else:
                # handle if detection_types is null/empty
                logger.warning(
                    {
                        "action": "LivenessSettingsView",
                        "message": "failed get detection_types value",
                        "client_id": liveness_configuration.client_id,
                    }
                )
                return liveness_error_response(
                    message=LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        else:
            # handle if failed get liveness_configuration
            logger.warning(
                {
                    "action": "LivenessSettingsView",
                    "message": "failed get data liveness_configuration",
                    "client_id": liveness_configuration.client_id,
                }
            )
            return liveness_error_response(
                message=LivenessHTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LivenessCheckProcessView(ParntershipLivenessAPIView):
    serializer_class = LivenessImageUploadSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        liveness_method = self.kwargs.get('liveness_method')
        liveness_configuration = request.liveness_configuration
        detection_types = liveness_configuration.detection_types

        # chcking if the configuration allow for liveness method
        if not detection_types.get(liveness_method):
            return liveness_error_response(
                message=LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.serializer_class(
            data=request.data, context={'liveness_method': liveness_method}
        )
        if not serializer.is_valid():
            return liveness_error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors,
            )

        validated_data = serializer.validated_data
        smile_image = validated_data.get('smile')
        neutral_image = validated_data.get('neutral')
        if liveness_method == LivenessType.SMILE:
            liveness_result, is_success = process_smile_liveness(
                liveness_configuration,
                neutral_image,
                smile_image,
            )
        else:
            liveness_result, is_success = process_passive_liveness(
                liveness_configuration,
                neutral_image,
            )
        if not is_success:
            return liveness_error_response(
                message=liveness_result,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = {
            'id': str(liveness_result.reference_id),
            'score': liveness_result.score,
        }
        return liveness_success_response(
            data=response,
            status=status.HTTP_200_OK,
        )
