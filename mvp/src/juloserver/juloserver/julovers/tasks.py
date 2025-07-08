import logging

from celery.task import task
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLookup
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType,
)
from juloserver.julo.models import Partner, UploadAsyncState
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.partners import PartnerConstant
from juloserver.julovers.models import Julovers
from juloserver.julovers.services.core_services import (
    create_julovers_and_upload_result,
    process_julover_register,
    process_julovers_auto_repayment,
    tokenize_and_save_julover_pii,
    detokenize_and_log_julover_pii,
    fetch_julovers_to_be_synced_for_pii_vault
)

logger = logging.getLogger(__name__)


@task(queue='loan_normal')
def process_julovers_task(upload_async_state_id):
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.JULOVERS,
        task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = create_julovers_and_upload_result(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error({
            'module': 'julovers',
            'action': 'process_julovers_task',
            'upload_async_state_id': upload_async_state_id,
            'error': e,
        })
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue='loan_low')
def tokenize_julover_pii_task(julover_id):
    tokenize_and_save_julover_pii(julover_id)
    detokenize_and_log_julover_pii(julover_id)


@task(queue='loan_low')
def sync_julover_to_application(julover_id, partner_id):
    julover = Julovers.objects.filter(id=julover_id, is_sync_application=False).first()
    if not julover:
        return
    process_julover_register(julover, partner_id)
    tokenize_julover_pii_task.delay(julover_id)


@task(queue='loan_normal', ignore_result=True)
def sync_julover_vault_token_task():
    julovers = fetch_julovers_to_be_synced_for_pii_vault()
    for julover in julovers:
        tokenize_julover_pii_task.delay(julover.id)


@task(queue='loan_normal', ignore_result=True)
def execute_julovers_repayment():
    today = timezone.localtime(timezone.now()).date()
    julover_account_lookup = AccountLookup.objects.get(name='JULOVER')
    account_payment_qs = AccountPayment.objects.filter(
        due_date__lte=today,
        status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        account__account_lookup_id=julover_account_lookup.id,
        account__status_id__in=[
            AccountConstant.STATUS_CODE.active,
            AccountConstant.STATUS_CODE.active_in_grace,
        ]
    )

    logger_data = {
        'module': 'julovers',
        'action': 'juloserver.julover.tasks.execute_julovers_repayment',
        'date': today,
    }
    logger.info({
        **logger_data,
        'message': 'execute_julovers_repayment',
        'count': account_payment_qs.count(),
    })
    for account_payment in account_payment_qs.iterator():
        is_success = process_julovers_auto_repayment(account_payment)
        if not is_success:
            logger.error({
                **logger_data,
                'message': 'Failed to execute julovers repayment',
                'account_payment_id': account_payment.id
            })
