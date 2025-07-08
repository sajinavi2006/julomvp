import logging
import time
from collections import defaultdict
from datetime import timedelta
from typing import List

from celery import chain, group, task
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.account.services.account_related import process_change_account_status
from juloserver.dana.constants import DanaUploadAsyncStateType, RepaymentReferenceStatus
from juloserver.dana.models import DanaRepaymentReference, DanaRepaymentReferenceStatus
from juloserver.dana.repayment.services import update_late_fee_amount, new_update_late_fee_amount
from juloserver.julo.constants import FeatureNameConst, UploadAsyncStateStatus
from juloserver.julo.models import FeatureSetting, Payment, UploadAsyncState, PaymentEvent
from juloserver.monitors.notifications import notify_cron_job_has_been_hit_more_than_once
from juloserver.partnership.utils import idempotency_check_cron_job, is_idempotency_check
from django_bulk_update.helper import bulk_update

logger = logging.getLogger(__name__)


@task(queue='dana_late_fee_queue')
def trigger_update_late_fee_amount() -> None:
    fn_name = "trigger_update_late_fee_amount"
    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    unpaid_payments = (
        Payment.objects.not_paid_active_overdue()
        .filter(loan__account__account_lookup__name="DANA")
        .values_list("id", "account_payment__account__id")
        .order_by("id")
    )

    mapping_account_from_payments = defaultdict(list)
    for payment in unpaid_payments.iterator():
        account_id = payment[1]
        mapping_account_from_payments[account_id].append(payment[0])

    account_id_keys = list(mapping_account_from_payments.keys())
    chunks = [account_id_keys[i: i + 20] for i in range(0, len(account_id_keys), 20)]

    late_fee_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_LATE_FEE, is_active=True,
    ).last()

    if late_fee_feature_setting and late_fee_feature_setting.parameters.get("enable_new_change"):
        for chunk in chunks:
            chain_tasks = []
            for account_id in chunk:
                payment_ids = mapping_account_from_payments[account_id]
                chain_tasks.append(update_late_fee_amount_task.si(payment_ids))
            group_tasks = group(chain(*chain_tasks))
            group_tasks()
            time.sleep(0.2)
    else:
        for chunk in chunks:
            chain_tasks = []
            for account_id in chunk:
                payment_ids = mapping_account_from_payments[account_id]
                chain_tasks.append(old_update_late_fee_amount_task.si(payment_ids))
            group_tasks = group(chain(*chain_tasks))
            group_tasks()


@task(queue='dana_late_fee_queue')
def old_update_late_fee_amount_task(payment_ids: List) -> None:
    from juloserver.dana.models import DanaPaymentBill
    from juloserver.account_payment.models import AccountPayment

    account_payment_dicts = {}
    account_payment_ids = set()

    logger.info(
        {
            "task": "old_update_late_fee_amount_task",
            "action": "process_dana_late_fee_amount",
            "message": "Process Dana Late Fee Amount",
            "payment_ids": payment_ids,
        }
    )

    dana_payment_bills = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))
    dana_payment_bill_mapping = {dpb.payment_id: dpb for dpb in dana_payment_bills}

    payments = Payment.objects.filter(id__in=payment_ids).select_related("loan")
    payment_mapping = {payment.id: payment for payment in payments}

    for payment_id, dpb in dana_payment_bill_mapping.items():
        payment = payment_mapping.get(payment_id)
        if payment:
            account_payment_dicts[payment.account_payment_id] = {
                "payment": payment,
                "dana_payment_bill": dpb,
            }
            account_payment_ids.add(payment.account_payment_id)

    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)

    for ap in account_payments:
        account_payment_dicts[ap.id]["account_payment"] = ap

    new_update_late_fee_amount(account_payment_dicts)


@task(queue='dana_late_fee_queue', rate_limit='8/s')
def update_late_fee_amount_task(payment_ids: List) -> None:
    logger.info(
        {
            "task": "update_late_fee_amount_task",
            "action": "process_dana_late_fee_amount",
            "message": "Process Dana Late Fee Amount",
            "payment_ids": payment_ids,
        }
    )

    for payment_id in payment_ids:
        update_late_fee_amount(payment_id)


@task(queue='dana_transaction_queue')
def account_reactivation(account_id: int) -> None:
    account = Account.objects.get(pk=account_id)
    if account.status_id not in {
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.suspended,
    }:
        logger.info(
            {
                "action": "dana_account_reactivation",
                "message": "account status {} is not eligible".format(account.status_id),
                "account_id": account.id,
            }
        )
        return
    total_unpaid_due_amount = account.get_total_outstanding_due_amount()
    if total_unpaid_due_amount > 0:
        logger.info(
            {
                "action": "dana_account_reactivation",
                "message": "outstanding amount {} greater than 0".format(total_unpaid_due_amount),
                "account_id": account.id,
            }
        )
        return
    process_change_account_status(
        account, AccountConstant.STATUS_CODE.active, 'revert account status back to 420'
    )


