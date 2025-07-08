from celery.task import task

from juloserver.monitors.services import get_channel_name_slack_for_payment_problem
from juloserver.monitors.notifications import get_slack_bot_client


@task(queue="repayment_normal")
def send_slack_alert_dana_biller(request_id, reason):
    channel_name = get_channel_name_slack_for_payment_problem()
    slack_message = (
        "Name - {}\n"
        "Request ID - {}\n"
        "Reason - {}".format("DANA Biller", request_id, reason)
    )
    get_slack_bot_client().api_call(
        "chat.postMessage", channel=channel_name, text=slack_message
    )
