from __future__ import absolute_import

import json
import logging
import re
from datetime import date, timedelta

from celery import task
from django.utils import timezone
from redis.exceptions import LockError

from juloserver.account.constants import AccountConstant
from juloserver.account.constants import RedisKey as AccountRedis
from juloserver.account.models import AccountStatusHistory
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account.services.account_transaction import (
    update_account_transaction_towards_late_fee,
)
from juloserver.julo.models import PaymentEvent, ProductLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.julo.constants import FeatureNameConst, BucketConst, WorkflowConst
from juloserver.julo.models import FeatureSetting
from dateutil.relativedelta import relativedelta
from juloserver.account_payment.models import AccountPayment, LateFeeRule
from juloserver.minisquad.constants import DialerServiceTeam, RedisKey
from juloserver.minisquad.models import AccountBucketHistory
from juloserver.minisquad.utils import batch_pk_query_with_cursor
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services import record_data_for_cashback_new_scheme
from juloserver.julo.constants import NewCashbackReason
from juloserver.account_payment.services.earning_cashback import (
    get_due_date_for_cashback_new_scheme,
)

logger = logging.getLogger(__name__)


@task(queue="repayment_high")
def update_account_transaction_for_late_fee_event(payment_id):
    """
    create account transaction for every day for late_fee payment events.
    """
    late_fee_payment_events = PaymentEvent.objects.filter(
        event_date=date.today(),
        event_type='late_fee',
        payment__account_payment__isnull=False,
        payment_id=payment_id,
        account_transaction__isnull=True,
    )

    for payment_event_id in late_fee_payment_events.values_list("id", flat=True):
        update_account_transaction_for_late_fee_event_subtask(payment_event_id)


@task(queue='repayment_high')
def update_account_transaction_for_late_fee_event_subtask(payment_event_id, times_retried=1):
    logger.info(
        {
            "task": "update_account_transaction_for_late_fee_event_subtask",
            "payment_event_id": payment_event_id,
            "action": "starting",
        }
    )
    payment_event = PaymentEvent.objects.get_or_none(pk=payment_event_id)
    if payment_event.payment.account_payment:
        redis_client = get_redis_client()
        lock = redis_client.lock(
            AccountRedis.ACCOUNT_TRANSACTION_LOCK.format(
                payment_event.payment.account_payment.account.id
            ),
            timeout=30 * times_retried,  # The maximum time to hold the lock
            sleep=1,  # Sleep time between each retry
        )
        try:
            with lock:
                update_account_transaction_towards_late_fee(payment_event=payment_event)
                logger.info(
                    {
                        "task": "update_account_transaction_for_late_fee_event_subtask",
                        "payment_event_id": payment_event_id,
                        "update_success": "success",
                    }
                )
        except LockError as e:
            if times_retried <= 3:
                update_account_transaction_for_late_fee_event_subtask.apply_async(
                    args=[payment_event_id, times_retried + 1],
                    countdown=30 * (times_retried + 1),
                )
            else:
                raise Exception("maximum retries reached" + str(e))


@task(queue='collection_normal')
def reactivate_account_after_suspended_task():
    fs = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.ACCOUNT_REACTIVATION_SETTING,
        is_active=True,
    )
    params = fs.parameters
    period_day = params.get('special_criteria', {}).get('day', 90)

    statuses = {
        "R4 cool off period": "post R4 cool off period completed",
        "refinancing cool off period": "post refinancing cool off period completed",
    }
    post_cool_off_threshold = timezone.localtime(timezone.now()).date() - timedelta(days=period_day)
    account_status_histories = AccountStatusHistory.objects.filter(
        status_new=AccountConstant.STATUS_CODE.suspended,
        change_reason__in=statuses.keys(),
        cdate__date__lte=post_cool_off_threshold,
        account__status__status_code=AccountConstant.STATUS_CODE.suspended,
        is_reactivable=True,
    )

    for account_status_history in account_status_histories:
        account = account_status_history.account
        account_status_history.update_safely(is_reactivable=False)
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.active,
            statuses[account_status_history.change_reason],
        )

    r4_account_post_cool_off_period = (
        LoanRefinancingRequest.objects.filter(
            status=CovidRefinancingConst.STATUSES.activated,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            offer_activated_ts__date=post_cool_off_threshold,
            account__status_id=AccountConstant.STATUS_CODE.suspended,
        )
        .exclude(
            account_id__in=list(
                account_status_histories.distinct('account_id').values_list('account_id', flat=True)
            )
        )
        .distinct('account')
        .order_by('account', '-cdate')
    )
    for loan_refinancing_req in r4_account_post_cool_off_period:
        account = loan_refinancing_req.account
        process_change_account_status(
            account, AccountConstant.STATUS_CODE.active, statuses["R4 cool off period"]
        )


