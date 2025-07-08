import logging
import requests
from django.conf import settings
from juloserver.julo.clients import get_julo_sentry_client
from rest_framework.views import APIView
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.nps.serializers import (
    NPSSurveySerilizers,
    NPSSurveyUpdateSerilizers,
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    internal_server_error_response,
    success_response,
)
from juloserver.nps.constants import NpsSurveyErrorMessages

logger = logging.getLogger(__name__)


class NPSSurveyAPIView(StandardizedExceptionHandlerMixinV2, APIView):
    def post(self, request):
        serializer = NPSSurveySerilizers(data=request.data)
        user = request.user
        customer = user.customer

        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        comments = serializer.validated_data.get("comments")
        rating = serializer.validated_data.get("rating")
        android_id = serializer.validated_data.get("android_id")

        try:
            headers = {
                "Authorization": request.META.get("HTTP_AUTHORIZATION", ""),
                "X-Customer-Id": str(request.user.customer.id),
            }
            request_body = {
                "comments": comments,
                "rating": int(rating),
                "android_id": str(android_id),
            }
            response = requests.post(
                settings.RATING_SERVICE_HOST + "/api/v1/nps-survey",
                headers=headers,
                json=request_body,
            )
            if response.status_code != 200:
                logger.error(
                    {
                        'action': 'NPSSurveyAPIView_POST',
                        'message': 'Hit rating-service API fail with http status {}'.format(
                            response.status_code
                        ),
                        'response': response.json(),
                        'customer_id': request.user.customer.id,
                    }
                )
                return general_error_response(NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG)

            return success_response({"customer_id": customer.id})
        except Exception as e:
            resp = str(e)
            logger.error(
                {
                    'action': 'NPSSurveyAPIView_POST',
                    'message': 'Hit rating-service API fail',
                    'response': resp,
                    'customer_id': request.user.customer.id,
                }
            )
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return internal_server_error_response('Terjadi kesalahan pada server.')

    def patch(self, request):
        serializer = NPSSurveyUpdateSerilizers(data=request.data)
        if not serializer.is_valid():
            return general_error_response(NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG)
        try:
            headers = {
                "Authorization": request.META.get("HTTP_AUTHORIZATION", ""),
                "X-Customer-Id": str(request.user.customer.id),
            }
            request_body = {
                "is_survey_accessed": serializer.validated_data.get("is_access_survey"),
            }
            response = requests.patch(
                settings.RATING_SERVICE_HOST + "/api/v1/nps-survey",
                headers=headers,
                json=request_body,
            )
            if response.status_code != 200:
                logger.error(
                    {
                        'action': 'NPSSurveyAPIView_PATCH',
                        'message': 'Hit rating-service API fail with http status {}'.format(
                            response.status_code
                        ),
                        'response': response.json(),
                        'customer_id': request.user.customer.id,
                    }
                )
                return general_error_response(NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG)

            return success_response({"customer_id": request.user.customer.id})
        except Exception as e:
            resp = str(e)
            logger.error(
                {
                    'action': 'NPSSurveyAPIView_PATCH',
                    'message': 'Hit rating-service API fail',
                    'response': resp,
                    'customer_id': request.user.customer.id,
                }
            )
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return internal_server_error_response('Terjadi kesalahan pada server.')
