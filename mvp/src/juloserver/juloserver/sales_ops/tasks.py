import math
import logging
from io import StringIO
from bulk_update.helper import bulk_update

from celery.task import task
from django.core import management
from django.utils import timezone
from django.conf import settings

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    UploadAsyncStateType,
    UploadAsyncStateStatus,
    FeatureNameConst,
)
from juloserver.julo.models import (
    UploadAsyncState,
    FeatureSetting,
)
from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.sales_ops.constants import (
    SalesOpsAlert ,
    PRIORITY_LINEUP_SIZE,
    QUERY_LIMIT,
)
from juloserver.sales_ops.models import (
    SalesOpsLineup,
    SalesOpsAutodialerQueueSnapshot,
    SalesOpsAgentAssignment,
    SalesOpsDailySummary,
    SalesOpsPrepareData,
)
from juloserver.sales_ops.services import sales_ops_services, sales_ops_revamp_services
from juloserver.sales_ops.services.sales_ops_revamp_services import \
    filter_out_user_assigned_in_bucket
from juloserver.sales_ops.services.vendor_rpc_services import update_rpc_from_vendor
from juloserver.sales_ops.utils import chunker
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic

logger = logging.getLogger(__name__)


def _execute_command(command, *args):
    out = StringIO()
    logger_msg = {
        'module': 'juloserver.sales_ops',
        'command': command,
        'args': args
    }
    management.call_command(command, *args, verbosity=0, stdout=out)
    if 'error' in out.getvalue().lower():
        logger.error({
            'message': f'There are error when running {command}',
            'out': out.getvalue(),
            **logger_msg
        })
        sentry_client = get_julo_sentry_client()
        sentry_client.captureMessage(
            f'[CFS] There are error when running {command}',
            data={
                **logger_msg,
                'out': out.getvalue()
            }
        )
        return

    logger.info({
        'message': f'Successfully run the command {command}',
        **logger_msg
    })


@task(queue='loan_normal')
def init_sales_ops_lineup():
    sales_ops_services.InitSalesOpsLineup().prepare_data()


@task(bind=True, queue='loan_normal')
def refresh_rm_ranking_db(self):
    try:
        _execute_command('sales_ops_refresh_ranking_db')
    except Exception as exc:
        self.request.callbacks = None
        raise exc


@task(queue='loan_normal')
def call_prioritize_sales_ops_lineups():
    lineup_ids = SalesOpsLineup.objects.get_queryset().active().values_list('id', flat=True)
    is_bucket_logic = sales_ops_services.using_sales_ops_bucket_logic()
    for sub_lineup_ids in chunker(lineup_ids.iterator(), PRIORITY_LINEUP_SIZE):
        prioritize_sales_ops_lineups.delay(sub_lineup_ids, is_bucket_logic)


@task(queue='loan_low')
def prioritize_sales_ops_lineups(lineup_ids, is_bucket_logic=False):
    lineups = SalesOpsLineup.objects.get_queryset().active().filter(id__in=lineup_ids)
    lineup_ids = [lineup.pk for lineup in lineups]

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        account_score_mappings = sales_ops_services.bulk_create_account_segment_history(lineups)
        sales_ops_services.bulk_update_lineups(lineups, account_score_mappings)

    if is_bucket_logic:
        update_vendor_bucket_lineups_logic.delay(lineup_ids)

    logger_data = {
        'module': 'juloserver.sales_ops.tasks',
        'action': 'prioritize_sales_ops_lineups',
        'lineup_ids': lineup_ids,
    }
    logger.info(logger_data)


@task(queue='loan_low')
def update_vendor_bucket_lineups_logic(lineup_ids):
    sales_ops_services.bulk_update_bucket_lineups_logic(lineup_ids)


@task(queue='loan_normal')
def sync_sales_ops_lineup():
    (
        refresh_rm_ranking_db.si()
        | call_prioritize_sales_ops_lineups.si()
    ).apply_async()


@task(queue='loan_high')
def snapshot_sales_ops_autodialer_queue():
    now = timezone.localtime(timezone.now())
    fields = ['account_id', 'prioritization']
    delay_setting = sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting()
    qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(None, **vars(delay_setting)).values(*fields)
    total = qs.count()
    iterator = qs.iterator()

    if total == 0:
        SalesOpsAutodialerQueueSnapshot.objects.create(
            snapshot_at=now,
            account_id=None,
            prioritization=None,
            ordering=None,
        )
        return

    snapshot_batch = []
    batch_size = 500
    ordering = 1
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        for lineup in iterator:
            snapshot_batch.append(SalesOpsAutodialerQueueSnapshot(
                snapshot_at=now,
                account_id=lineup['account_id'],
                prioritization=lineup['prioritization'],
                ordering=ordering,
            ))
            ordering += 1
            if len(snapshot_batch) >= batch_size:
                SalesOpsAutodialerQueueSnapshot.objects.bulk_create(snapshot_batch)
                snapshot_batch = []

        if len(snapshot_batch) > 0:
            SalesOpsAutodialerQueueSnapshot.objects.bulk_create(snapshot_batch)

    logger.info({
        'task': 'snapshot_sales_ops_autodialer_queue',
        'message': f'SalesOps Queue Snapshot is done at {now}. Total: {total}',
        'total': total,
        'now': str(now),
    })


