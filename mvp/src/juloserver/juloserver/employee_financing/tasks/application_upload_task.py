import logging

from celery.task import task
from juloserver.employee_financing.services import (
    create_ef_application_and_upload_result,
    disburse_employee_financing,
    repayment_employee_financing,
    create_ef_pre_approval_upload_result,
    send_form_url_to_email_service
)
from juloserver.julo.constants import (UploadAsyncStateStatus,
                                       UploadAsyncStateType)
from juloserver.julo.models import UploadAsyncState
from juloserver.employee_financing.models import Company

logger = logging.getLogger(__name__)


@task(name="process_ef_upload_task", queue="employee_financing_global_queue")
def process_ef_upload_task(upload_async_state_id, task_type):
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=task_type,
        task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        if task_type == UploadAsyncStateType.EMPLOYEE_FINANCING:
            is_success_all = create_ef_application_and_upload_result(upload_async_state)
        elif task_type == UploadAsyncStateType.EMPLOYEE_FINANCING_DISBURSEMENT:
            is_success_all = disburse_employee_financing(upload_async_state)
        elif task_type == UploadAsyncStateType.EMPLOYEE_FINANCING_REPAYMENT:
            is_success_all = repayment_employee_financing(upload_async_state)

        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error({
            'module': 'employee_financing',
            'action': 'process_create_application_task',
            'load_async_state_id': upload_async_state_id,
            'error': e,
        })
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(name="process_ef_pre_approval_upload_task", queue="employee_financing_global_queue")
def process_ef_pre_approval_upload_task(upload_async_state_id):
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL,
        task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        return
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = create_ef_pre_approval_upload_result(upload_async_state)

        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error({
            'module': 'employee_financing',
            'action': 'process_ef_pre_approval_upload_task',
            'load_async_state_id': upload_async_state_id,
            'error': e,
        })
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(name="send_form_url_to_email_task", queue="employee_financing_global_queue")
def send_form_url_to_email_task(
    upload_async_state_id: int, task_type: str, company: Company
) -> None:
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=task_type,
        task_status=UploadAsyncStateStatus.WAITING
    ).first()
    if not upload_async_state or not upload_async_state.file:
        raise ValueError(
            'upload_async_state not or file not found with ID: {}'.format(upload_async_state_id)
        )
    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = send_form_url_to_email_service(upload_async_state, task_type, company)

        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.error({
            'module': 'employee_financing',
            'action': 'send_form_url_to_email_task',
            'load_async_state_id': upload_async_state_id,
            'error': e,
        })
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
