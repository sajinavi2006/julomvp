import logging
import os
import pdfkit
import tempfile

from juloserver.followthemoney.tasks import (
    assign_lenderbucket_xid_to_lendersignature,
    insert_data_into_lender_balance_history,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.tasks import upload_document
from bulk_update.helper import bulk_update
from celery import task
from collections import defaultdict
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from juloserver.account.models import AccountLimit, AccountLimitHistory
from juloserver.account_payment.models import AccountPayment
from juloserver.channeling_loan.services.general_services import (
    is_block_regenerate_document_ars_config_active,
)
from juloserver.dana.constants import PaymentReferenceStatus
from juloserver.dana.models import (
    DanaLoanReference,
    DanaLoanReferenceInsufficientHistory,
    DanaPaymentBill,
    DanaRepaymentReference,
)
from juloserver.fdc.constants import FDCReasonConst
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.followthemoney.services import (
    RedisCacheLoanBucketXidPast,
    get_available_balance,
    get_summary_loan_agreement_template,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Document, FeatureSetting, Loan, Partner, Payment
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.followthemoney.models import (
    LenderBalanceCurrent,
    LenderBucket,
    LenderCurrent,
    LoanAgreementTemplate,
)
from juloserver.dana.constants import DanaReferenceStatus
from juloserver.loan.services.loan_related import update_fdc_active_loan_checking
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting

logger = logging.getLogger(__name__)


@task(queue='dana_transaction_queue')
def run_payment_async_process(
    dana_loan_reference_id: int = None,
) -> None:
    from juloserver.dana.loan.services import resume_dana_create_loan

    dana_loan_references = DanaLoanReference.objects.filter(
        pk=dana_loan_reference_id,
        dana_loan_status__status=PaymentReferenceStatus.PENDING,
    ).order_by('id')

    if dana_loan_references:
        logger.info(
            {
                "action": "run_payment_async_process",
                "data": dana_loan_references.values_list('loan_id', flat=True),
            }
        )

    resume_dana_create_loan(list_dana_loan_references=dana_loan_references)


@task(queue='dana_global_queue')
def process_pending_dana_payment_task() -> None:
    from juloserver.dana.loan.services import resume_dana_create_loan

    feature_setting_payment_async_process = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_ENABLE_PAYMENT_ASYNCHRONOUS,
    ).first()

    if not (
        feature_setting_payment_async_process and feature_setting_payment_async_process.is_active
    ):
        return

    logs = {
        "action": "run_schedule_payment_pending",
        "message": "Start run_schedule_payment_pending",
    }
    logger.info(logs)

    target_datetime = timezone.localtime(timezone.now()) - timedelta(hours=1)
    pending_dana_payment_references = DanaLoanReference.objects.filter(
        dana_loan_status__status=PaymentReferenceStatus.PENDING, cdate__lte=target_datetime
    )

    if not pending_dana_payment_references:
        logs["message"] = "No DanaPaymentReference with PENDING status"
        logger.info(logs)
    else:
        logs = {
            "action": "process_pending_dana_payment_task",
            "data": pending_dana_payment_references.values_list('loan_id', flat=True),
            "message": "running resume_dana_create_loan",
        }
        logger.info(logs)
        resume_dana_create_loan(list_dana_loan_references=pending_dana_payment_references)

    logs["message"] = "Sucess run_schedule_payment_pending"
    logger.info(logs)


@task(queue='dana_global_queue')
def generate_dana_p3_for_jtp() -> None:
    with open('juloserver/dana/templates/p3bti_dana.html', "r") as file:
        html = file.read()
        file.close()

    jtp = LenderCurrent.objects.filter(lender_name="jtp", lender_status="active").last()
    is_template_exist = LoanAgreementTemplate.objects.filter(
        lender=jtp, agreement_type=LoanAgreementType.SUMMARY_DANA
    ).exists()

    if jtp and not is_template_exist:
        LoanAgreementTemplate.objects.create(
            body=html, lender=jtp, is_active=True, agreement_type=LoanAgreementType.SUMMARY_DANA
        )


@task(queue='dana_global_queue')
def recalculate_account_limit() -> None:
    """
    This function will recalculate payment, account payment, and account limit.
    Automatically update based on data created in table DanaLoanReferenceInsufficientHistory
    And not yet recalculated
    """
    fn_name = 'recalculate_account_limit'
    logger.info(
        {
            "action": fn_name,
            "message": "task start",
        }
    )

    is_block = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.DANA_BLOCK_RECALCULATE_ACCOUNT_LIMIT,
        is_active=True,
    ).exists()
    if is_block:
        logger.info(
            {
                "action": fn_name,
                "message": "task early return because feature settings",
            }
        )
        return

    update_date = timezone.localtime(timezone.now())
    dana_loan_created_with_insufficient_limit = DanaLoanReferenceInsufficientHistory.objects.filter(
        is_recalculated=False,
    ).select_related('dana_loan_reference', 'dana_loan_reference__loan')

    account_ids_need_recalculate = dana_loan_created_with_insufficient_limit.values_list(
        'dana_loan_reference__loan__account_id', flat=True
    ).distinct('dana_loan_reference__loan__account_id')

    dana_loan_references = DanaLoanReference.objects.filter(
        loan__account__id__in=account_ids_need_recalculate
    ).select_related('loan', 'loan__account', 'dana_loan_status')

    """
    Handling if loan stuck need to adding with calculated due amount
    For prevent miss calculation, because on this case limit is deducted
    But account payment still not created
    """
    not_active_loans_amount_limit_deducted = defaultdict(int)
    for dana_loan_reference in dana_loan_references:
        is_success = (
            hasattr(dana_loan_reference, 'dana_loan_status')
            and dana_loan_reference.dana_loan_status.status == PaymentReferenceStatus.SUCCESS
        )

        not_active_loan_status = {
            LoanStatusCodes.LENDER_APPROVAL,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        }
        is_loan_not_active = dana_loan_reference.loan.status in not_active_loan_status

        if is_success and is_loan_not_active:
            account_id = dana_loan_reference.loan.account_id
            dana_loan_reference_amount = dana_loan_reference.credit_usage_mutation
            not_active_loans_amount_limit_deducted[account_id] += dana_loan_reference_amount

    account_payments = AccountPayment.objects.filter(
        account_id__in=account_ids_need_recalculate
    ).order_by('id')

    account_payment_ids = account_payments.values_list('id', flat=True)
    payments = Payment.objects.filter(
        account_payment__id__in=account_payment_ids,
        loan__loan_status__status_code__gte=LoanStatusCodes.CURRENT,
        loan__loan_status__status_code__lte=LoanStatusCodes.PAID_OFF,
    ).order_by('account_payment_id')

    payment_ids = payments.values_list('id', flat=True)
    dana_payment_bills_qs = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))

    dana_payment_bill_map = {bill.payment_id: bill for bill in dana_payment_bills_qs}

    mapping_payment_paid_interest = defaultdict(int)
    dana_repayment_references = DanaRepaymentReference.objects.filter(
        payment__in=payments
    ).order_by('id')
    for dana_repayment in dana_repayment_references:
        mapping_payment_paid_interest[
            dana_repayment.payment_id
        ] += dana_repayment.interest_fee_amount

    mapping_account_payment_amount = defaultdict(lambda: defaultdict(int))
    for payment in payments.iterator():
        account_payment_id = payment.account_payment_id
        mapping_account_payment_amount[account_payment_id]['total_due_amount'] += payment.due_amount
        mapping_account_payment_amount[account_payment_id][
            'total_principal_amount'
        ] += payment.installment_principal
        mapping_account_payment_amount[account_payment_id][
            'total_interest_amount'
        ] += payment.installment_interest
        mapping_account_payment_amount[account_payment_id][
            'total_late_fee_amount'
        ] += payment.late_fee_amount
        mapping_account_payment_amount[account_payment_id][
            'total_paid_amount'
        ] += payment.paid_amount
        mapping_account_payment_amount[account_payment_id][
            'total_paid_principal'
        ] += payment.paid_principal
        mapping_account_payment_amount[account_payment_id][
            'total_paid_interest'
        ] += payment.paid_interest
        mapping_account_payment_amount[account_payment_id][
            'total_paid_late_fee'
        ] += payment.paid_late_fee

        dana_payment_bill = dana_payment_bill_map.get(payment.id)
        if dana_payment_bill:
            mapping_account_payment_amount[account_payment_id][
                'actual_total_interest_amount'
            ] += dana_payment_bill.interest_fee_amount

            if (
                hasattr(payment.loan.danaloanreference, 'dana_loan_status')
                and payment.loan.danaloanreference.dana_loan_status.status
                == DanaReferenceStatus.CANCELLED
            ):
                mapping_account_payment_amount[account_payment_id][
                    'actual_total_paid_interest_amount'
                ] += dana_payment_bill.interest_fee_amount
            else:
                mapping_account_payment_amount[account_payment_id][
                    'actual_total_paid_interest_amount'
                ] += mapping_payment_paid_interest.get(payment.id, 0)

    recalculate_account_payment_update = []
    account_used_limit_mapping = defaultdict(int)
    for account_payment in account_payments.iterator():
        account_id = account_payment.account_id
        payments_calculation = mapping_account_payment_amount[account_payment.id]

        total_due_amount = payments_calculation['total_due_amount']
        total_principal_amount = payments_calculation['total_principal_amount']
        total_interest_amount = payments_calculation['total_interest_amount']
        total_late_fee_amount = payments_calculation['total_late_fee_amount']
        total_paid_amount = payments_calculation['total_paid_amount']
        total_paid_principal = payments_calculation['total_paid_principal']
        total_paid_interest = payments_calculation['total_paid_interest']
        total_paid_late_fee = payments_calculation['total_paid_late_fee']
        actual_total_interest_amount = payments_calculation['actual_total_interest_amount']
        actual_total_paid_interest_amount = payments_calculation[
            'actual_total_paid_interest_amount'
        ]

        old_due_amount = account_payment.due_amount
        old_principal_amount = account_payment.principal_amount
        old_interest_amount = account_payment.interest_amount
        old_late_fee_amount = account_payment.late_fee_amount
        old_paid_amount = account_payment.paid_amount
        old_paid_principal = account_payment.paid_principal
        old_paid_interest = account_payment.paid_interest
        old_paid_late_fee = account_payment.paid_late_fee

        account_payment.udate = update_date
        account_payment.due_amount = total_due_amount
        account_payment.principal_amount = total_principal_amount
        account_payment.interest_amount = total_interest_amount
        account_payment.late_fee_amount = total_late_fee_amount
        account_payment.paid_amount = total_paid_amount
        account_payment.paid_principal = total_paid_principal
        account_payment.paid_interest = total_paid_interest
        account_payment.paid_late_fee = total_paid_late_fee

        logger.info(
            {
                'action': 'recalculate_account_limit',
                'account_id': account_payment.account_id,
                'account_payment_id': account_payment.id,
                'old_data': {
                    'old_due_amount': old_due_amount,
                    'old_principal_amount': old_principal_amount,
                    'old_interest_amount': old_interest_amount,
                    'old_late_fee_amount': old_late_fee_amount,
                    'old_paid_amount': old_paid_amount,
                    'old_paid_principal': old_paid_principal,
                    'old_paid_interest': old_paid_interest,
                    'old_paid_late_fee': old_paid_late_fee,
                },
                'new_data': {
                    'new_due_amount': account_payment.due_amount,
                    'new_principal_amount': account_payment.principal_amount,
                    'new_interest_amount': account_payment.interest_amount,
                    'new_late_fee_amount': account_payment.late_fee_amount,
                    'new_paid_amount': account_payment.paid_amount,
                    'new_paid_principal': account_payment.paid_principal,
                    'new_paid_interest': account_payment.paid_interest,
                    'new_paid_late_fee': account_payment.paid_late_fee,
                },
            }
        )

        recalculate_account_payment_update.append(account_payment)

        total_used_limit = (total_principal_amount - total_paid_principal) + (
            actual_total_interest_amount - actual_total_paid_interest_amount
        )
        account_used_limit_mapping[account_id] += total_used_limit

    with transaction.atomic():
        fields_to_update = [
            'udate',
            'due_amount',
            'principal_amount',
            'interest_amount',
            'late_fee_amount',
            'paid_amount',
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
        ]
        bulk_update(
            recalculate_account_payment_update, update_fields=fields_to_update, batch_size=300
        )

        account_limits = AccountLimit.objects.filter(
            account__id__in=account_ids_need_recalculate
        ).order_by('account_id')

        updated_account_limit_history = []
        account_limit_updated_data = []
        loan_account_id_update = []
        for account_limit in account_limits.iterator():
            amount_based_acc_payment = account_used_limit_mapping.get(account_limit.account_id, 0.0)
            amount_based_not_active_loan = not_active_loans_amount_limit_deducted.get(
                account_limit.account_id, 0.0
            )

            calculated_used_limit = amount_based_acc_payment + amount_based_not_active_loan
            calculated_available_limit = account_limit.max_limit - calculated_used_limit

            current_used_limit = account_limit.used_limit
            current_available_limit = account_limit.available_limit
            if (
                current_used_limit != calculated_used_limit
                or current_available_limit != calculated_available_limit
            ):
                if calculated_available_limit < 0:
                    continue

                account_limit.udate = update_date
                account_limit_history = AccountLimitHistory(
                    account_limit=account_limit,
                    field_name='available_limit',
                    value_old=str(current_available_limit),
                    value_new=str(calculated_available_limit),
                )
                updated_account_limit_history.append(account_limit_history)
                account_limit.available_limit = calculated_available_limit

                account_limit_history = AccountLimitHistory(
                    account_limit=account_limit,
                    field_name='used_limit',
                    value_old=str(current_used_limit),
                    value_new=str(calculated_used_limit),
                )
                updated_account_limit_history.append(account_limit_history)
                account_limit.used_limit = calculated_used_limit
                account_limit_updated_data.append(account_limit)
                loan_account_id_update.append(account_limit.account_id)

                logger.info(
                    {
                        'action': 'recalculate_account_limit',
                        'message': 'success_recalculate_dana_insufficient_account_limit',
                        'account_id': account_limit.account_id,
                        'calculated_used_limt': calculated_used_limit,
                    }
                )

        bulk_update(
            account_limit_updated_data,
            update_fields=['udate', 'available_limit', 'used_limit'],
            batch_size=100,
        )
        AccountLimitHistory.objects.bulk_create(updated_account_limit_history, batch_size=100)

        # Update to recalculated
        insufficient_loan_created_update = []
        for insufficient_loan_created in dana_loan_created_with_insufficient_limit:
            if (
                insufficient_loan_created.dana_loan_reference.loan.account_id
                in loan_account_id_update
            ):
                insufficient_loan_created.is_recalculated = True
                insufficient_loan_created.udate = update_date
                insufficient_loan_created_update.append(insufficient_loan_created)

        bulk_update(
            insufficient_loan_created_update,
            update_fields=['is_recalculated', 'udate'],
            batch_size=100,
        )


