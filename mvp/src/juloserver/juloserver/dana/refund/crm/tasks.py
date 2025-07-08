import logging
from celery import task

from juloserver.julo.models import UploadAsyncState
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.dana.refund.crm.services import process_dana_refund_payment_settlement_result

logger = logging.getLogger(__name__)


@task(queue='dana_global_queue')
def process_dana_refund_payment_settlement_file_task(upload_async_state_id: int, task_type: str):
    fn_name = "process_dana_refund_payment_settlement_file_task"
    logger.info({"action": fn_name, "task_type": task_type, "status": "STARTED"})
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id, task_type=task_type, task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info("UploadAsyncState not found or file is missing.")
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        logger.info(
            {
                "action": fn_name,
                "task_type": task_type,
                "status": "PROCESSING",
            }
        )
        is_success_all = process_dana_refund_payment_settlement_result(upload_async_state)
        task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        upload_async_state.update_safely(task_status=task_status)
        logger.info(
            {
                "action": fn_name,
                "task_type": task_type,
                "status": "FINISHED",
            }
        )
    except Exception as e:
        logger.error(
            {
                'module': 'dana_refund_crm',
                'action': 'process_dana_refund_payment_settlement_file',
                'load_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