@task(queue='collection_normal')
def cashback_new_scheme_break():
    """
    this task for reset cashback counter customer, who has passed due date based on
    dpd on feature setting
    """
    fn_name = 'cashback_new_scheme_break'
    logger.info(
        {
            'action': fn_name,
            'message': 'task begin',
        }
    )

    due_date_cashback = get_due_date_for_cashback_new_scheme()
    today = timezone.localtime(timezone.now()).date()
    date = today + relativedelta(days=abs(due_date_cashback))
    query = AccountPayment.objects.oldest_account_payment().filter(
        due_date__lt=date, account__cashback_counter__gt=0
    ).values_list('id')

    split_threshold = 2500
    for batched_eligible_account_payment_ids in batch_pk_query_with_cursor(
        query, batch_size=split_threshold
    ):
        cashback_new_scheme_break_subtask.delay(batched_eligible_account_payment_ids)
        logger.info(
            {
                'action': fn_name,
                'message': 'sent to async task',
            }
        )

    logger.info(
        {
            'action': fn_name,
            'message': 'task finish',
        }
    )


@task(queue='collection_normal')
def cashback_new_scheme_break_subtask(account_payment_ids):
    fn_name = 'cashback_new_scheme_break_subtask'
    logger.info(
        {
            'action': fn_name,
            'message': 'task begin',
        }
    )
    for account_payment_id in account_payment_ids:
        logger.info(
            {
                'action': fn_name,
                'account_payment_id': account_payment_id,
                'message': 'processing',
            }
        )
        try:
            account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
            account = account_payment.account
            if not account.is_eligible_for_cashback_new_scheme or account.cashback_counter < 1:
                continue
            payments = account_payment.payment_set.filter(due_amount__gt=0)
            for payment in payments.iterator():
                # create new row for cashback counter history
                record_data_for_cashback_new_scheme(
                    payment, None, 0, NewCashbackReason.PAID_AFTER_TERMS
                )

            # update cashback counter to 0
            account_payment.account.cashback_counter = 0
            account_payment.account.save()
        except Exception as err:
            logger.error(
                {
                    'action': fn_name,
                    'account_payment_id': account_payment_id,
                    'message': str(err),
                }
            )
            get_julo_sentry_client().captureException()
            continue
    logger.info(
        {
            'action': fn_name,
            'message': 'task finish',
        }
    )


