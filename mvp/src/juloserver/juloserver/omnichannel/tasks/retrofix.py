import traceback
import logging
from datetime import datetime
from builtins import str
from django.utils import timezone

from celery.task import task
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.monitors.notifications import get_slack_sdk_web_client


logger = logging.getLogger(__name__)
FEATURE_RETROFIX_AUTODEBET = 'send_automated_comm_sms_j1_autodebet_only'


@task(queue="omnichannel")
def send_automated_comm_sms_j1_autodebet_only_scheduler():
    fs = FeatureSettingHelper(FEATURE_RETROFIX_AUTODEBET)
    if not fs.is_active:
        return

    from juloserver.julo.tasks import send_automated_comm_sms_j1_autodebet_only

    today = timezone.localtime(timezone.now())
    date_of_day = today.date()

    start_date = fs.get('start_date', '2025-02-01')
    end_date = fs.get('end_date', '2025-03-31')

    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()

    if date_of_day < start_date_obj or date_of_day > end_date_obj:
        return

    slack_channel = fs.get('slack_channel')
    thread_ts = fs.get('thread_ts')

    # mock function, for testing purposes
    # case: to test whether the scheduler is run or not without explicitly send sms
    mock_return = fs.get('mock_return', False)

    streamlined_comm_ids = fs.get('streamlined_comm_ids', [524, 526, 789, 794])
    for s in streamlined_comm_ids:
        if mock_return:
            res = {
                'template_code': 'template_{}'.format(str(s)),
                'total_sent': 100,
                'total_customer': 1000,
                'total_non_autodebet': 1000,
                'total_experiment': 1000,
            }
        else:
            res = send_automated_comm_sms_j1_autodebet_only(s)
        slack_message = "*Template: {}* - send_automated_comm_sms_j1_autodebet_only (streamlined_id - {}) ".format(  # noqa
            str(res.get('template_code', '')), str(s)
        )
        slack_message += "Total sent: {} | ".format(res.get('total_sent'))
        slack_message += "Total customer: {} | ".format(res.get('total_customer'))
        slack_message += "Total non autodebet: {} | ".format(res.get('total_non_autodebet'))
        slack_message += "Total experiment: {} | ".format(res.get('total_experiment'))
        send_retrofix_result(slack_channel, thread_ts, slack_message)


def send_retrofix_result(channel: str, thread_ts: str, text_to_send: str):
    try:
        slack_client = get_slack_sdk_web_client()
        if not text_to_send:
            return
        resp = slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=text_to_send,
        )
        if resp and not resp.get('ok', False):
            logger.error(
                {
                    "action": "send_retrofix_result",
                    "message": str(resp or ""),
                    "level": "error",
                }
            )
    except Exception:
        logger.error(
            {
                "action": "send_retrofix_result",
                "message": traceback.format_exc(),
                "level": "error",
            }
        )
