import logging

from celery import task
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from juloserver.dana.constants import (
    BILL_STATUS_PAID_OFF,
    DanaReferenceStatus,
    PaymentReferenceStatus,
    DanaUploadAsyncStateType,
)
from juloserver.dana.models import DanaRefundTransaction, DanaPaymentBill, DanaLoanReferenceStatus
from juloserver.dana.repayment.services import create_manual_repayment_settlement
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.models import Payment, UploadAsyncState

logger = logging.getLogger(__name__)


@task(queue='dana_transaction_queue')
def run_refund_async_process(dana_refund_transaction_id: int) -> None:
    """
    In this process the calculation to be paid using inner process and data from JULO side
    and the bill status should mark as FULLY PAID (PAID)
    set as CANCELLED is mean marked as REFUNDED (Treatment as repayment in JULO)
    """

    dana_refund_transaction = DanaRefundTransaction.objects.get(id=dana_refund_transaction_id)
    dana_refund_reference = dana_refund_transaction.dana_refund_reference
    dana_refunded_bills = dana_refund_transaction.dana_refunded_bills.all()

    with transaction.atomic(using='partnership_db'):
        bill_ids = [
            refunded_repayment_detail.bill_id for refunded_repayment_detail in dana_refunded_bills
        ]
        dana_payment_bills = DanaPaymentBill.objects.select_for_update().filter(
            bill_id__in=bill_ids
        )
        dana_payment_bill_mapping = {
            dana_payment_bill.bill_id: dana_payment_bill for dana_payment_bill in dana_payment_bills
        }

        payment_ids = [dana_payment_bill.payment_id for dana_payment_bill in dana_payment_bills]
        payments = Payment.objects.filter(id__in=payment_ids)
        payment_mapping = {payment.id: payment for payment in payments}

        for refunded_repayment_detail in dana_refunded_bills:
            dana_payment_bill = dana_payment_bill_mapping.get(refunded_repayment_detail.bill_id)
            payment_id = dana_payment_bill.payment_id
            payment = payment_mapping.get(payment_id)

            principal_amount = payment.installment_principal - payment.paid_principal
            interest_fee_amount = payment.installment_interest - payment.paid_interest
            late_fee_amount = payment.late_fee_amount - payment.paid_late_fee
            total_amount = principal_amount + interest_fee_amount + late_fee_amount
            time_to_str = str(timezone.localtime(dana_refund_reference.refund_time))

            data = {
                'partnerReferenceNo': dana_refund_reference.partner_refund_no,
                'billId': refunded_repayment_detail.bill_id,
                'billStatus': BILL_STATUS_PAID_OFF,
                'principalAmount': principal_amount,
                'interestFeeAmount': interest_fee_amount,
                'lateFeeAmount': late_fee_amount,
                'totalAmount': total_amount,
                'transTime': time_to_str,
                # for event payment needed
                'danaLateFeeAmount': refunded_repayment_detail.late_fee_Amount,
            }

            dana_loan_reference = payment.loan.danaloanreference
            is_recalculated = True
            if hasattr(payment.loan.danaloanreference, 'danaloanreferenceinsufficienthistory'):
                is_recalculated = (
                    dana_loan_reference.danaloanreferenceinsufficienthistory.is_recalculated
                )

            create_manual_repayment_settlement(
                data=data, is_pending_process=True, is_refund=True, is_recalculated=is_recalculated
            )

        dana_refund_reference.update_safely(status=DanaReferenceStatus.SUCCESS)
        DanaLoanReferenceStatus.objects.update_or_create(
            dana_loan_reference=dana_refund_transaction.dana_loan_reference,
            defaults={'status': PaymentReferenceStatus.CANCELLED},
        )


@task(queue='dana_global_queue')
def process_pending_dana_refund_task():
    target_datetime = timezone.localtime(timezone.now()) - timedelta(hours=1)
    refund_transaction_pending_ids = (
        DanaRefundTransaction.objects.filter(
            dana_refund_reference__status=DanaReferenceStatus.PENDING, cdate__lte=target_datetime
        )
        .select_related('dana_refund_reference__status')
        .values('id')
        .order_by('cdate')
    )

    for refund_transaction in refund_transaction_pending_ids:
        run_refund_async_process(refund_transaction['id'])


@task(queue='dana_global_queue')
def process_dana_refund_repayment_settlement_task(
    upload_async_state_id: int,
) -> None:
    from juloserver.dana.refund.services import process_dana_refund_repayment_settlement_result

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=DanaUploadAsyncStateType.DANA_REFUND_REPAYMENT_SETTLEMENT,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "dana_process_refund_repayment_settlement_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = process_dana_refund_repayment_settlement_result(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        logger.exception(
            {
                'module': 'dana',
                'action': 'dana_process_refund_repayment_settlement_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
