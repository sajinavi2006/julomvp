import logging
from builtins import str
from datetime import timedelta, datetime
from itertools import chain
from celery import task
from django.utils import timezone

from juloserver.minisquad.services2.genesys import store_genesys_call_result_to_skiptracehistory
from juloserver.monitors.notifications import notify_failed_manual_store_genesys_call_results

logger = logging.getLogger(__name__)


@task(queue="collection_dialer_normal")
def store_genesys_call_results(valid_data):
    now_tasks = timezone.now()
    logger.info({
        "action": "store_intelix_call_result_start",
        "time": timezone.localtime(now_tasks).strftime('%m/%d/%Y %I:%M:%S %p'),
        "data_count": len(valid_data)
    })
    failed_store = []
    for data in valid_data:
        try:
            is_success, message = store_genesys_call_result_to_skiptracehistory(
                data
            )
        except Exception as error:
            is_success = False
            message = str(error)

        if not is_success:
            failed_store.append(message)

    logger.info({
        "action": "manual_store_genesys_call_results",
        "time": timezone.localtime(timezone.now()).strftime('%m/%d/%Y %I:%M:%S %p'),
        "spent_time": "{}s".format((timezone.now() - now_tasks).seconds),
        "data_count": len(valid_data)
    })

    if failed_store:
        failed_message = "\n".join(failed_store)
        notify_failed_manual_store_genesys_call_results(failed_message)
