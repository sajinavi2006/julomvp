import datetime
import logging
import random
from datetime import (
    datetime,
    time,
    timedelta,
)
from typing import Optional

from celery import task
from django.conf import settings
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import (
    ReminderTypeConst,
    VendorConst,
    VoiceTypeStatus,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.reminders import Reminder
from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.nexmo.constants import NexmoVoiceRateLimit
from juloserver.nexmo.models import (
    IsRiskyExcludedDetail,
    NexmoCustomerData,
    NexmoSendConfig,
)
from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_voice_client_v2,
)
from juloserver.julo.models import (
    CommsProviderLookup,
    Customer,
    VendorDataHistory,
    VoiceCallRecord,
)
from juloserver.nexmo.services import (
    NexmoVoiceContentSanitizer,
    nexmo_product_type,
)
from juloserver.ratelimit.constants import RateLimitTimeUnit
from juloserver.ratelimit.service import sliding_window_rate_limit
from juloserver.streamlined_communication.utils import payment_reminder_execution_time_limit

logger = logging.getLogger(__name__)


@task(queue='collection_high')
def store_risk_payment_data(data):
    for payment_id, dpd, model_version in data:
        try:
            IsRiskyExcludedDetail.objects.create(
                payment_id=payment_id,
                dpd=dpd,
                model_version=model_version
            )
        except Exception as error:
            logger.error(
                {
                    'action': 'store_risk_payment_data',
                    'msg': str(error),
                    'data': [payment_id, dpd, model_version],
                }
            )


@task(bind=True, queue='collection_nexmo')
@payment_reminder_execution_time_limit
def process_call_customer_via_nexmo(self, trigger_time: datetime, source: str, request_data: dict):
    """
    Process call customer via Nexmo.  No DB query for this task.
    Args:
        self: Task instance
        trigger_time (datetime): Time when the task is triggered
        source (str): Source of the request
        request_data (dict): This data is validate_data from
                    juloserver.integapiv1.serializers.CallCustomerNexmoRequestSerializer

    Returns:
        None
    """
    campaign_data = request_data.get('campaign_data')
    retries = request_data.get('retries')
    payloads = request_data.get('payload')

    logger_data = {
        "action": "process_call_customer_via_nexmo",
        "celery_task_id": self.request.id,
    }
    logger.info(
        {
            **logger_data,
            "message": "Processing nexmo voice call scheduler",
            'campaign_data': request_data.get('campaign_data'),
            'retries': retries,
            'total_payloads': len(payloads),
        }
    )

    template_code = "{}|{}|{}".format(
        source, campaign_data.get('campaign_id'), campaign_data.get('campaign_name')
    )
    template_code = template_code[:200]

    trigger_time = timezone.localtime(trigger_time)  # ensure trigger_time is in local timezone
    now = timezone.localtime(timezone.now())
    send_config = NexmoSendConfig(
        trigger_time=trigger_time,
        max_retry=len(retries),
        min_retry_interval=request_data.get(
            'min_retry_delay_in_minutes',
            NexmoSendConfig.DEFAULT_MIN_RETRY_INTERVAL,
        ),
    )

    trigger_bulk_send_nexmo_robocall.delay(template_code, payloads, send_config)
    for retry in retries:
        if not isinstance(retry, time):
            logger.warning(
                {
                    **logger_data,
                    "message": "retry is not a time",
                    "template_code": template_code,
                    'total_payloads': len(payloads),
                    "retry": retry,
                }
            )
            continue

        next_trigger_time = trigger_time.replace(
            hour=retry.hour,
            minute=retry.minute,
            second=0,
            microsecond=0,
        )
        if next_trigger_time < now:
            logger.warning(
                {
                    **logger_data,
                    "message": "Next trigger time is in the past",
                    "template_code": template_code,
                    "total_payloads": len(payloads),
                    "trigger_time": str(trigger_time),
                    "next_trigger_time": str(next_trigger_time),
                }
            )
            continue

        send_config = NexmoSendConfig(
            trigger_time=next_trigger_time,
            max_retry=send_config.max_retry,
            min_retry_interval=send_config.min_retry_interval,
        )
        trigger_bulk_send_nexmo_robocall.apply_async(
            (template_code, payloads, send_config),
            eta=next_trigger_time,
        )
    return template_code


