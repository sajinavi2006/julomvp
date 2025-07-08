import logging
import time

from celery.exceptions import MaxRetriesExceededError
from celery.task import task

from juloserver.comms.constants import NsqTopic
from juloserver.julo.clients import (
    get_nsq_producer,
    get_voice_client_v2,
)
from juloserver.julo.models import VoiceCallRecord
from juloserver.streamlined_communication.utils import payment_reminder_execution_time_limit

logger = logging.getLogger(__name__)


@task(
    name='vonage_rate_limit_call',
    queue='outbound_call_core',
    bind=True,
    default_retry_delay=2,
    max_retries=3,
)
@payment_reminder_execution_time_limit
def vonage_rate_limit_call(
    self,
    voice_call_record_id: int,
    phone_number: str,
    application_id: int,
    ncco_dict: dict,
    retry: int = 0,
    call_from: str = None,
    capture_sentry: bool = True,
    is_grab: bool = False,
):
    """
    Controls the RPS limitation when requesting API call to Vonage. This is relevant for Collection
    payment reminder account.

    Args:
        phone_number (str): Target for robocall.
        application_id (int): Application id of the customer used to rotate nexmo number.
        ncco_dict (dict): Contain data required for nexmo to process. Typically provided by
                        juloserver.julo.services2.get_voice_template
        retry (int): Number of retries. Reserved for retry mechanism.
        call_from (str): Number that Nexmo will use to call the target. @deprecated
        is_grab (bool): For logging purpose. Identify normal collection and grab collection.
    """
    log_data = {
        'action': 'vonage_rate_limit_call',
        'is_grab': is_grab,
    }

    try:
        logger.info(
            {
                'message': 'Requesting robocall to communication-service.',
                **log_data,
            }
        )
        vonage_client = get_voice_client_v2()
        call_from = vonage_client.randomize_call_number(application_id, call_from)

        timestamp = int(time.time())
        temporary_uuid = f"commtemp-{timestamp}-{voice_call_record_id}"

        nsq_producer = get_nsq_producer()
        nsq_data = {
            'auth_user_id': 1,  # This is registered in communication-service
            'client_call_uid': temporary_uuid,
            'to': phone_number,
            'from': call_from,
            'ncco': ncco_dict,
        }
        nsq_producer.publish_message(NsqTopic.send_robocall(), nsq_data)

        voice_call_record = VoiceCallRecord.objects.get(id=voice_call_record_id)
        voice_call_record.update_safely(uuid=temporary_uuid)

    except Exception as e:
        logger.info(
            {
                'error': e,
                'message': 'Fail sending. Retrying.',
                **log_data,
            }
        )
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError as e2:
            logger.info(
                {
                    'error': e2,
                    'message': 'Fail sending. Stop retrying.',
                    **log_data,
                }
            )

            return None


@task(
    name='vonage_rate_limit_call_dana',
    queue='outbound_call_dana',
    rate_limit='12/s',
    bind=True,
    default_retry_delay=2,
    max_retries=3,
)
@payment_reminder_execution_time_limit
def vonage_rate_limit_call_dana(
    self,
    voice_call_record_id: int,
    phone_number: str,
    application_id: int,
    ncco_dict: dict,
    retry: int = 0,
    call_from: str = None,
    capture_sentry: bool = True,
):
    """
    Controls the RPS limitation when requesting API call to Vonage. This is relevant for Collection
    payment reminder account.

    Args:
        phone_number (str): Target for robocall.
        application_id (int): Application id of the customer used to rotate nexmo number.
        ncco_dict (dict): Contain data required for nexmo to process. Typically provided by
                        juloserver.julo.services2.get_voice_template
        retry (int): Number of retries. Reserved for retry mechanism.
        call_from (str): Number that Nexmo will use to call the target. @deprecated
    """
    log_data = {
        'action': 'vonage_rate_limit_call_dana',
    }

    try:
        logger.info(
            {
                'message': 'Requesting robocall to communication-service.',
                **log_data,
            }
        )
        vonage_client = get_voice_client_v2()
        call_from = vonage_client.randomize_call_number(application_id, call_from)

        timestamp = int(time.time())
        temporary_uuid = f"commtemp-dana-{timestamp}-{voice_call_record_id}"

        nsq_producer = get_nsq_producer()
        nsq_data = {
            'auth_user_id': 2,  # This is registered in communication-service
            'client_call_uid': temporary_uuid,
            'to': phone_number,
            'from': call_from,
            'ncco': ncco_dict,
        }
        nsq_producer.publish_message(NsqTopic.send_robocall(), nsq_data)

        voice_call_record = VoiceCallRecord.objects.get(id=voice_call_record_id)
        voice_call_record.update_safely(uuid=temporary_uuid)
    except Exception as e:
        logger.info(
            {
                'error': e,
                'message': 'Fail sending. Retrying.',
                **log_data,
            }
        )
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError as e2:
            logger.info(
                {
                    'error': e2,
                    'message': 'Fail sending. Stop retrying.',
                    **log_data,
                }
            )
            return None
