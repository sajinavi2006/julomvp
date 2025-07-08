import logging

from rest_framework.views import APIView

from juloserver.comms.serializers.email import EmailCallbackDTO
from juloserver.comms.tasks import save_email_callback
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)

logger = logging.getLogger(__name__)


class EventCallbackView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    serializer_class = EmailCallbackDTO

    def post(self, request, *args, **kwargs):
        """
        Received callback event from email service.
        And store the event to database via celery tasks
        """
        logger.info(
            {
                "action": "EventCallbackView.post",
                "message": "Received callback event from email service",
                "request_data": request.data,
            }
        )
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.error_string())

        # Store the event to database via celery tasks
        celery_task = save_email_callback.delay(serializer.validated_data)
        logger.info(
            {
                "action": "EventCallbackView.post",
                "message": "published to RMQ",
                "celery_task_id": celery_task.id,
            }
        )
        return success_response({"task_id": celery_task.id})
