from celery import task
import logging
from typing import Optional

from django.conf import settings
from django.utils import timezone

from juloserver.monitors.notifications import (
    get_slack_bot_client,
    send_slack_bot_message,
)

from juloserver.dana_linking.models import (
    DanaWalletAccount,
    DanaWalletBalanceHistory,
)
from juloserver.dana_linking.constants import DanaWalletAccountStatusConst
from juloserver.dana_linking.services import get_dana_balance_amount

from juloserver.account_payment.models import RepaymentApiLog

logger = logging.getLogger(__name__)


@task(queue='repayment_low')
def send_slack_notification(
    account_id: int, application_id: int, reason: str, url: Optional[str] = ""
) -> None:
    streamer = ""
    if settings.ENVIRONMENT != 'prod':
        streamer = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())

    slack_error_message = (
        "url - {}\n"
        "Account ID - {}\n"
        "Application ID - {}\n"
        "Reason - {}".format(url, account_id, application_id, reason)
    )
    slack_messages = streamer + slack_error_message
    get_slack_bot_client().api_call(
        "chat.postMessage", channel="#dana_ewallet_alert ", text=slack_messages
    )


@task(queue='repayment_normal')
def update_dana_balance():
    today = timezone.localtime(timezone.now())
    dana_wallet_accounts = DanaWalletAccount.objects.filter(
        status=DanaWalletAccountStatusConst.ENABLED,
        access_token__isnull=False,
        access_token_expiry_time__gt=today,
    ).only('id')
    for dana_wallet_account in dana_wallet_accounts.iterator():
        update_dana_balance_subtask.delay(dana_wallet_account.id)


@task(queue='repayment_normal', rate_limit='4/s')
def update_dana_balance_subtask(dana_wallet_account_id: int):
    logger.info(
        {
            'action': 'juloserver.dana_linking.tasks.update_dana_balance_subtask',
            'dana_wallet_account_id': dana_wallet_account_id,
        }
    )
    dana_wallet_account = (
        DanaWalletAccount.objects.select_related('account__customer')
        .filter(pk=dana_wallet_account_id)
        .first()
    )
    customer = dana_wallet_account.account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid
    device = customer.device_set.last()
    balance_amount = get_dana_balance_amount(dana_wallet_account, device.android_id, customer_xid)
    DanaWalletBalanceHistory.objects.create(
        dana_wallet_account_id=dana_wallet_account_id, balance=balance_amount
    )


@task(queue='repayment_low')
def store_repayment_api_log(
    request_type: str,
    http_status_code: int,
    vendor: str,
    error_message: Optional[str] = None,
    application_id: Optional[int] = None,
    account_id: Optional[int] = None,
    response: Optional[str] = None,
    account_payment_id: Optional[int] = None,
    request: Optional[str] = None,
) -> None:
    RepaymentApiLog.objects.create(
        application_id=application_id,
        account_id=account_id,
        account_payment_id=account_payment_id,
        request_type=request_type,
        http_status_code=http_status_code,
        request=request,
        response=response,
        error_message=error_message,
        vendor=vendor,
    )


@task(queue='repayment_normal')
def send_dana_payment_disable_slack_notification(slack_message):
    if settings.ENVIRONMENT != 'prod':
        slack_message = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_message
        )

    logger.info(
        {
            'action': 'juloserver.dana_linking.tasks.send_dana_payment_disable_slack_notification',
            'message': slack_message,
        }
    )
    send_slack_bot_message("#dana_ewallet_alert", slack_message)
