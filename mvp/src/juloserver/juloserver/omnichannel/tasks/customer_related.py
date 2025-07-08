from celery.task import task
from django.utils import timezone
from django.conf import settings
import logging

from requests import (
    HTTPError,
    RequestException,
)
from typing import List

from juloserver.julo.models import SkiptraceHistory, SkiptraceHistoryPDSDetail
from juloserver.minisquad.models import intelixBlacklist
from juloserver.omnichannel.models import (
    CustomerAttribute,
    OmnichannelCustomer,
    OmnichannelEventTrigger,
    OmnichannelPDSActionLog,
    OmnichannelPDSActionLogTask,
)
from juloserver.omnichannel.clients import get_omnichannel_http_client
from juloserver.omnichannel.services.settings import get_omnichannel_integration_setting
from juloserver.omnichannel.services.utils import exists_in_omnichannel_customer_sync

logger = logging.getLogger(__name__)


@task(bind=True, queue="omnichannel", max_retry=3)
def upload_device_attributes(self, customer_id: int, fcm_reg_id: str = None):
    """
    Upload device-related attribute to omnichannel service
    Args:
        self (celery.task.Task): The celery task object itself,
        customer_id (int): The primary key of customer,
        fcm_reg_id (str): The fcm_reg_id of the customer.
    """
    # Skip if the omnichannel integration is not active
    setting = get_omnichannel_integration_setting()
    if not setting.is_active:
        return

    # Skip the customer if the is_full_rollout is not active and
    # customer is not in OmnichannelCustomerSync
    if not setting.is_full_rollout and not exists_in_omnichannel_customer_sync(customer_id):
        return

    # Get the fcm_reg_id if not provided
    if fcm_reg_id is None:
        from juloserver.customer_module.services.device_related import DeviceRepository

        device_repository = DeviceRepository()
        fcm_reg_id = device_repository.get_active_fcm_id(customer_id)

    # construct and send the omnichannel customer attribute
    from juloserver.omnichannel.tasks import send_omnichannel_customer_attributes

    omnichannel_customer = OmnichannelCustomer(
        customer_id=str(customer_id),
        updated_at=timezone.now(),
        customer_attribute=CustomerAttribute(
            fcm_reg_id=fcm_reg_id,
        ),
    )
    send_omnichannel_customer_attributes(
        omnichannel_customers=[omnichannel_customer],
        celery_task=self,
    )


@task(bind=True, queue="omnichannel", max_retry=3)
def send_dialer_blacklist_customer_attribute(self, dialer_blacklist_id: int):
    """
    Update dialer_blacklisted_permanent and dialer_blacklisted_expiry_date
    attributes to the omnichannel service.
    Args:
        self (celery.task.Task): The celery task object itself,
        dialer_blacklist_id (int): The primary key of intelixBlacklist,
    """
    setting = get_omnichannel_integration_setting()
    if not setting.is_active:
        return

    dialer_blacklist = (
        intelixBlacklist.objects.select_related('account')
        .filter(id=dialer_blacklist_id, account__isnull=False)
        .only('account__customer_id', 'expire_date')
        .first()
    )
    if not dialer_blacklist:
        return

    if not setting.is_full_rollout and not exists_in_omnichannel_customer_sync(
        dialer_blacklist.account.customer_id
    ):
        return

    omnichannel_customer = OmnichannelCustomer(
        customer_id=str(dialer_blacklist.account.customer_id),
        updated_at=timezone.localtime(timezone.now()),
        customer_attribute=CustomerAttribute(
            dialer_blacklisted_permanent=not dialer_blacklist.expire_date,
            dialer_blacklisted_expiry_date=dialer_blacklist.expire_date,
        ),
    )

    from juloserver.omnichannel.tasks import send_omnichannel_customer_attributes

    send_omnichannel_customer_attributes(
        omnichannel_customers=[omnichannel_customer],
        celery_task=self,
    )


@task(bind=True, queue="omnichannel", max_retry=3)
def send_event_trigger(self, events: List[OmnichannelEventTrigger]):
    """
    Trigger the event to the omnichannel.
    Note that if the customer attribute is empty,
    the workflow automation will not be triggered.
    If you intend to trigger the workflow automation,
    but no customer attribute update is necessary,
    please just add customer_id to the customer attribute,
    so that it will still be triggered.
    If you want to trigger the event-based trigger campaign,
    please register the event type first to the omnichannel,
    otherwise it will not be triggered.
    For workflow automation,
    it isn't necessary to register the event_type first.
    Args:
        self (celery.task.Task): The celery task object itself,
        events List[OmnichannelEventTrigger]: List of events to be triggered,

    """
    retries_times = self.request.retries
    logger_data = {
        "action": "send_event_trigger",
        "events": events,
        "retries_times": retries_times,
    }
    setting = get_omnichannel_integration_setting()
    if not setting.is_active:
        return

    processed_events = [
        event
        for event in events
        if event.event_attribute.to_json_dict() or event.customer_attribute.to_json_dict()
    ]

    if not events:
        logger.warning(
            {
                "message": "Events is empty",
                "events": events,
                **logger_data,
            }
        )
        return

    try:
        logger.info(
            {
                "message": "Process sending event triggers",
                **logger_data,
            }
        )
        omnichannel_client = get_omnichannel_http_client()
        resp = omnichannel_client.send_event_trigger(processed_events)
        resp_body = resp.json()
        logger.info(
            {
                "message": "Finish event triggers",
                "response": resp_body,
                **logger_data,
            }
        )
    except HTTPError as e:
        resp = e.response
        if resp.status_code in [500, 503, 502, 429]:
            logger.warning(
                {
                    "message": "Retry event triggers",
                    "exc": e,
                    **logger_data,
                }
            )
            raise self.retry(exc=e, countdown=pow(3, retries_times))
    except RequestException as e:
        logger.warning(
            {
                "message": "Retry event triggers",
                "exc": e,
                **logger_data,
            }
        )
        raise self.retry(exc=e, countdown=pow(3, retries_times))


