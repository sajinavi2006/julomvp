import logging
from datetime import datetime

from celery.task import task
from django.db import transaction

from juloserver.comms.constants import EventConst
from juloserver.comms.models import (
    CommsRequest,
    CommsRequestEvent,
)
from juloserver.comms.serializers.email import EmailCallbackDTO
from juloserver.comms.services.email_service import (
    EmailSender,
    publish_send_email,
)
from juloserver.julo.models import EmailHistory
from juloserver.julo.services2 import get_redis_client


logger = logging.getLogger(__name__)


@task(queue="comms_email")
def send_email_via_rmq(request_id, redis_key, retry_num=0):
    """
    Send email via RMQ.
    """
    logger_data = {
        "action": "send_email_via_rmq",
        "request_id": request_id,
        "redis_key": redis_key,
    }
    redis_client = get_redis_client()
    send_email_kwargs_json = redis_client.get(redis_key)
    if not send_email_kwargs_json:
        logger.warning(
            {
                "message": "send_email_kwargs_json not found in redis",
                **logger_data,
            }
        )
        return

    send_email_kwargs = EmailSender.deserialize_send_email_args(send_email_kwargs_json)

    return publish_send_email(
        retry_num=retry_num,
        **send_email_kwargs,
    )


@task(bind=True, queue="comms_global", max_retries=3)
def add_comms_request_event(self, comms_request_id, event, event_at, remarks=None):
    """
    Add comm request event.
    """
    logger_data = {
        "action": "add_comms_request_event",
        "celery_task_id": self.request.id,
        "comm_request_id": comms_request_id,
        "event": event,
        "event_at": event_at,
        "remarks": remarks,
    }
    logger.debug(
        {
            "message": "Start storing",
            **logger_data,
        }
    )
    comms_request = CommsRequest.objects.get(id=comms_request_id)

    CommsRequestEvent.objects.create(
        comms_request=comms_request,
        event=event,
        event_at=event_at,
        remarks=remarks,
    )

    with transaction.atomic():
        # Because we don't have event_at information in `EmailHistory`. This is the best we can do:
        # Update email history if:
        # 1. the status movement is valid from the EventConst perspective
        # 2. or, the event is not in EventConst. This means the event is not controlled by system
        email_history = (
            EmailHistory.objects.select_for_update()
            .filter(sg_message_id=comms_request.request_id)
            .last()
        )
        if email_history and (
            email_history.status in EventConst.all()
            and event in EventConst.all()
            or event not in EventConst.all()
        ):
            logger.info(
                {
                    "message": "Update email history status",
                    "previous_status": email_history.status,
                    "previous_udate": email_history.udate,
                    "new_status": event,
                    "event_at": str(event_at),
                    **logger_data,
                }
            )
            email_history.status = event
            email_history.save(update_fields=['status', 'udate'])

    return comms_request_id, event, event_at


@task(bind=True, queue="comms_email")
def save_email_callback(self, email_callback_dto: dict):
    """
    Save email callback event from the API callback event
    Args:
        self (Task): Celery task
        email_callback_dto (dict): Email callback event data based on EmailCallbackDTO.
    Returns
        request_id (str): External request ID. The ID from the email service
        status (str): Email status
    """
    logger_data = {
        "action": "save_email_callback",
        "celery_task_id": self.request.id,
    }
    logger.debug(
        {
            "message": "Start storing",
            "email_callback_dto": email_callback_dto,
            **logger_data,
        }
    )
    serializer = EmailCallbackDTO(data=email_callback_dto)
    serializer.is_valid(raise_exception=True)
    email_callback_dto = serializer.validated_data

    request_id = email_callback_dto["email_request_id"]
    logger_data.update({"request_id": request_id})

    comms_request_id = (
        CommsRequest.objects.filter(request_id=request_id).values_list("id", flat=True).last()
    )
    if not comms_request_id:
        logger.warning(
            {
                "message": "CommsRequest not found",
                **logger_data,
            }
        )
        return request_id, "request_id not found"

    add_comms_request_event(
        comms_request_id=comms_request_id,
        event=email_callback_dto["status"],
        event_at=datetime.fromtimestamp(email_callback_dto["event_at"]),
        remarks=email_callback_dto.get("remarks"),
    )
    return request_id, email_callback_dto["status"]