@task(bind=True, queue='collection_nexmo')
@payment_reminder_execution_time_limit
def trigger_bulk_send_nexmo_robocall(
    self,
    template_code: str,
    payloads: list,
    send_config: NexmoSendConfig,
):
    """
    This task focus on the validation of the data format before send the nexmo robocall.
    No DB query for this task.
    Args:
        self: Task instance
        template_code (str): Template code
        payloads (list): List of payloads
        send_config (NexmoSendConfig): nexmo sending configuration
    Returns:
        None
    """
    logger_data = {
        "action": "trigger_bulk_send_nexmo_robocall",
        "celery_task_id": self.request.id,
    }
    logger.info(
        {
            **logger_data,
            "message": "starting",
            'trigger_time': str(send_config.trigger_time),
            'template_code': template_code,
            'total_payloads': len(payloads),
        }
    )

    for payload in payloads:
        try:
            customer_data = NexmoCustomerData(
                customer_id=payload.get('customer_id'),
                account_payment_id=payload.get("account_payment_id"),
                phone_number=payload.get('phone_number'),
            )
        except TypeError as exc:
            logger.exception(
                {
                    **logger_data,
                    "message": "Invalid customer data",
                    "template_code": template_code,
                    "payload": payload,
                    "exc": str(exc),
                }
            )
            continue

        content = payload.get('content')
        if not content or not isinstance(content, list):
            logger.warning(
                {
                    **logger_data,
                    'message': 'Content is not a dict',
                    'template_code': template_code,
                    'payload': payload,
                }
            )
            get_julo_sentry_client().captureMessage(
                '[trigger_bulk_send_nexmo_robocall] Content is not a dict',
                extra={
                    'template_code': template_code,
                    'payload': payload,
                },
            )
            continue
        send_payment_reminder_nexmo_robocall.apply_async(
            (template_code, customer_data, content, send_config),
            max_retries=send_config.task_max_retry,
        )
    return


