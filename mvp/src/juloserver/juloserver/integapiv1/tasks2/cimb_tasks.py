from typing import (
    Optional,
)

from celery import task

from juloserver.monitors.services import get_channel_name_slack_for_payment_problem
from juloserver.monitors.notifications import get_slack_bot_client


@task(queue='repayment_low')
def send_slack_alert_cimb_payment_notification(
    error_message: str,
    payment_request_id: Optional[str] = None,
) -> None:
    slack_message = "Name - CIMB Niaga VA\n" \
                    "Transaction ID - {payment_request_id}\n" \
                    "Reason - {error_msg}". \
        format(
            payment_request_id=payment_request_id,
            error_msg=str(error_message),
        )
    channel_name = get_channel_name_slack_for_payment_problem()
    get_slack_bot_client().api_call(
        "chat.postMessage", channel=channel_name, text=slack_message
    )
