import logging

from celery.task import task
from juloserver.dana.loan.crm.services import (
    process_dana_loan_settlement_file,
    process_dana_update_pusdafil_data,
    process_dana_update_loan_fund_transfer_ts,
)

from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.models import UploadAsyncState

logger = logging.getLogger(__name__)


@task(queue="dana_global_queue")
def process_dana_loan_settlement_file_task(
    upload_async_state_id: int, task_type: str, product_type: str
) -> None:
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id, task_type=task_type, task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = process_dana_loan_settlement_file(upload_async_state, product_type)

        task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error(
            {
                'module': 'dana_loan_crm',
                'action': 'process_dana_settlement_file',
                'load_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue="dana_global_queue")
def process_dana_update_loan_fund_transfer_ts_task(
    upload_async_state_id: int, task_type: str, product_type: str
) -> None:
    fn_name = "process_dana_update_loan_fund_transfer_ts_task"
    logger.info(
        {
            "action": fn_name,
            "upload_async_state_id": upload_async_state_id,
            "product_type": product_type,
            "status": "STARTED",
        }
    )
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id, task_type=task_type, task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        logger.info(
            {
                "action": fn_name,
                "upload_async_state_id": upload_async_state_id,
                "product_type": product_type,
                "status": "PROCESSING",
            }
        )
        is_success_all = process_dana_update_loan_fund_transfer_ts(upload_async_state, product_type)

        task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        upload_async_state.update_safely(task_status=task_status)

        logger.info(
            {
                "action": fn_name,
                "upload_async_state_id": upload_async_state_id,
                "product_type": product_type,
                "status": "FINISHED",
            }
        )
    except Exception as e:
        logger.error(
            {
                'module': 'dana_loan_crm',
                'action': 'process_dana_update_loan_fund_transfer_ts',
                'load_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue="dana_global_queue")
def process_dana_update_pusdafil_data_task(upload_async_state_id: int, task_type: str):
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id, task_type=task_type, task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = process_dana_update_pusdafil_data(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error(
            {
                'module': 'dana_loan_crm',
                'action': 'process_dana_update_pusdafil_file',
                'load_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
