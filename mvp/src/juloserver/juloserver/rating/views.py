import json
import requests
import logging
from django.conf import settings
from juloserver.rating.serializers import RatingSerializer
from juloserver.rating.tasks import submit_rating_task
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    internal_server_error_response,
)
from rest_framework.views import APIView
from juloserver.julo.clients import (
    get_julo_sentry_client,
)


logger = logging.getLogger(__name__)


class RatingDeciderAPI(APIView):
    def get(self, request):
        try:
            headers = {
                "Authorization": request.META.get("HTTP_AUTHORIZATION", ""),
                "X-Customer-Id": str(request.user.customer.id),
            }
            response = requests.get(
                settings.RATING_SERVICE_HOST + "/api/v1/inapp/popup/rejected-users",
                headers=headers,
            )

            if response.status_code != 200:
                logger.error(
                    {
                        'action': 'RatingDeciderAPI.get',
                        'message': 'Hit rating-service API fail',
                        'response': response.json(),
                        'customer_id': str(request.user.customer.id),
                    }
                )
                return internal_server_error_response('Terjadi kesalahan pada server.')

            return success_response(
                {
                    "show_rating_popup": response.json()['data']['show_popup'],
                }
            )
        except json.JSONDecodeError as e:
            logger.error(
                {
                    'action': 'RatingDeciderAPI.get',
                    'message': 'failed json decode',
                    'response': str(e),
                    'customer_id': str(request.user.customer.id),
                }
            )
            return internal_server_error_response('Terjadi kesalahan pada server.')


class SubmitRatingAPI(APIView):
    def post(self, request):
        serializer = RatingSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        try:
            headers = {
                "Authorization": request.META.get("HTTP_AUTHORIZATION", ""),
                "X-Customer-Id": str(request.user.customer.id),
            }
            data = {
                "customer_id": request.user.customer.id,
                "score": serializer.validated_data["rating"],
                "description": serializer.validated_data["description"],
                "csat_score": serializer.validated_data["csat_score"],
                "csat_description": serializer.validated_data["csat_detail"],
                "form_type": serializer.validated_data["rating_form"],
                "source": serializer.validated_data["source"],
            }
            submit_rating_task.apply_async(args=[headers, data])
        except Exception:
            get_julo_sentry_client().captureException()
            return internal_server_error_response('Terjadi kesalahan pada server.')

        return success_response('success')


class SuccessLoanRatingAPI(APIView):
    def get(self, request):
        headers = {
            "Authorization": request.META.get("HTTP_AUTHORIZATION", ""),
            "X-Customer-Id": str(request.user.customer.id),
        }
        response = requests.get(
            settings.RATING_SERVICE_HOST + "/api/v1/inapp/popup/success-loan",
            headers=headers,
        )

        try:
            if response.status_code != 200:
                logger.error(
                    {
                        'action': 'SuccessLoanRatingAPI.get',
                        'message': 'Hit rating-service API fail',
                        'response': response.json(),
                        'customer_id': str(request.user.customer.id),
                    }
                )
                return internal_server_error_response('Terjadi kesalahan pada server.')

            response_data = {
                'show_popup': response.json().get('data').get('show_popup'),
                'rating_form': response.json().get('data').get('rating_form'),
            }

            if response.json().get('data').get('source'):
                response_data['source'] = response.json().get('data').get('source')

            return success_response(response_data)
        except json.JSONDecodeError as e:
            logger.error(
                {
                    'action': 'SuccessLoanRatingAPI.get',
                    'message': 'failed json decode',
                    'response': str(e),
                    'customer_id': str(request.user.customer.id),
                }
            )
            return internal_server_error_response('Terjadi kesalahan pada server.')
