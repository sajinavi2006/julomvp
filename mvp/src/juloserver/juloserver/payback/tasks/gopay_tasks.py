import datetime
import logging
from datetime import timedelta

from celery.task import task
from django.utils import timezone

from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.services.account_services import (
    is_autodebet_gopay_feature_active,
    is_autodebet_feature_disable,
    get_autodebet_dpd_deduction,
)
from juloserver.payback.client import get_gopay_client
from juloserver.payback.constants import GopayTransactionStatusConst
from juloserver.payback.exceptions import GopayError
from juloserver.payback.models import (
    GopayCustomerBalance,
    GopayAccountLinkStatus,
    GopayAutodebetTransaction
)

logger = logging.getLogger(__name__)


@task(queue="repayment_normal")
def update_gopay_balance_task():
    """
    Update customers gopay balance task.

    Args:
        None

    Returns:
        None
    """
    logger.info(
        {
            'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_task',
            'message': 'task begin',
        }
    )
    today = timezone.localtime(timezone.now()).date()
    gopay_balance_pay_account_ids = GopayCustomerBalance.objects.filter(
        cdate__date=today
    ).values_list('gopay_account', flat=True)
    gopay_account_ids = (
        GopayAccountLinkStatus.objects.filter(status='ENABLED')
        .exclude(id__in=gopay_balance_pay_account_ids)
        .values_list('id', flat=True)
    )

    for gopay_account_id in gopay_account_ids:
        update_gopay_balance_subtask.delay(gopay_account_id)


@task(queue="repayment_normal")
def update_gopay_balance_subtask(gopay_account_id):
    """
    Update customer gopay balance subtask.

    Args:
        gopay_account_id (int): The ID of the gopay account link status.

    Returns:
        If gopay wallet not exists return None, 'Gopay wallet not provided'
        else None
    """
    logger.info(
        {
            'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
            'gopay_account_id': gopay_account_id,
            'message': 'subtask begin',
        }
    )
    gopay_client = get_gopay_client()
    gopay_account = GopayAccountLinkStatus.objects.filter(id=gopay_account_id).last()
    if not gopay_account:
        logger.error(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'gopay_account_id is not found',
                'gopay_account_id': gopay_account_id,
            }
        )
        return

    res_data = gopay_client.get_pay_account(gopay_account.pay_account_id)
    if not (res_data.get('account_status') == 'ENABLED'):
        logger.error(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'account_status is not enabled',
                'data': res_data,
            }
        )
        return
    metadata = res_data.get('metadata', {})
    gopay_wallet = next(
        (item for item in metadata.get('payment_options', []) if item['name'] == 'GOPAY_WALLET'),
        None,
    )
    if not gopay_wallet:
        logger.error(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'Gopay wallet not provided',
                'data': res_data,
            }
        )
        return None, 'Gopay wallet not provided'

    gopay_balance = int(float(gopay_wallet['balance']['value']))

    GopayCustomerBalance.objects.create(
        gopay_account=gopay_account,
        is_active=gopay_wallet['active'],
        balance=gopay_balance,
        account=gopay_account.account,
    )