@task(bind=True, queue="omnichannel", max_retry=3)
def send_pds_action_log(self, action_logs: List[OmnichannelPDSActionLogTask]):
    """
    Send pds action log to omnichannel service.
    Args:
        self (celery.task.Task): The celery task object itself,
        skiptrace_history_id (int): The primary key of SkiptraceHistory,
    """
    retries_times = self.request.retries
    logger_data = {
        "action": "send_pds_action_log",
        "action_logs": action_logs,
        "total_action_logs": len(action_logs),
        "retries_times": retries_times,
    }
    setting = get_omnichannel_integration_setting()
    if not setting.is_active:
        return

    action_logs_dict = {action_log.skiptrace_history_id: action_log for action_log in action_logs}
    skiptrace_histories = SkiptraceHistory.objects.select_related('account', 'call_result').filter(
        id__in=action_logs_dict.keys(), account__isnull=False
    )
    if not skiptrace_histories:
        return

    skiptrace_history_ids = [skiptrace_history.id for skiptrace_history in skiptrace_histories]

    skiptrace_history_pds_details = SkiptraceHistoryPDSDetail.objects.filter(
        skiptrace_history_id__in=skiptrace_history_ids
    )
    skiptrace_history_pds_detail_dict = {
        obj.skiptrace_history_id: obj for obj in skiptrace_history_pds_details
    }

    action_logs = []
    for skiptrace_history in skiptrace_histories:
        skiptrace_history_pds_detail = skiptrace_history_pds_detail_dict.get(skiptrace_history.id)
        if not skiptrace_history_pds_detail:
            logger.warning(
                {
                    "message": "Omiting skiptrace_history",
                    "skiptrace_history_id": skiptrace_history.id,
                    **logger_data,
                }
            )
            continue
        level1 = skiptrace_history_pds_detail.customize_results.get('Level1') or 'NotConnected'
        level2 = (
            skiptrace_history_pds_detail.customize_results.get('Level2')
            or skiptrace_history_pds_detail.call_result_type
        )
        level3 = skiptrace_history_pds_detail.customize_results.get('Level3')
        action = ' - '.join(filter(None, [level1, level2, level3]))
        metadata = {
            'phone_number': str(skiptrace_history.skiptrace.phone_number),
            'start_ts': timezone.localtime(skiptrace_history.start_ts).isoformat(
                timespec='seconds'
            ),
        }
        action_log = action_logs_dict.get(skiptrace_history.id)
        if action_log.contact_source:
            metadata.update(contact_source=action_log.contact_source)
        task_name_arr = action_log.task_name.split('__')
        if len(task_name_arr) > 1 and task_name_arr[-1].strip() == 'OMNICHANNEL':
            metadata.update(
                bucket_name=task_name_arr[1 if settings.ENVIRONMENT.upper() != 'PROD' else 0]
            )
        action_logs.append(
            OmnichannelPDSActionLog(
                customer_id=str(skiptrace_history.account.customer_id),
                action=action,
                metadata=metadata,
            )
        )

    if not action_logs:
        logger.warning(
            {
                "message": "Action logs is empty",
                "skiptrace_history_id": skiptrace_history.id,
                **logger_data,
            }
        )
        return

    try:
        logger.info(
            {
                "message": "Process sending action log",
                **logger_data,
            }
        )
        omnichannel_client = get_omnichannel_http_client()
        resp = omnichannel_client.send_pds_action_log(action_logs)
        resp_body = resp.json()
        logger.info(
            {
                "message": "Finish sending action log",
                "response": resp_body,
                **logger_data,
            }
        )
    except HTTPError as e:
        resp = e.response
        if resp.status_code in [500, 503, 502, 429]:
            logger.warning(
                {
                    "message": "Retry sending action log",
                    "exc": e,
                    **logger_data,
                }
            )
            raise self.retry(exc=e, countdown=30 * (1 + retries_times))
    except RequestException as e:
        logger.warning(
            {
                "message": "Retry sending action log",
                "exc": e,
                **logger_data,
            }
        )
        raise self.retry(exc=e, countdown=30 * (1 + retries_times))