@task(queue='partnership_global')
def dana_hit_fdc_inquiry_for_max_platform_check_task(
    customer_id: int, fdc_inquiry_data: dict
) -> None:
    from juloserver.fdc.exceptions import FDCServerUnavailableException

    try:
        get_and_save_fdc_data(fdc_inquiry_data, FDCReasonConst.REASON_APPLYING_LOAN, False)
        update_fdc_active_loan_checking(customer_id, fdc_inquiry_data)
    except FDCServerUnavailableException as e:
        logger.error(
            {
                "action": "dana_hit_fdc_inquiry_for_max_platform_check_task",
                "data": fdc_inquiry_data,
                "error": str(e),
            }
        )


@task(queue="dana_loan_agreement_queue")
def dana_generate_auto_lender_agreement_document_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Loan not found!!',
                'loan_id': loan_id,
            }
        )
        return

    lender = loan.lender
    if not lender:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender not found!!',
                'loan_id': loan_id,
            }
        )
        return

    existing_lender_bucket = LenderBucket.objects.filter(
        total_approved=1,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids__approved__contains=[loan_id],
    )
    if existing_lender_bucket:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender bucket already created!!',
                'loan_id': loan_id,
                'lender_bucket_id': existing_lender_bucket.values_list('id', flat=True),
            }
        )
        return

    is_disbursed = False
    if loan.status >= LoanStatusCodes.CURRENT:
        is_disbursed = True

    action_time = timezone.localtime(timezone.now())
    use_fund_transfer = False

    lender_bucket = LenderBucket.objects.create(
        partner_id=lender.user.partner.pk,
        total_approved=1,
        total_rejected=0,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids={"approved": [loan_id], "rejected": []},
        is_disbursed=is_disbursed,
        is_active=False,
        action_time=action_time,
        action_name='Disbursed',
    )

    # generate summary lla
    assign_lenderbucket_xid_to_lendersignature(
        [loan_id], lender_bucket.lender_bucket_xid, is_loan=True
    )
    dana_generate_summary_lender_loan_agreement.delay(lender_bucket.id, use_fund_transfer)

    # cache lender bucket xid for getting application past in lender dashboard
    redis_cache = RedisCacheLoanBucketXidPast()
    redis_cache.set(loan_id, lender_bucket.lender_bucket_xid)


