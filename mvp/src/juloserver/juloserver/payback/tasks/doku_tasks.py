from typing import (
    Optional,
)

from celery import task

from juloserver.monitors.services import get_channel_name_slack_for_payment_problem
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.payback.models import DokuVirtualAccountSuffix
from juloserver.julo.constants import VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT
from django.db.models import Max
from juloserver.integapiv1.services import get_last_va_suffix
from juloserver.pii_vault.constants import PiiSource
import logging


logger = logging.getLogger(__name__)

@task(queue='repayment_low')
def send_slack_alert_doku_payment_notification(
    error_message: str,
    payment_request_id: Optional[str] = None,
) -> None:
    slack_message = (
        "Name - DOKU VA\n"
        "Transaction ID - {payment_request_id}\n"
        "Reason - {error_msg}".format(
            payment_request_id=payment_request_id,
            error_msg=str(error_message),
        )
    )
    channel_name = get_channel_name_slack_for_payment_problem()
    get_slack_bot_client().api_call("chat.postMessage", channel=channel_name, text=slack_message)


@task(queue='repayment_high')
def populate_doku_virtual_account_suffix():
    count_va_suffix_unused = DokuVirtualAccountSuffix.objects.filter(
        loan_id=None, line_of_credit_id=None, account_id=None
    ).count()
    # generate virtual_account_suffix if unused count is less
    if count_va_suffix_unused <= VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT:
        batch_size = 1000
        last_virtual_account_suffix = get_last_va_suffix(
            DokuVirtualAccountSuffix,
            'virtual_account_suffix',
            PiiSource.DOKU_VIRTUAL_ACCOUNT_SUFFIX,
        )

        start_range = last_virtual_account_suffix + 1
        max_count = VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT
        end_range = start_range + max_count + 1

        doku_va_suffix_objs = (
            DokuVirtualAccountSuffix(virtual_account_suffix=str(va_suffix_val).zfill(7))
            for va_suffix_val in range(start_range, end_range)
        )
        DokuVirtualAccountSuffix.objects.bulk_create(doku_va_suffix_objs, batch_size)

        logger.info(
            {
                'action': 'populate_doku_virtual_account_suffix',
                'message': 'successfully populated the doku virtual account suffix',
            }
        )
