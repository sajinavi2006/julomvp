import logging

from django.http import JsonResponse

from juloserver.dana.constants import DanaBasePath
from juloserver.dana.views import DanaAPIView
from juloserver.minisquad.constants import AiRudder

from juloserver.standardized_api_response.utils import (
    success_response,
)

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.permissions import AllowAny
from juloserver.dana.collection.tasks import dana_process_airudder_store_call_result

logger = logging.getLogger(__name__)


class BaseDanaCollectionAPIView(DanaAPIView):
    base_path = DanaBasePath.collection


class DanaCollectionView(BaseDanaCollectionAPIView):
    def post(self, request: Request) -> Response:
        return success_response("Hello World")


class AiRudderWebhooks(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = request.data
        fn_name = 'dana_airudder_webhooks_api'
        callback_type = serializer.get('type', None)
        callback_body = serializer.get('body', None)
        if callback_type not in [
            AiRudder.AGENT_STATUS_CALLBACK_TYPE,
            AiRudder.TASK_STATUS_CALLBACK_TYPE,
        ]:
            return JsonResponse({'status': 'skipped'})
        try:
            if not (callback_type) or not (callback_body):
                logger.error(
                    {
                        'function_name': fn_name,
                        'message': 'invalid json body payload',
                        'callback_type': callback_type,
                    }
                )
                return JsonResponse(
                    status=400,
                    data={'status': 'failed', 'message': 'Please provide valid json body payload'},
                )
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process airudder webhook',
                    'callback_type': callback_type,
                    'data': serializer,
                }
            )
            dana_process_airudder_store_call_result.delay(serializer)
            logger.info(
                {
                    'function_name': fn_name,
                    'callback_type': callback_type,
                    'data': serializer,
                    'message': 'sent to async task',
                }
            )
            return JsonResponse({'status': 'success'})

        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process airudder webhook',
                    'data': serializer,
                    'callback_type': callback_type,
                }
            )
            return JsonResponse(status=500, data={'status': 'failed', 'message': str(e)})
