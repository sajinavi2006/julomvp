import logging
from celery import task
from django.utils import timezone
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from juloserver.account.services.account_related import (
    update_ever_entered_b5_account_level_base_on_account_payment
)
from juloserver.account_payment.models import AccountPayment
from juloserver.collection_vendor.constant import Bucket5Threshold
from juloserver.julo.models import Payment
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.constants import RedisKey
from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids

logger = logging.getLogger(__name__)


@task(queue="collection_dialer_high")
def change_ever_entered_b5():
    fn_name = 'change_ever_entered_b5'
    logger.info({'action': fn_name, 'message': 'task begin'})
    today = timezone.localtime(timezone.now()).date()
    due_date_for_91 = today - relativedelta(days=Bucket5Threshold.DPD_REACH_BUCKET_5)
    payment_ever_crossed_91 = Payment.objects.select_related('loan').not_paid_active().filter(
        due_date__lte=due_date_for_91, loan__ever_entered_B5=False,
        account_payment__isnull=True
    )
    for payment in payment_ever_crossed_91:
        loan = payment.loan
        # to handle 2 payment with same loan_id and dpd >= 101
        if loan.ever_entered_B5:
            continue

        loan.update_safely(
            ever_entered_B5=True
        )
    # trigger chain
    set_ever_entered_b5_j1.delay()
    logger.info({'action': fn_name, 'message': 'task finish'})


@task(queue="collection_dialer_high")
def set_ever_entered_b5_j1():
    fn_name = 'set_ever_entered_b5_j1'
    logger.info({'action': fn_name, 'message': 'task begin'})
    # for set is_ever_entered_b5 on account level when ever its goes to dpd 91
    redisClient = get_redis_client()
    cached_oldest_account_payment_ids = redisClient.get_list(
        RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

    today = timezone.localtime(timezone.now()).date()
    due_date_reach_bucket_5 = today - timedelta(days=Bucket5Threshold.DPD_REACH_BUCKET_5)
    account_payment_ids_reach_b5 = AccountPayment.objects.select_related(
        'account').not_paid_active().filter(
        account__ever_entered_B5=False, id__in=oldest_account_payment_ids
    ).filter(due_date__lte=due_date_reach_bucket_5).values_list('id', flat=True)
    for account_payment_id in account_payment_ids_reach_b5:
        set_ever_entered_b5_j1_sub_task.delay(account_payment_id)
    logger.info({'action': fn_name, 'message': 'task finish'})


@task(queue="collection_dialer_normal")
def set_ever_entered_b5_j1_sub_task(account_payment_id):
    fn_name = 'set_ever_entered_b5_j1_sub_task'
    logger.info({'action': fn_name, 'message': 'task begin'})
    account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
    if not account_payment:
        return

    update_ever_entered_b5_account_level_base_on_account_payment(account_payment)
    logger.info({'action': fn_name, 'message': 'task finish'})