@task(queue="dana_loan_agreement_queue")
def dana_generate_summary_lender_loan_agreement(
    lender_bucket_id,
    use_fund_transfer=False,
    is_new_generate=False,
    is_for_ar_switching=False,
    is_failed_digisign=False,
):
    logger_action_view = 'juloserver.dana.tasks.dana_generate_summary_lender_loan_agreement'

    if is_block_regenerate_document_ars_config_active() and is_for_ar_switching:
        logger.info(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id},
                'message': "blocked from regenerate document due to ar switching",
            }
        )
        return

    lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
    if not lender_bucket:
        logger.error(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id},
                'errors': "LenderBucket tidak ditemukan.",
            }
        )
        return

    try:
        document = Document.objects.get_or_none(
            document_source=lender_bucket_id, document_type="summary_lender_sphp"
        )
        if document and not is_failed_digisign:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id, 'document': document.filename},
                    'errors': "summary lender loan agreement has found",
                }
            )
            return
        partner = Partner.objects.get(pk=lender_bucket.partner_id)
        user = partner.user
        lender = user.lendercurrent
        body = get_summary_loan_agreement_template(lender_bucket, lender, use_fund_transfer)

        if not body:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id},
                    'errors': "Template tidak ditemukan.",
                }
            )
            return

        is_new_or_failed = ""
        if is_new_generate:
            is_new_or_failed = "-new"
        if is_failed_digisign:
            is_new_or_failed = "_new-digisign"

        filename = 'rangkuman_perjanjian_pinjaman-{}{}.pdf'.format(
            lender_bucket.lender_bucket_xid, is_new_or_failed
        )
        file_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error(
                {
                    'action_view': logger_action_view,
                    'data': {'lender_bucket_id': lender_bucket_id},
                    'errors': str(e),
                }
            )
            return

        summary_lla = Document.objects.create(
            document_source=lender_bucket_id,
            document_type='summary_lender_sphp',
            filename=filename,
        )
        document_id = summary_lla.id

        logger.info(
            {
                'action_view': logger_action_view,
                'data': {'lender_bucket_id': lender_bucket_id, 'document_id': summary_lla.id},
                'message': "success create PDF",
            }
        )

        upload_document(document_id, file_path, is_bucket=True)

    except Exception as e:
        logger.error(
            {
                'action_view': 'FollowTheMoney - {}'.format(logger_action_view),
                'data': {'lender_bucket_id': lender_bucket_id},
                'errors': str(e),
            }
        )
        JuloException(e)


