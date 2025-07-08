import logging
from celery import task
from django.db import IntegrityError

from juloserver.dana.dana_lender.crm.services import process_file_from_dana_lender_upload
from juloserver.julo.models import UploadAsyncState
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.partnership.models import DanaLenderSettlementFile

logger = logging.getLogger(__name__)


@task(queue='dana_lender_settlement_file_queue')
def process_dana_lender_payment_upload_task(upload_async_state_id: int, task_type: str):
    fn_name = "process_dana_lender_payment_upload_task"
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
        is_success_all = process_file_from_dana_lender_upload(upload_async_state)
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
                'action': fn_name,
                'load_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue="dana_lender_settlement_file_queue")
def dana_lender_process_upload_data(cleaned_data_batch):
    fn_name = "dana_lender_process_upload_data"

    dlsf_list = []
    for data in cleaned_data_batch:
        dlsf = DanaLenderSettlementFile(
            customer_id=data["customerId"],
            partner_id=data["partnerId"],
            lender_product_id=data["lenderProductId"],
            partner_reference_no=data["partnerReferenceNo"],
            txn_type=data["txnType"],
            amount=data["amount"],
            status=data["status"],
            bill_id=data["billId"],
            due_date=data["dueDate"],
            period_no=data["periodNo"],
            credit_usage_mutation=data["creditUsageMutation"],
            principal_amount=data["principalAmount"],
            interest_fee_amount=data["interestFeeAmount"],
            late_fee_amount=data["lateFeeAmount"],
            total_amount=data["totalAmount"],
            paid_principal_amount=data["paidPrincipalAmount"],
            paid_interest_fee_amount=data["paidInterestFeeAmount"],
            paid_late_fee_amount=data["paidLateFeeAmount"],
            total_paid_amount=data["totalPaidAmount"],
            trans_time=data["transTime"],
            is_partial_refund=data["isPartialRefund"],
            fail_code=data["failCode"],
            original_order_amount=data["originalOrderAmount"],
            original_partner_reference_no=data["originalPartnerReferenceNo"],
            txn_id=data["txnId"],
            waived_principal_amount=data["waivedPrincipalAmount"],
            waived_interest_fee_amount=data["waivedInterestFeeAmount"],
            waived_late_fee_amount=data["waivedLateFeeAmount"],
            total_waived_amount=data["totalWaivedAmount"],
        )
        dlsf_list.append(dlsf)

    try:
        DanaLenderSettlementFile.objects.bulk_create(
            dlsf_list,
            batch_size=100,
        )
    except IntegrityError as e:
        error = str(e)
        logger.error(
            {
                "action": fn_name,
                "message": "bulk_create failed for some objects",
                "error": error,
            }
        )