@task(queue="collection_dialer_high")
def account_bucket_history_querying():
    """
    this task is for flagging account if they already reach some sort of bucket
    """
    fn_name = 'account_bucket_history_querying'
    logger.info({'action': fn_name, 'message': 'task begin'})
    eligible_dpd = {
        BucketConst.BUCKET_6_1_DPD['from']: DialerServiceTeam.JULO_B6_1,
    }
    already_marked_query_exclusion = """
                NOT EXISTS (
                    SELECT 1
                    FROM "account_bucket_history" abh
                    WHERE abh.account_id = account_payment.account_id
                    AND abh."bucket_name" = %s
                )
            """
    redis_client = get_redis_client()
    today = timezone.localtime(timezone.now()).date()
    for dpd, bucket_name in eligible_dpd.items():
        # this code for reset account id list bucket history
        redis_key = RedisKey.ACCOUNT_ID_BUCKET_HISTORY.format(bucket_name)
        redis_client.delete_key(redis_key)

        logger.info(
            {
                'action': fn_name,
                'message': 'query begin for dpd {} bucket {}'.format(dpd, bucket_name),
            }
        )
        due_date = today - timedelta(days=dpd)
        account_ids_eligible_today = list(
            AccountPayment.objects.select_related('account')
            .not_paid_active()
            .filter(
                due_date=due_date,
                account__account_lookup__workflow__name__in=(
                    WorkflowConst.JULO_ONE,
                    WorkflowConst.JULO_STARTER,
                    WorkflowConst.JULO_ONE_IOS,
                ),
            )
            .extra(where=[already_marked_query_exclusion], params=[bucket_name])
            .values_list('account_id', flat=True)
        )
        logger.info(
            {
                'action': fn_name,
                'message': 'finish query for dpd {} bucket {} with data {}'.format(
                    dpd, bucket_name, len(account_ids_eligible_today)
                ),
            }
        )
        if not account_ids_eligible_today:
            continue

        redis_client.set_list(redis_key, account_ids_eligible_today, timedelta(hours=4))
        account_bucket_history_creation.delay(redis_key, bucket_name)

    logger.info({'action': fn_name, 'message': 'task finish'})


@task(queue="collection_dialer_high")
def account_bucket_history_creation(redis_key, bucket_name):
    """
    this task is for insert into account bucket history with bulk insert
    """
    fn_name = 'account_bucket_history_creation'
    logger.info({'action': fn_name, 'message': 'task begin {}'.format(bucket_name)})
    redis_client = get_redis_client()
    cached_account_ids = redis_client.get_list(redis_key)
    if not cached_account_ids:
        logger.info({'action': fn_name, 'message': 'failed run task for {}'.format(bucket_name)})
        return

    cached_account_ids = list(map(int, cached_account_ids))
    current_time = timezone.localtime(timezone.now())
    # bathing data creation prevent full memory
    batch_size = 500
    counter = 0
    processed_data_count = 0
    bucket_history_data = []
    # implementing experiment for b5
    for account_id in cached_account_ids:
        bucket_history_data.append(
            AccountBucketHistory(
                account_id=account_id, bucket_name=bucket_name, reached_at=current_time
            )
        )
        counter += 1

        # Check if the batch size is reached, then perform the bulk_create
        if counter >= batch_size:
            AccountBucketHistory.objects.bulk_create(bucket_history_data)
            processed_data_count += counter
            # Reset the counter and the list for the next batch
            counter = 0
            bucket_history_data = []

    # Insert any remaining objects in the final batch
    if bucket_history_data:
        processed_data_count += counter
        AccountBucketHistory.objects.bulk_create(bucket_history_data)

    redis_client.delete_key(redis_key)
    logger.info({'action': fn_name, 'message': 'task finish {}'.format(bucket_name)})


@task(queue="repayment_normal")
def late_fee_rule_creation(late_fee_rule_params):
    parameters = json.loads(late_fee_rule_params)
    max_late_fee = max(list(parameters.values()))
    late_fee_rule = LateFeeRule.objects.all().values_list('product_lookup', flat=True)
    product_lookups = ProductLookup.objects.filter(
        product_line_id__in=[
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
        ],
    ).exclude(pk__in=late_fee_rule)
    today = timezone.localtime(timezone.now())
    late_fee_product_name = "L." + str(max_late_fee).replace(".", "").zfill(3)
    for product_lookup in product_lookups:
        product_lookup.cdate = today
        product_lookup.udate = today
        product_lookup.pk = None
        product_lookup.product_name = re.sub(
            r"L\.\d{3}", late_fee_product_name, product_lookup.product_name
        )
        product_lookup.late_fee_pct = max_late_fee
        product_lookup.save()
        for dpd, late_fee_pct in parameters.items():
            LateFeeRule.objects.create(
                dpd=int(dpd),
                late_fee_pct=late_fee_pct,
                product_lookup=product_lookup,
            )
    logger.info(
        {
            'action': 'late_fee_rule_creation',
            'message': 'Late fee rule creation completed',
        }
    )