@task(queue='dana_global_queue')
def process_dana_repayment_settlement_task(
    upload_async_state_id: int,
    product: str,
) -> None:
    from juloserver.dana.repayment.services import (
        process_dana_repayment_settlement_result,
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=DanaUploadAsyncStateType.DANA_REPAYMENT_SETTLEMENT,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "dana_process_dana_repayment_settlement_task",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = process_dana_repayment_settlement_result(upload_async_state, product)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        logger.exception(
            {
                'module': 'dana',
                'action': 'dana_process_dana_repayment_settlement_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue='dana_transaction_queue')
def run_repayment_async_process(bill_ids: List, list_partner_references_no: List) -> None:
    """
    Need handle payment have loan for supporting if loan is below 220
    To not process the payment
    """

    from juloserver.dana.repayment.services import resume_dana_repayment
    from juloserver.julo.statuses import LoanStatusCodes

    dana_repayment_references = DanaRepaymentReference.objects.filter(
        partner_reference_no__in=list_partner_references_no,
        bill_id__in=bill_ids,
        payment__loan__loan_status__gte=LoanStatusCodes.CURRENT,
    )

    resume_dana_repayment(list_dana_repayment_references=dana_repayment_references)


@task(queue='dana_global_queue')
def process_pending_dana_repayment_task() -> None:
    from juloserver.dana.repayment.services import resume_dana_repayment

    feature_setting_repayment_async_process = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_ENABLE_REPAYMENT_ASYNCHRONOUS,
    ).first()

    if not (
        feature_setting_repayment_async_process
        and feature_setting_repayment_async_process.is_active
    ):
        return

    logs = {
        "action": "run_schedule_repayment_pending",
        "message": "Start run_schedule_repayment_pending",
    }
    logger.info(logs)

    to_datetime = timezone.localtime(timezone.now())
    from_datetime = to_datetime - timedelta(days=1)

    pending_repayment_ids = list(
        DanaRepaymentReferenceStatus.objects.filter(
            cdate__range=[from_datetime, to_datetime],
            status=RepaymentReferenceStatus.PENDING,
        ).values_list("dana_repayment_reference_id", flat=True)
    )

    dana_repayment_references = DanaRepaymentReference.objects.filter(
        id__in=pending_repayment_ids,
        payment__account_payment__isnull=False,
        payment__loan__danaloanreference__isnull=False,
    )

    repayment_payment_ids = dana_repayment_references.values_list("payment_id", flat=True)
    repayment_payment_events = PaymentEvent.objects.filter(
        payment_id__in=repayment_payment_ids, event_type="payment"
    )

    mapped_payment_event_repayment = {}
    for pe in repayment_payment_events.iterator():
        key = (pe.payment_id, pe.payment_receipt)
        mapped_payment_event_repayment[key] = pe

    ran_dana_repayment_references = []
    update_status_dana_repayment_reference_ids = []

    for drr in dana_repayment_references.iterator():
        key = (drr.payment_id, drr.partner_reference_no)
        if mapped_payment_event_repayment.get(key):
            update_status_dana_repayment_reference_ids.append(drr.id)
        else:
            ran_dana_repayment_references.append(drr)

    if len(update_status_dana_repayment_reference_ids) > 0:
        update_dana_repayment_references_status = []
        dana_repayment_references_status = DanaRepaymentReferenceStatus.objects.filter(
            status=RepaymentReferenceStatus.PENDING,
            dana_repayment_reference_id__in=update_status_dana_repayment_reference_ids,
        )
        for drrs in dana_repayment_references_status.iterator():
            drrs.udate = timezone.localtime(timezone.now())
            drrs.status = RepaymentReferenceStatus.SUCCESS
            update_dana_repayment_references_status.append(drrs)

        bulk_update(
            update_dana_repayment_references_status,
            update_fields=["status", "udate"],
            batch_size=100,
            using="partnership_db",
        )

    if len(ran_dana_repayment_references) > 0:
        resume_dana_repayment(list_dana_repayment_references=ran_dana_repayment_references)
    else:
        logs["message"] = "No DanaRepaymentReference with PENDING status"
        logger.info(logs)

    logs["message"] = "Success run_schedule_repayment_pending"
    logger.info(logs)