@task(bind=True, queue='collection_nexmo', max_retries=60)
@payment_reminder_execution_time_limit
def send_payment_reminder_nexmo_robocall(
    self,
    template_code: str,
    customer_data: NexmoCustomerData,
    content: list,
    send_config: NexmoSendConfig,
) -> Optional[int]:
    """
    Send Nexmo voice for payment reminder.
    The max_retry is relatively high because retry only happened if there is rate limit.
    Args:
        self: Task instance
        template_code (str): Template code
        customer_data (NexmoCustomerData): Customer data
        content (list): content (ncco_data) supported by Nexmo.
        send_config (NexmoSendConfig): Retry configuration
    Returns:
        int: VoiceCallRecord ID. Return None if not trigger nexmo voice call.
    """
    logger_data = {
        "action": "send_nexmo_robocall",
        "celery_task_id": self.request.id,
        "template_code": template_code,
    }
    # retry duration between 2 - 60 seconds
    retry_countdown = 2 + random.uniform(0, 58)
    if send_config.task_mock_retry:
        current_retry_count = 0
        if self.request and self.request.retries:
            current_retry_count = self.request.retries

        logger.info({**logger_data, "msg": "Retry for " + str(current_retry_count)})

        if current_retry_count <= send_config.task_mock_num_retry:
            raise self.retry(countdown=retry_countdown, max_retries=send_config.task_max_retry)

    redis_client = get_redis_client()

    # Quick Data validation
    customer_data.validate()
    send_config.validate()

    # Check the circuit breaker.
    if redis_client.get(NexmoVoiceRateLimit.PAYMENT_REMINDER_REDIS_KEY):
        raise self.retry(countdown=retry_countdown, max_retries=send_config.task_max_retry)

    # Check for retry,
    # 1. Do we need to retry?
    # 2. Should we skip the sending?
    now = timezone.localtime(timezone.now())
    account_payment_id = customer_data.account_payment_id
    is_retry_rule = False
    last_call = VoiceCallRecord.objects.get_last_call_by_template(template_code, account_payment_id)
    if last_call and send_config.trigger_time.date() == last_call.cdate.date():
        # Skip if no retry
        if not send_config.has_retry():
            return

        call_delay = now - last_call.cdate
        if not send_config.is_retry_allowed(call_delay):
            logger.warning(
                {
                    **logger_data,
                    "msg": "Retry is not allowed",
                    "account_payment_id": account_payment_id,
                    "call_delay": call_delay.total_seconds(),
                    "last_voice_call_record_id": last_call.id,
                }
            )
            return

        is_retry_rule = True

    # Set the robocall state to None if not retrying.
    if not is_retry_rule:
        AccountPayment.objects.filter(id=account_payment_id).update(
            is_collection_called=False,
            is_success_robocall=None,
        )

    account_payment = AccountPayment.objects.get(id=account_payment_id)
    if account_payment.is_paid or account_payment.due_amount == 0:
        return

    if account_payment.is_success_robocall or account_payment.is_collection_called:
        logger.warning(
            {
                **logger_data,
                "message": "Robocall is already sent",
                "account_payment_id": account_payment_id,
            }
        )
        return

    # Check fo rate limit
    is_rate_limited = sliding_window_rate_limit(
        NexmoVoiceRateLimit.PAYMENT_REMINDER_REDIS_KEY,
        NexmoVoiceRateLimit.PAYMENT_REMINDER,
        RateLimitTimeUnit.Seconds,
    )
    if is_rate_limited:
        logger.warning(
            {
                **logger_data,
                "message": "rate limit",
                "account_payment_id": customer_data.account_payment_id,
                "customer_id": customer_data.customer_id,
            }
        )
        # Trigger Circuit breaker
        redis_client.set(NexmoVoiceRateLimit.PAYMENT_REMINDER_REDIS_KEY, 1, ex=1),

        raise self.retry(countdown=retry_countdown, max_retries=send_config.task_max_retry)

    # Preparing Nexmo Voice Content
    logger.info(
        {
            **logger_data,
            "message": "preparing nexmo content",
            "account_payment_id": account_payment_id,
            "total_rate_limit_retry": self.request.retries,
        }
    )
    customer = (
        Customer.objects.filter(id=customer_data.customer_id)
        .only('product_line_id', 'current_application_id', 'gender')
        .last()
    )
    if not customer:
        raise ValueError(f"Customer not found: {customer_data.customer_id}")

    event_type = VoiceTypeStatus.PAYMENT_REMINDER
    nexmo_product = nexmo_product_type(customer.product_line_id)
    extra_url = '?product={}'.format(nexmo_product)
    input_webhook_url = ''.join(
        [
            settings.BASE_URL,
            '/api/integration/v1/callbacks/voice-call/',
            event_type,
            '/',
            str(account_payment_id),
            extra_url,
        ]
    )
    nexmo_content_sanitizer = NexmoVoiceContentSanitizer(
        content=content,
        customer=customer,
        input_webhook_url=input_webhook_url,
    )
    nexmo_content_sanitizer.sanitize()
    nexmo_content_sanitizer.add_record_action()

    # Send Nexmo Voice
    logger.info(
        {
            **logger_data,
            "message": "Sending nexmo robocall",
            "account_payment_id": account_payment_id,
            "customer_id": customer.id,
        }
    )
    comms_provider_lookup = CommsProviderLookup.objects.get(provider_name='Nexmo')
    voice_call_data = dict(
        template_code=template_code,
        event_type=event_type,
        application_id=customer.current_application_id,
        voice_identifier=account_payment_id,
        account_payment_id=account_payment_id,
        comms_provider_id=comms_provider_lookup.id,
        voice_style_id=nexmo_content_sanitizer.voice_style_id(),
    )
    phone_number = format_nexmo_voice_phone_number(customer_data.phone_number)
    nexmo_voice_client = get_voice_client_v2()
    try:
        response = nexmo_voice_client.create_call(
            phone_number=phone_number,
            application_id=customer.current_application_id,
            ncco_dict=nexmo_content_sanitizer.content,
            capture_sentry=False,
        )
    except Exception as error:
        logger.warning(
            {
                **logger_data,
                "message": "Failed to send nexmo robocall",
                "account_payment_id": account_payment_id,
                "customer_id": customer.id,
                "error": str(error),
            }
        )
        raise self.retry(
            countdown=retry_countdown, exc=error, max_retries=send_config.task_max_retry
        )

    # Saving the voice call record for tracking.
    voice_call_data.update(
        status=response.get('status'),
    )
    if response.get('conversation_uuid'):
        voice_call_data.update(
            direction=response['direction'],
            uuid=response['uuid'],
            conversation_uuid=response['conversation_uuid'],
        )
    else:
        logger.warning(
            {
                **logger_data,
                "message": "Failed to send nexmo robocall",
                "account_payment_id": account_payment,
                "customer_id": customer.id,
                "response": response,
            }
        )

    voice_call_record = VoiceCallRecord.objects.create(**voice_call_data)
    Reminder.create_j1_reminder_history(
        template=template_code,
        account_payment=account_payment,
        customer=customer,
        vendor=VendorConst.NEXMO,
        reminder_type=ReminderTypeConst.ROBOCALL_TYPE_REMINDER,
    )

    logger.info(
        {
            **logger_data,
            "message": "finished sending nexmo voice",
            "account_payment_id": account_payment_id,
            "customer_id": customer.id,
            "voice_call_record_id": voice_call_record.id,
            "total_rate_limit_retry": self.request.retries,
        }
    )
    return voice_call_record.id