@task(queue='dana_global_queue')
def dana_calculate_available_balance(lender_balance_id, snapshot_type, **lender_balance_kwargs):
    lender_balance = LenderBalanceCurrent.objects.get_or_none(pk=lender_balance_id)
    if not lender_balance:
        raise JuloException("Lender balance current not found")
    is_delay = lender_balance_kwargs.get('is_delay', True)
    loan_amount = lender_balance_kwargs.get('loan_amount', 0)
    repayment_amount = lender_balance_kwargs.get('repayment_amount', 0)
    withdrawal_amount = lender_balance_kwargs.pop('withdrawal_amount', 0)
    available_balance = get_available_balance(lender_balance.lender_id)

    pending_withdrawal = lender_balance.pending_withdrawal + withdrawal_amount

    remaining_balance = available_balance - loan_amount + repayment_amount - pending_withdrawal
    lender_balance_kwargs['available_balance'] = remaining_balance
    lender_balance_kwargs['pending_withdrawal'] = pending_withdrawal

    # Remove unused key
    lender_balance_kwargs.pop('loan_amount', None)
    lender_balance_kwargs.pop('repayment_amount', None)
    lender_balance_kwargs.pop('is_delay', None)

    logger.info(
        {
            'task': 'juloserver.dana.loan.tasks.dana_calculate_available_balance',
            'message': 'start deposit lender balance for {}'.format(lender_balance_id),
        }
    )
    if remaining_balance < 0:
        logger.error(
            {
                "task": "juloserver.dana.loan.tasks.dana_calculate_available_balance",
                "message": "Available balance insufficient",
                "lender_balance_id": lender_balance_id,
                "snapshot_type": snapshot_type,
                "kwargs": lender_balance_kwargs,
            }
        )
        # raise JuloException("Available balance insufficient")

    # Update lender balance
    lender_balance.update_safely(**lender_balance_kwargs)

    # Insert lender balance history
    if is_delay:
        insert_data_into_lender_balance_history.delay(
            lender_balance, pending_withdrawal, snapshot_type, remaining_balance
        )
    else:
        insert_data_into_lender_balance_history(
            lender_balance, pending_withdrawal, snapshot_type, remaining_balance
        )

    return available_balance