# @task(queue='loan_normal')
# def deactivate_sales_ops_account(account_id):
#     # check if it is an active sales op account
#     account_line_up = SalesOpsLineup.objects.get_or_none(
#         account_id=account_id,
#         is_active=True,
#     )
#     if account_line_up:
#         account_line_up.is_active = False
#         account_line_up.save()
#         # Deactivate old agent assignment session
#         SalesOpsAgentAssignment.objects.filter(
#             lineup_id=account_line_up.id,
#             is_active=True,
#         ).update(is_active=False)


@task(queue='loan_low')
def process_sales_ops_lineup_account_ids(account_ids, daily_summary_id):
    sales_ops_services.InitSalesOpsLineup().handle(account_ids, daily_summary_id)
    logger.info({
        'task': 'process_sales_ops_lineup_account_ids',
        'account_ids': account_ids,
        'daily_summary_id': daily_summary_id,
    })


@task(queue='loan_normal')
def update_rpc_from_vendor_task(upload_async_state_id):
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state:
        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        task_status = UploadAsyncStateStatus.COMPLETED
        is_success_all = update_rpc_from_vendor(upload_async_state)
        if not is_success_all:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
    except Exception as e:
        logger.error({
            'module': 'sales_ops',
            'action': 'update_rpc_from_vendor_task',
            'upload_async_state_id': upload_async_state_id,
            'error': e,
        })
        task_status = UploadAsyncStateStatus.FAILED

    upload_async_state.update_safely(task_status=task_status)


@task(queue='loan_low')
def update_sales_ops_latest_rpc_agent_assignment_task(sub_lineup_ids):
    now = timezone.localtime(timezone.now())
    agent_assignments = SalesOpsAgentAssignment.objects \
        .filter(lineup_id__in=sub_lineup_ids, is_rpc=True, completed_date__isnull=False) \
        .order_by('lineup_id', '-completed_date') \
        .distinct('lineup_id')

    sales_ops_lineups = []
    for agent_assignment in agent_assignments:
        lineup = agent_assignment.lineup
        lineup.latest_rpc_agent_assignment = agent_assignment
        lineup.udate = now
        sales_ops_lineups.append(lineup)
    bulk_update(sales_ops_lineups, update_fields=['latest_rpc_agent_assignment', 'udate'])


@task(queue='loan_low')
def update_sales_ops_lineup_rpc_count(lineup_ids):
    lineups = SalesOpsLineup.objects.filter(id__in=lineup_ids)
    for lineup in lineups:
        count = SalesOpsAgentAssignment.objects.filter(lineup=lineup.id, is_rpc=True).count()
        lineup.update_safely(
            rpc_count=count
        )


@task(queue='loan_normal')
def send_slack_notification():
    sales_ops_alert_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_ALERT, is_active=True
    ).last()
    if not sales_ops_alert_fs:
        return

    parameters = sales_ops_alert_fs.parameters
    channel = parameters.get('channel', SalesOpsAlert.CHANNEL)

    sales_ops_daily_summary = SalesOpsDailySummary.objects.last()
    if sales_ops_daily_summary.progress == sales_ops_daily_summary.number_of_task:
        message = parameters.get('success_message', SalesOpsAlert.SUCCESS_MESSAGE)
    else:
        message = parameters.get('failure_message', SalesOpsAlert.FAILURE_MESSAGE)

    message += (
        f'\n On *{settings.ENVIRONMENT}* environment:'
        f'\n  - Total sales ops lineups: {sales_ops_daily_summary.total}'
        f'\n  - Current progress: {sales_ops_daily_summary.progress}'
        f'\n  - Number of progresses: {sales_ops_daily_summary.number_of_task}'
    )
    send_slack_bot_message(channel, message)


@task(queue='loan_high')
def init_sales_ops_lineup_new_flow():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_REVAMP, is_active=True
    ).last()
    if not feature_setting:
        return

    account_ids = SalesOpsPrepareData.objects.values_list('account_id', flat=True)
    total_count = len(account_ids)
    daily_summary = SalesOpsDailySummary.objects.create(
        total=total_count,
        progress=0,
        number_of_task=math.ceil(total_count / QUERY_LIMIT),
        new_sales_ops=0,
        update_sales_ops=0,
    )

    # update lineup to inactive
    SalesOpsLineup.objects.filter(is_active=True).update(is_active=False)

    # Classify m_score and r_score and then generate lineup
    for account_sub_ids in chunker(account_ids, QUERY_LIMIT):
        process_generate_lineup_task.delay(account_sub_ids, daily_summary.pk)


@task(queue='loan_normal')
def process_generate_lineup_task(account_ids, daily_summary_id):
    SalesOpsLineup.objects.filter(account_id__in=account_ids).update(is_active=True)
    account_ids = filter_out_user_assigned_in_bucket(account_ids)
    classify_data = sales_ops_revamp_services.classify_rm_scoring(account_ids)
    num_created, num_updated = \
        sales_ops_revamp_services.generate_sales_ops_line_up(classify_data)

    with db_transactions_atomic({DbConnectionAlias.UTILIZATION_DB}):
        # update daily summary
        daily_summary = (
            SalesOpsDailySummary.objects
            .select_for_update()
            .filter(id=daily_summary_id)
            .last()
        )
        daily_summary.progress += 1
        daily_summary.new_sales_ops = (daily_summary.new_sales_ops or 0) + num_created
        daily_summary.update_sales_ops = (daily_summary.update_sales_ops or 0) + num_updated
        daily_summary.save()