@task(queue="repayment_normal")
def gopay_autodebet_retry_mechanism():
    from juloserver.autodebet.services.authorization_services import check_gopay_wallet_token_valid
    from juloserver.autodebet.services.task_services import (
        get_due_amount_for_gopay_autodebet_deduction,
        get_gopay_wallet_customer_balance,
        update_gopay_wallet_customer_balance,
    )

    gopay_client = get_gopay_client()
    today_date = timezone.localtime(timezone.now()).date()
    if not is_autodebet_gopay_feature_active():
        return

    if is_autodebet_feature_disable(AutodebetVendorConst.GOPAY):
        return

    dpd_start, dpd_end = get_autodebet_dpd_deduction(vendor=AutodebetVendorConst.GOPAY)
    deny_gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
        is_active=False,
        cdate__date__range=[today_date - timedelta(days=1), today_date],
        status=GopayTransactionStatusConst.DENY
    )

    partial_gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
        is_active=False,
        cdate__date=today_date - timedelta(days=1),
        is_partial=True
    ).exclude(id__in=deny_gopay_autodebet_transactions.values_list('id', flat=True))

    if not deny_gopay_autodebet_transactions and not partial_gopay_autodebet_transactions:
        return

    gopay_autodebet_transactions = []
    for deny_gopay_autodebet_transaction in deny_gopay_autodebet_transactions:
        gopay_autodebet_transactions.append(deny_gopay_autodebet_transaction)

    for partial_gopay_autodebet_transaction in partial_gopay_autodebet_transactions:
        gopay_autodebet_transactions.append(partial_gopay_autodebet_transaction)

    if not gopay_autodebet_transactions:
        return

    for gopay_autodebet_transaction in gopay_autodebet_transactions:
        now = timezone.localtime(timezone.now())

        retry_gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
            gopay_account=gopay_autodebet_transaction.gopay_account,
            cdate__range=[now.date(), now], is_active=True,
        ).last()

        if retry_gopay_autodebet_transaction:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.'
                    'gopay_autodebet_retry_mechanism',
                    'error': 'subscription sudah dibuat dihari ini',
                    'data': {
                        'account_id': retry_gopay_autodebet_transaction.\
                             gopay_account.account.id
                    }
                }
            )
            continue

        account_payment = gopay_autodebet_transaction.account_payment

        if not (dpd_start <= account_payment.dpd <= dpd_end + 1):
            continue

        is_autodebet_active = AutodebetAccount.objects.filter(
            is_use_autodebet=True,
            vendor=AutodebetVendorConst.GOPAY,
            account=account_payment.account,
            is_suspended=False,
        ).exists()

        if not is_autodebet_active:
            continue

        result = check_gopay_wallet_token_valid(account_payment.account)

        if not result:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.gopay_autodebet_retry_mechanism',
                    'account_id': account_payment.account.id,
                    'error': 'GopayAccountLinkStatus not found',
                }
            )
            continue

        token = result[1]

        amount = get_due_amount_for_gopay_autodebet_deduction(account_payment.account)

        if not amount:
            continue

        # Fetch and update subscripiton due_amount based on customer balance
        customer_balance = get_gopay_wallet_customer_balance(
            gopay_autodebet_transaction.gopay_account.pay_account_id)
        if customer_balance is None:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.gopay_autodebet_retry_mechanism',
                    'account_id': account_payment.account.id,
                    'error': 'Gopay wallet customer balance not found',
                }
            )
            continue
        update_gopay_wallet_customer_balance(account_payment.account, customer_balance)

        if account_payment.dpd > 0:
            if customer_balance < 10000:
                continue

        deduction_amount = amount
        if customer_balance > 1 and amount > customer_balance:
            deduction_amount = customer_balance

        next_execution = now + timedelta(minutes=5)
        next_execution_at = next_execution.strftime("%Y-%m-%d %H:%M:%S %z")

        request_data = {
            'name': gopay_autodebet_transaction.name,
            'amount': deduction_amount,
            'currency': 'IDR',
            'token': token,
            'schedule': {
                'next_execution_at': next_execution_at
            }
        }

        try:
            gopay_client.update_subscription_gopay_autodebet(
                gopay_autodebet_transaction,
                request_data
            )
        except GopayError as error:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.gopay_autodebet_retry_mechanism',
                    'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id,
                    'error': error,
                }
            )
            continue

        GopayAutodebetTransaction.objects.create(
            subscription_id=gopay_autodebet_transaction.subscription_id,
            name=gopay_autodebet_transaction.name,
            gopay_account=gopay_autodebet_transaction.gopay_account,
            amount=amount,
            customer=gopay_autodebet_transaction.customer,
            is_active=True,
            account_payment=account_payment,
            is_partial=False
        )

        logger.info(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.gopay_autodebet_retry_mechanism',
                'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id,
                'request_data': request_data,
                'message': 'Retry attempt',
            }
        )


@task(queue='repayment_normal')
def update_overlap_subscription():
    now = timezone.localtime(timezone.now())

    GopayAutodebetTransaction.objects.filter(
        cdate__date=now.date() - datetime.timedelta(days=1)
    ).exclude(status=GopayTransactionStatusConst.SETTLEMENT).update(
        status=GopayTransactionStatusConst.EXPIRED, is_active=False)


@task(queue='repayment_normal')
def update_subscription(gopay_autodebet_transaction_list):
    # circular import
    from juloserver.autodebet.services.authorization_services import check_gopay_wallet_token_valid
    from juloserver.autodebet.services.task_services import \
        get_due_amount_for_gopay_autodebet_deduction

    gopay_client = get_gopay_client()
    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
        pk__in=gopay_autodebet_transaction_list
    )
    hour = 22
    now = timezone.localtime(timezone.now())

    for gopay_autodebet_transaction in gopay_autodebet_transactions:
        account_payment = gopay_autodebet_transaction.account_payment
        amount = get_due_amount_for_gopay_autodebet_deduction(account_payment.account)

        if not amount:
            continue

        if now.date() < account_payment.due_date:
            hour = 17
        else:
            if now.time() < datetime.time(9, 50, 0):
                hour = 17

        next_execution_time = account_payment.due_date.strftime(
            "%Y-%m-%d") + ' ' + timezone.localtime(now.replace(hour=hour, minute=0, second=0))\
            .strftime("%H:%M:%S %z")

        result = check_gopay_wallet_token_valid(account_payment.account)

        if not result:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.update_subscription',
                    'account_id': account_payment.account.id,
                    'error': 'GopayAccountLinkStatus not found',
                }
            )
            continue

        token = result[1]
        request_data = {
            'name': gopay_autodebet_transaction.name,
            'amount': amount,
            'currency': 'IDR',
            'token': token,
            'schedule': {
                'next_execution_at': next_execution_time
            }
        }

        try:
            gopay_client.update_subscription_gopay_autodebet(
                gopay_autodebet_transaction,
                request_data
            )
        except GopayError as error:
            logger.error(
                {
                    'action': 'juloserver.payback.tasks.gopay_tasks.update_subscription',
                    'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id,
                    'error': error,
                }
            )
            continue

        gopay_autodebet_transaction.update_safely(
            is_active=True,
            forced_inactive_by_julo=False,
            amount=amount
        )
