import math
from collections import namedtuple
from datetime import date, datetime
import os
import io
import csv
import time
import uuid
from typing import (
    Dict,
    Tuple,
    Union,
    List,
)
import logging

from bulk_update.helper import bulk_update
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from juloserver.account.models import Account
from juloserver.account_payment.models import (
    AccountPayment,
    AccountPaymentNote,
)
from juloserver.account_payment.services.collection_related import (
    update_ptp_for_paid_off_account_payment,
    ptp_update_for_j1,
)

from juloserver.fdc.files import TempDir
from juloserver.julo.models import (
    PaybackTransaction,
    Payment,
    PaymentNote,
    PaymentEvent,
    PTP,
    CootekRobocall,
    UploadAsyncState,
)
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely,
)
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import upload_file_to_oss

from juloserver.account.models import (
    AccountLimit,
    AccountTransaction,
)

from juloserver.loan.services.loan_related import update_loan_status_and_loan_history

from juloserver.dana.models import (
    DanaPaymentBill,
    DanaRepaymentReference,
    DanaCustomerData,
    DanaRepaymentReferenceHistory,
    DanaRepaymentReferenceStatus,
)
from juloserver.dana.constants import (
    BILL_STATUS_PAID_OFF,
    DanaProductType,
    MAX_LATE_FEE_APPLIED,
    DANA_REPAYMENT_SETTLEMENT_HEADERS,
    BILL_STATUS_PARTIAL,
    RepaymentReferenceStatus,
)
from juloserver.dana.repayment.serializers import DanaRepaymentSettlementSerializer
from juloserver.dana.utils import construct_massive_logger, set_redis_key

from juloserver.minisquad.tasks2.intelix_task import (
    delete_paid_payment_from_intelix_if_exists_async_for_j1,
)
from juloserver.cootek.tasks import cancel_phone_call_for_payment_paid_off
from juloserver.minisquad.tasks2.dialer_system_task import delete_paid_payment_from_dialer
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting

logger = logging.getLogger(__name__)


def update_late_fee_amount(payment_id: int) -> None:
    try:
        with transaction.atomic(using='partnership_db'):
            dana_payment_bill = (
                DanaPaymentBill.objects.select_for_update().filter(payment_id=payment_id).last()
            )

            if not dana_payment_bill:
                logger.error(
                    {
                        "action": "dana_payment_bill_not_found",
                        "message": "Failed to get dana payment bill",
                        "payment_id": payment_id,
                    }
                )
                return

            payment = Payment.objects.get(id=payment_id)
            dana_loan_reference = payment.loan.danaloanreference

            if payment.status in PaymentStatusCodes.paid_status_codes():
                return

            if payment.late_fee_applied >= MAX_LATE_FEE_APPLIED:
                return
            today = date.today()
            due_amount_before = payment.due_amount
            principal_amount = payment.installment_principal - payment.paid_principal
            interest_amount = payment.installment_interest - payment.paid_interest
            bill_amount = principal_amount + interest_amount
            late_fee = dana_loan_reference.late_fee_rate / 100
            raw_late_fee = bill_amount * late_fee
            rounded_late_fee = math.ceil(raw_late_fee)
            if rounded_late_fee <= 0:
                return
            payment.apply_late_fee(rounded_late_fee)
            dana_payment_bill.late_fee_amount += rounded_late_fee
            dana_payment_bill.total_amount += rounded_late_fee
            dana_payment_bill.save(update_fields=['late_fee_amount', 'total_amount'])

            try:
                with transaction.atomic(using='default'):
                    payment_event = PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=-rounded_late_fee,
                        event_due_amount=due_amount_before,
                        event_date=today,
                        event_type='late_fee',
                    )
                    account_payment = AccountPayment.objects.select_for_update().get(
                        pk=payment.account_payment_id
                    )
                    account_payment.update_late_fee_amount(payment_event.event_payment)
                    account_transaction, created = AccountTransaction.objects.get_or_create(
                        account=account_payment.account,
                        transaction_date=payment_event.event_date,
                        transaction_type='late_fee',
                        defaults={
                            'transaction_amount': 0,
                            'towards_latefee': 0,
                            'towards_principal': 0,
                            'towards_interest': 0,
                            'accounting_date': payment_event.event_date,
                        },
                    )
                    if created:
                        account_transaction.transaction_amount = payment_event.event_payment
                        account_transaction.towards_latefee = payment_event.event_payment
                    else:
                        account_transaction.transaction_amount += payment_event.event_payment
                        account_transaction.towards_latefee += payment_event.event_payment
                    account_transaction.save(
                        update_fields=['transaction_amount', 'towards_latefee']
                    )
                    payment_event.account_transaction = account_transaction
                    payment_event.save(update_fields=['account_transaction'])
                    logger.info(
                        {
                            "action": "successfully_generate_dana_late_fee",
                            "message": "Successfully generated dana late fee",
                            "payment_id": payment_id,
                        }
                    )

            except Exception as e:
                logger.exception(
                    {
                        'module': 'update_late_fee_amount',
                        'action': 'transaction using julodb',
                        'error': e,
                    }
                )
                raise e

    except Exception as e:
        logger.exception(
            {
                'module': 'update_late_fee_amount',
                'action': 'transaction using partnership_db',
                'error': e,
            }
        )
        raise e


def update_account_payment_late_fee_amount(account_payment, late_fee):
    account_payment.late_fee_amount += abs(late_fee)
    account_payment.due_amount += abs(late_fee)

    if account_payment.late_fee_applied:
        account_payment.late_fee_applied += 1
    else:
        account_payment.late_fee_applied = 1


def new_update_late_fee_amount(account_payment_dicts: dict) -> None:
    today = date.today()
    account_payment_list, account_transaction_list, payment_event_list = [], [], []

    with transaction.atomic(using='partnership_db'):
        for ap in account_payment_dicts:
            ap_dict = account_payment_dicts.get(ap)

            if not ap_dict.get("dana_payment_bill"):
                logger.error(
                    {
                        "action": "dana_payment_bill_not_found",
                        "message": "Failed to get dana payment bill",
                        "payment_id": ap_dict.get("payment").id,
                    }
                )
                return

            payment = ap_dict.get("payment")
            account_payment = ap_dict.get("account_payment")
            dana_payment_bill = ap_dict.get("dana_payment_bill")
            dana_loan_reference = payment.loan.danaloanreference

            if payment.status in PaymentStatusCodes.paid_status_codes():
                return

            if payment.late_fee_applied >= MAX_LATE_FEE_APPLIED:
                return

            due_amount_before = payment.due_amount
            principal_amount = payment.installment_principal - payment.paid_principal
            interest_amount = payment.installment_interest - payment.paid_interest
            bill_amount = principal_amount + interest_amount
            late_fee = dana_loan_reference.late_fee_rate / 100
            raw_late_fee = bill_amount * late_fee
            rounded_late_fee = math.ceil(raw_late_fee)

            if rounded_late_fee <= 0:
                return
            payment.apply_late_fee(rounded_late_fee)
            dana_payment_bill.late_fee_amount += rounded_late_fee
            dana_payment_bill.total_amount += rounded_late_fee
            dana_payment_bill.save(update_fields=["late_fee_amount", "total_amount"])

            payment_event = PaymentEvent(
                payment=payment,
                event_payment=-rounded_late_fee,
                event_due_amount=due_amount_before,
                event_date=today,
                event_type="late_fee",
            )

            payment_event_list.append(payment_event)

            update_account_payment_late_fee_amount(account_payment, payment_event.event_payment)
            account_payment_list.append(account_payment)

            account_transaction, created = AccountTransaction.objects.get_or_create(
                account=account_payment.account,
                transaction_date=payment_event.event_date,
                transaction_type="late_fee",
                defaults={
                    "transaction_amount": 0,
                    "towards_latefee": 0,
                    "towards_principal": 0,
                    "towards_interest": 0,
                    "accounting_date": payment_event.event_date,
                },
            )

            if created:
                account_transaction.transaction_amount = payment_event.event_payment
                account_transaction.towards_latefee = payment_event.event_payment
            else:
                account_transaction.transaction_amount += payment_event.event_payment
                account_transaction.towards_latefee += payment_event.event_payment
            account_transaction_list.append(account_transaction)

            payment_event.account_transaction = account_transaction

    with transaction.atomic(using='default'):
        bulk_update(
            account_payment_list,
            update_fields=["late_fee_applied", "late_fee_amount", "due_amount"],
            batch_size=100,
        )

        bulk_update(
            account_transaction_list,
            update_fields=["transaction_amount", "towards_latefee"],
            batch_size=100,
        )
        PaymentEvent.objects.bulk_create(payment_event_list)


def store_calculated_payments(
    payment,
    paid_date,
    payment_receipt,
    payment_method,
    old_payment_detail,
    bill_status,
    event_type=None,
    note='',
):
    from juloserver.followthemoney.services import create_manual_transaction_mapping

    payment_events = []
    total_paid_amount = payment.paid_amount - old_payment_detail["paid_amount"]
    if total_paid_amount > 0:
        total_payment_amount = (
            payment.installment_principal + payment.installment_interest + payment.late_fee_amount
        )
        re_calculate_due_amount = total_payment_amount - payment.paid_amount
        event_due_amount = re_calculate_due_amount + total_paid_amount

        payment_event = PaymentEvent.objects.create(
            payment=payment,
            event_payment=total_paid_amount,
            event_due_amount=event_due_amount,
            event_date=paid_date,
            event_type='payment',
            payment_receipt=payment_receipt,
            payment_method=payment_method,
            can_reverse=False,  # reverse (void) must be via account payment level
        )
        payment_events.append(payment_event)
        paid_principal = payment.paid_principal - old_payment_detail["paid_principal"]
        paid_interest = payment.paid_interest - old_payment_detail["paid_interest"]
        paid_late_fee = payment.paid_late_fee - old_payment_detail["paid_late_fee"]
        create_manual_transaction_mapping(
            payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee
        )

        payment.udate = timezone.localtime(timezone.now())
        payment.paid_date = paid_date
        payment_update_fields = [
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
            'paid_amount',
            'due_amount',
            'paid_date',
            'udate',
            'late_fee_amount',
        ]

        loan = payment.loan
        payment_history = {
            'payment_old_status_code': payment.status,
            'loan_old_status_code': loan.status,
        }
        if bill_status == BILL_STATUS_PAID_OFF:
            update_payment_paid_off_status(payment)
            payment_update_fields.append('payment_status')

        payment.save(update_fields=payment_update_fields)

        # take care loan level
        unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
        if len(unpaid_payments) == 0:  # this mean loan is paid_off
            # Handling checking if is already paid off, Because there is case payment failure
            if loan.status != LoanStatusCodes.PAID_OFF:
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.PAID_OFF,
                    change_by_id=None,
                    change_reason="Loan paid off",
                )
            loan.refresh_from_db()

            # Handling if there is partial paid but loan is already paid
            # Need to create history also
            if bill_status == BILL_STATUS_PARTIAL and loan.status == LoanStatusCodes.PAID_OFF:
                payment.create_payment_history(payment_history)

        elif bill_status == BILL_STATUS_PAID_OFF:
            current_loan_status = loan.status
            loan.update_status(record_history=False)
            if current_loan_status != loan.status:
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=loan.status,
                    change_by_id=None,
                    change_reason="update loan status after payment paid off",
                )

        if bill_status == BILL_STATUS_PAID_OFF:
            payment.create_payment_history(payment_history)

        note = ',\nnote: %s' % note
        note_payment_method = ',\n'
        if payment_method:
            note_payment_method += (
                'payment_method: %s,\n\
                        payment_receipt: %s'
                % (payment_method.payment_method_name, payment_event.payment_receipt)
            )
        template_note = (
            '[Add Event %s]\n\
                    amount: %s,\n\
                    date: %s%s%s.'
            % (
                event_type,
                display_rupiah(payment_event.event_payment),
                payment_event.event_date.strftime("%d-%m-%Y"),
                note_payment_method,
                note,
            )
        )

        PaymentNote.objects.create(note_text=template_note, payment=payment)
        # Do A refresh because need get last data for updating account_payment
        payment.refresh_from_db()

    return payment_events


def update_account_limit(change_limit_amount: int, account_id: int, loan_id: int = None) -> None:
    account_limit = AccountLimit.objects.select_for_update().filter(account_id=account_id).last()
    new_available_limit = account_limit.available_limit + change_limit_amount
    if new_available_limit > account_limit.max_limit:
        new_available_limit = account_limit.max_limit
    new_used_limit = account_limit.used_limit - change_limit_amount

    logger.info(
        {
            'action': 'dana_repayment_replenish_account_limit',
            'loan_id': loan_id,
            'amount': change_limit_amount,
            'old_available_limit': account_limit.available_limit,
            'old_used_limit': account_limit.used_limit,
            'new_available_limit': new_available_limit,
            'new_used_limit': new_used_limit,
        }
    )

    account_limit.update_safely(available_limit=new_available_limit, used_limit=new_used_limit)


def update_account_payment_paid_off_status(account_payment):
    from juloserver.julo.statuses import PaymentStatusCodes

    if account_payment.paid_late_days <= 0:
        account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
    elif account_payment.paid_late_days < Payment.GRACE_PERIOD_DAYS:
        account_payment.status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
    else:
        account_payment.status_id = PaymentStatusCodes.PAID_LATE


def update_payment_paid_off_status(payment):
    if payment.paid_late_days <= 0:
        payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
    elif payment.paid_late_days < Payment.GRACE_PERIOD_DAYS:
        payment.payment_status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
    else:
        payment.payment_status_id = PaymentStatusCodes.PAID_LATE


def consume_paid_amount_for_payment(
    repayments_data: Dict, payback_transaction: PaybackTransaction, reference_no: str
) -> Tuple:
    paid_amount_account_payments = {}
    payment_events = []
    bill_ids = []
    list_partner_reference_no = []
    dana_repayment_reference_list = []

    repayment_id = repayments_data.get('additionalInfo', {}).get('repaymentId', '')
    float_credit_usage_mutation = float(
        repayments_data.get('creditUsageMutation', {}).get('value', 0)
    )
    credit_usage_mutation = int(float_credit_usage_mutation)

    bill_ids = [
        repayment_detail['billId'] for repayment_detail in repayments_data['repaymentDetailList']
    ]
    dana_payment_bills = DanaPaymentBill.objects.filter(bill_id__in=bill_ids)
    dana_payment_bill_mapping = {
        dana_payment_bill.bill_id: dana_payment_bill for dana_payment_bill in dana_payment_bills
    }

    payment_ids = [dana_payment_bill.payment_id for dana_payment_bill in dana_payment_bills]
    payments = Payment.objects.filter(id__in=payment_ids)
    payment_mapping = {payment.id: payment for payment in payments}

    for repayment_detail in repayments_data['repaymentDetailList']:
        dana_payment_bill = dana_payment_bill_mapping.get(repayment_detail['billId'])
        payment = payment_mapping.get(dana_payment_bill.payment_id)

        paid_principal = int(float(repayment_detail['repaymentPrincipalAmount']['value']))
        paid_interest = int(float(repayment_detail['repaymentInterestFeeAmount']['value']))
        paid_late_fee = int(float(repayment_detail['repaymentLateFeeAmount']['value']))
        total_paid_amount = int(float(repayment_detail['totalRepaymentAmount']['value']))
        old_payment_detail = {
            "paid_late_fee": payment.paid_late_fee,
            "paid_principal": payment.paid_principal,
            "paid_interest": payment.paid_interest,
            "paid_amount": payment.paid_amount,
        }
        payment.paid_principal += paid_principal
        payment.paid_interest += paid_interest
        payment.paid_late_fee += paid_late_fee
        payment.paid_amount += total_paid_amount

        # Check status Bill to calculate due_amount and late_fee_amount
        bill_status = repayment_detail['billStatus']

        # additional dictionary data for payment event
        data = {
            "danaLateFeeAmount": paid_late_fee,
            "transactionDate": timezone.localtime(timezone.now()).date(),
            'partnerReferenceNo': repayments_data['partnerReferenceNo'],
        }

        if bill_status == BILL_STATUS_PAID_OFF:
            """
            This code it's mean if bill status is "PAID",
            we can assume payment should be paid off
            That's why we need to set the due amount as 0
            and check if payment.late_fee_amount not equal with paid_late_fee
            we need replace that because source of truth is Dana (paid_late_fee)
            """
            payment.due_amount = 0

            if payment.late_fee_amount != payment.paid_late_fee:
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

        elif bill_status == BILL_STATUS_PARTIAL:
            """
            This else for "INIT" case,
            Do calculate if this bill_id have payment before as PAID
            No need to calculate again the due amount since due_amount is 0
            handle it in "PAID" case, if not paid before do a normal reduce the due amount
            And if the payment paid before this need to make a same
            paid_late_fee == late_fee_amount
            """

            if (
                payment.status in PaymentStatusCodes.paid_status_codes()
                and payment.paid_late_fee != payment.late_fee_amount
            ):
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

            if payment.status not in PaymentStatusCodes.paid_status_codes():
                payment.due_amount -= total_paid_amount

                """
                This case when INIT send but late fee in DANA greater than late fee in JULO
                Need to set as 0
                """
                if payment.due_amount < 0:
                    payment.due_amount = 0

        payment_events += store_calculated_payments(
            payment,
            payback_transaction.transaction_date.date(),
            payback_transaction.transaction_id,
            payback_transaction.payment_method,
            old_payment_detail,
            bill_status,
            None,
            note='',
        )

        account_payment_id = payment.account_payment_id
        if account_payment_id not in paid_amount_account_payments:
            paid_amount_account_payments[account_payment_id] = {
                'paid_principal': paid_principal,
                'paid_interest': paid_interest,
                'paid_late_fee': paid_late_fee,
                'total_paid_amount': total_paid_amount,
            }
        else:
            paid_amount_account_payments[account_payment_id]['paid_principal'] += paid_principal
            paid_amount_account_payments[account_payment_id]['paid_interest'] += paid_interest
            paid_amount_account_payments[account_payment_id]['paid_late_fee'] += paid_late_fee
            paid_amount_account_payments[account_payment_id][
                'total_paid_amount'
            ] += total_paid_amount

        repaid_time = parse_datetime(repayments_data['repaidTime'])

        waived_principal_amount = None
        waived_interest_fee_amount = None
        waived_late_fee_amount = None
        total_waived_amount = None
        waived_principal = repayment_detail.get('waivedPrincipalAmount')
        if waived_principal:
            waived_principal_amount = int(float(waived_principal.get('value', 0)))

        waived_interest_fee = repayment_detail.get('waivedInterestFeeAmount')
        if waived_interest_fee:
            waived_interest_fee_amount = int(float(waived_interest_fee.get('value', 0)))

        waived_late_fee = repayment_detail.get('waivedLateFeeAmount')
        if waived_late_fee:
            waived_late_fee_amount = int(float(waived_late_fee.get('value', 0)))

        total_waived = repayment_detail.get('totalWaivedAmount')
        if total_waived:
            total_waived_amount = int(float(total_waived.get('value', 0)))

        repayment_data = {
            'payment': payment,
            'partner_reference_no': repayments_data['partnerReferenceNo'],
            'customer_id': repayments_data['customerId'],
            'reference_no': reference_no,
            'bill_id': repayment_detail['billId'],
            'bill_status': repayment_detail['billStatus'],
            'principal_amount': paid_principal,
            'interest_fee_amount': paid_interest,
            'late_fee_amount': paid_late_fee,
            'total_repayment_amount': total_paid_amount,
            'repaid_time': repaid_time,
            'repayment_id': repayment_id,
            'credit_usage_mutation': credit_usage_mutation,
            'lender_product_id': repayments_data.get('lenderProductId'),
            'waived_principal_amount': waived_principal_amount,
            'waived_interest_fee_amount': waived_interest_fee_amount,
            'waived_late_fee_amount': waived_late_fee_amount,
            'total_waived_amount': total_waived_amount,
        }

        dana_repayment_reference = DanaRepaymentReference(**repayment_data)
        dana_repayment_reference_list.append(dana_repayment_reference)

        list_partner_reference_no.append(repayments_data['partnerReferenceNo'])
        bill_ids.append(repayment_detail['billId'])

    # Create Dana Repayment Reference and Dana Repayment Reference Status
    DanaRepaymentReference.objects.bulk_create(dana_repayment_reference_list, batch_size=30)

    created_dana_repayment_references = DanaRepaymentReference.objects.filter(
        partner_reference_no__in=list_partner_reference_no,
        bill_id__in=bill_ids,
    )

    dana_repayment_reference_status_list = []
    for repayment_reference in created_dana_repayment_references.iterator():
        dana_repayment_reference_status_list.append(
            DanaRepaymentReferenceStatus(
                dana_repayment_reference_id=repayment_reference.id,
                status=RepaymentReferenceStatus.SUCCESS,
            )
        )

    DanaRepaymentReferenceStatus.objects.bulk_create(
        dana_repayment_reference_status_list, batch_size=30
    )

    return paid_amount_account_payments, payment_events


def consume_paid_amount_for_account_payment(
    paid_amount_account_payments: Dict, payback_transaction: PaybackTransaction
) -> Tuple:
    total_paid_principal = 0
    total_paid_interest = 0
    total_paid_late_fee = 0
    account_payment_note_list = []
    for account_payment_id, paid_amount_account_payment in paid_amount_account_payments.items():
        account_payment = AccountPayment.objects.select_for_update().get(pk=account_payment_id)

        existing_account_payment = account_payment.payment_set.aggregate(
            total_due_amount=Sum('due_amount'), total_late_fee_amount=Sum('late_fee_amount')
        )
        accumulated_payment_due_amount = existing_account_payment['total_due_amount'] or 0
        accumulated_total_late_fee_amount = existing_account_payment['total_late_fee_amount'] or 0

        account_payment.paid_date = payback_transaction.transaction_date.date()
        account_payment.paid_principal += paid_amount_account_payment['paid_principal']
        account_payment.paid_interest += paid_amount_account_payment['paid_interest']
        account_payment.paid_late_fee += paid_amount_account_payment['paid_late_fee']
        account_payment.paid_amount += paid_amount_account_payment['total_paid_amount']

        """
            Need recalculate late_fee_amount and due_amount because we need to consume
            related all payment especially due_amount and late_fee_amount
            because there is always mismatch related late_fee_amount makes due_amount minus
            check if total account_payment.late_fee_amount not equal
            With SUM payment.late_fee_amount
            we need replace that because source of truth is Dana (paid_late_fee)
            because in payment.paid_late_fee == payment.late_fee_amount
        """
        if accumulated_total_late_fee_amount != account_payment.late_fee_amount:
            account_payment.late_fee_amount = accumulated_total_late_fee_amount

        account_payment.due_amount = accumulated_payment_due_amount

        if account_payment.due_amount == 0:
            history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
            update_account_payment_paid_off_status(account_payment)
            account_payment.create_account_payment_status_history(history_data)

        account_payment.udate = timezone.localtime(timezone.now())
        account_payment.save(
            update_fields=[
                'due_amount',
                'paid_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_date',
                'status',
                'udate',
                'late_fee_amount',
            ]
        )

        note = ',\nnote: '
        note_payment_method = ',\n'
        if payback_transaction.payment_method:
            note_payment_method += (
                'payment_method: %s,\n\
                                    payment_receipt: %s'
                % (
                    payback_transaction.payment_method.payment_method_name,
                    payback_transaction.transaction_id,
                )
            )
        template_note = (
            '[Add Event %s]\n\
                                amount: %s,\n\
                                date: %s%s%s.'
            % (
                'payment',
                display_rupiah(
                    paid_amount_account_payment['paid_principal']
                    + paid_amount_account_payment['paid_interest']
                    + paid_amount_account_payment['paid_late_fee']
                ),
                payback_transaction.transaction_date.strftime("%d-%m-%Y"),
                note_payment_method,
                note,
            )
        )
        account_payment_note_list.append(
            AccountPaymentNote(note_text=template_note, account_payment=account_payment)
        )
        total_paid_principal += paid_amount_account_payment['paid_principal']
        total_paid_interest += paid_amount_account_payment['paid_interest']
        total_paid_late_fee += paid_amount_account_payment['paid_late_fee']
        if account_payment.due_amount == 0:
            update_ptp_for_paid_off_account_payment(account_payment)
            # fmt: off
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(paid_off_id)
            )
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_dialer.delay(paid_off_id)
            )

            # fmt: on
            # this will update ptp_status
            today = timezone.localtime(timezone.now()).date()
            ptp = PTP.objects.filter(ptp_date__gte=today, account_payment=account_payment).last()
            if ptp:
                ptp.update_safely(ptp_status='Paid')
            # handle cootek
            account_payment_form_cootek = CootekRobocall.objects.filter(
                account_payment=account_payment
            ).last()
            if account_payment_form_cootek:
                cancel_phone_call_for_payment_paid_off.delay(account_payment_form_cootek.id)
        else:
            # this will handle partial account payment updates
            ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

    AccountPaymentNote.objects.bulk_create(account_payment_note_list, batch_size=30)

    return total_paid_principal, total_paid_interest, total_paid_late_fee


def construct_repayment_redis_key(payload: Dict) -> Union[None, str]:
    try:
        payload['repaymentDetailList'].sort(key=lambda item: item['billId'])
        bill_info = []
        for repayment_detail in payload['repaymentDetailList']:
            total_repayment_amount = (
                repayment_detail.get('total_repayment_amount')
                or repayment_detail.get('totalRepaymentAmount').get('value').split('.')[0]
            )
            bill_info.append(
                "{}+{}+{}".format(
                    repayment_detail['billId'],
                    repayment_detail['billStatus'],
                    total_repayment_amount,
                )
            )
        key = "{}+{}+{}".format(payload['partnerReferenceNo'], payload['customerId'], bill_info)
    except (KeyError, AttributeError, IndexError):
        logger.error(
            {
                "action": "dana_construct_repayment_redis_key",
                "message": "error when construct key",
                "payload": payload,
            }
        )
        return None

    return key


def upload_dana_csv_data_to_oss(upload_async_state, file_path=None):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path
    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    dest_name = "dana/{}/{}".format(upload_async_state.id, file_name_elements[-1] + extension)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def write_row_result(
    row: Dict, is_inserted: bool, is_valid: bool, errors: str = '', action: str = '', note: str = ''
) -> List:
    return [
        is_inserted,
        is_valid,
        row.get('partnerId'),
        row.get('lenderProductId'),
        "'{}".format(row.get('partnerReferenceNo')),
        "'{}".format(row.get('billId')),
        row.get('billStatus'),
        row.get('principalAmount'),
        row.get('interestFeeAmount'),
        row.get('lateFeeAmount'),
        row.get('totalAmount'),
        row.get('transTime'),
        row.get('waivedPrincipalAmount'),
        row.get('waivedInterestFeeAmount'),
        row.get('waivedLateFeeAmount'),
        row.get('totalWaivedAmount'),
        errors,
        action,
        note,
    ]


def process_dana_repayment_settlement_result(
    upload_async_state: UploadAsyncState, product: str
) -> bool:
    upload_file = upload_async_state.file
    f = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(f, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(DANA_REPAYMENT_SETTLEMENT_HEADERS)

            for row in reader:
                formatted_data = dict(row)
                serializer = DanaRepaymentSettlementSerializer(
                    data=formatted_data,
                )

                if not serializer.is_valid():
                    is_success_all = False
                    is_inserted = False
                    is_valid = False
                    error_list = serializer.errors.get('non_field_errors')
                    error_str = ', '.join(error_list)
                    action = 'not_updated'
                    note = 'Failed when do format data, please re-check the data'
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    continue

                validated_data = serializer.validated_data
                partner_reference_no = validated_data['partnerReferenceNo']
                bill_id = validated_data['billId']

                if validated_data['lenderProductId'] != product:
                    is_success_all = False
                    is_inserted = False
                    is_valid = False
                    error_str = 'Invalid lenderProductId'
                    action = 'not_updated'
                    note = 'lenderProductId did not match with the chosen Product'
                    write.writerow(
                        write_row_result(
                            formatted_data, is_inserted, is_valid, error_str, action, note
                        )
                    )
                    continue

                dana_repayment_reference = DanaRepaymentReference.objects.filter(
                    partner_reference_no=partner_reference_no, bill_id=bill_id
                ).last()

                if dana_repayment_reference:
                    errors = []
                    principal_amount = float(validated_data['principalAmount'])
                    interest_fee_amount = float(validated_data['interestFeeAmount'])
                    late_fee_amount = float(validated_data['lateFeeAmount'])
                    total_repayment_amount = float(validated_data['totalAmount'])

                    existing_principal_amount = dana_repayment_reference.principal_amount
                    existing_interest_fee_amount = dana_repayment_reference.interest_fee_amount
                    existing_late_fee_amount = dana_repayment_reference.late_fee_amount
                    existing_total_repayment_amount = (
                        dana_repayment_reference.total_repayment_amount
                    )

                    is_match_principal = int(principal_amount) == existing_principal_amount
                    is_match_interest_fee_amount = (
                        int(interest_fee_amount) == existing_interest_fee_amount
                    )
                    is_match_late_fee_amount = int(late_fee_amount) == existing_late_fee_amount
                    is_match_total_repayment_amount = (
                        int(total_repayment_amount) == existing_total_repayment_amount
                    )

                    is_inserted = False
                    is_valid = True
                    error_str = '-'
                    action = 'data_is_similar_no_need_to_update'
                    note = 'No need update data, the data is already match'
                    if (
                        not is_match_principal
                        or not is_match_interest_fee_amount
                        or not is_match_late_fee_amount
                        or not is_match_total_repayment_amount
                    ):
                        # TODO-DANA: Do processing reverse data
                        if not is_match_principal:
                            errors.append('Principal amount with existing value not match')

                        if not is_match_interest_fee_amount:
                            errors.append('Interest amount with existing value not match')

                        if not is_match_late_fee_amount:
                            errors.append('Late Fee amount with existing value not match')

                        if not is_match_total_repayment_amount:
                            errors.append('Total Repayment amount with existing value not match')

                        is_inserted = False
                        is_valid = False
                        error_str = ', '.join(errors)
                        action = 'need_to_update_existing_data'
                        note = 'Several data is not match, need to re-calculate'
                else:
                    dana_payment_bill = DanaPaymentBill.objects.filter(bill_id=bill_id).last()
                    payment_id = dana_payment_bill.payment_id
                    payment = Payment.objects.get(id=payment_id)

                    loan = payment.loan
                    action = 'no_need_to_add_data'
                    is_inserted = False
                    is_valid = False

                    if loan.status < LoanStatusCodes.CURRENT:
                        """
                        Invalid loan status
                        """
                        error_str = 'Invalid loan status'
                        note = 'Amount have invalid status Probably Canceled/Reject/On Going'
                        write.writerow(
                            write_row_result(
                                formatted_data, is_inserted, is_valid, error_str, action, note
                            )
                        )
                        continue

                    # Success process
                    is_inserted = True
                    is_valid = True
                    is_recalculated = True
                    if hasattr(loan.danaloanreference, 'danaloanreferenceinsufficienthistory'):
                        dana_loan_reference = loan.danaloanreference
                        is_recalculated = (
                            dana_loan_reference.danaloanreferenceinsufficienthistory.is_recalculated
                        )

                    # for event payment needed
                    validated_data['danaLateFeeAmount'] = late_fee_amount
                    create_manual_repayment_settlement(
                        validated_data, is_recalculated=is_recalculated
                    )
                    error_str = '-'
                    action = 'inserted_new_data'
                    note = 'Creating New data because partner_reference_no or bill_id not match'

                write.writerow(
                    write_row_result(formatted_data, is_inserted, is_valid, error_str, action, note)
                )

        upload_dana_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def recalculate_payment_event(payment_events: QuerySet, payment: Payment, data: Dict) -> None:
    dana_late_fee_amount = data['danaLateFeeAmount']
    transaction_date = data['transactionDate']
    partner_reference_no = data['partnerReferenceNo']

    total_late_fee_payment = sum(
        abs(event.event_payment) for event in payment_events if event.event_type == 'late_fee'
    )

    # Check if already created
    def event_exists(event_type: str) -> bool:
        return PaymentEvent.objects.filter(
            payment=payment,
            event_type=event_type,
            payment_receipt=partner_reference_no,
        ).exists()

    if total_late_fee_payment < dana_late_fee_amount:
        evt_type = 'late_fee'
        if not event_exists(evt_type):
            event_payment = dana_late_fee_amount - total_late_fee_payment
            PaymentEvent.objects.create(
                payment=payment,
                event_payment=-event_payment,
                event_due_amount=0,
                event_date=transaction_date,
                event_type=evt_type,
                payment_receipt=partner_reference_no,
                can_reverse=False,
            )
    elif total_late_fee_payment > dana_late_fee_amount:
        evt_type = 'late_fee_void'
        if not event_exists(evt_type):
            event_payment = dana_late_fee_amount - total_late_fee_payment
            PaymentEvent.objects.create(
                payment=payment,
                event_payment=abs(event_payment),
                event_due_amount=0,
                event_date=transaction_date,
                event_type=evt_type,
                payment_receipt=partner_reference_no,
                can_reverse=False,
            )


@transaction.atomic
def create_manual_repayment_settlement(
    data: Dict,
    is_pending_process: bool = False,
    is_refund: bool = False,
    is_recalculated: bool = True,
) -> None:
    """
    is_pending_process: This flag for exclude re-create dana_repayment_reference
    Since for pending process dana_repayment_reference created in API but status is pending

    Refund Case:
    - is_void_late_fee: this for refund case, we need to waived late fee as 0
    - in refund case late_fee_amount will be set to 0.0 and status should be send as PAID
    - So there will be calculated late fee as 0.0 as well
    - PaymentEvent late_fee update to 0.0 as well
    - if is_pending_process & is_void_late_fee true this should be refund process
    - because no need to create dana_repayment_reference and waived the late fee
    """

    try:
        from juloserver.dana.repayment.tasks import account_reactivation
        from juloserver.followthemoney.services import create_manual_transaction_mapping

        lender_product_id = data.get('lenderProductId', '')
        repayment_id = data.get('repaymentId', '')
        credit_usage_mutation = data.get('creditUsageMutation')
        if credit_usage_mutation:
            credit_usage_mutation = int(credit_usage_mutation)
        float_total_amount = float(data['totalAmount'])
        float_principal_amount = float(data['principalAmount'])
        float_interest_fee_amount = float(data['interestFeeAmount'])
        float_late_fee_amount = float(data['lateFeeAmount'])

        total_amount = int(float_total_amount)
        principal_amount = int(float_principal_amount)
        interest_fee_amount = int(float_interest_fee_amount)
        late_fee_amount = int(float_late_fee_amount)

        bill_status = data['billStatus']
        reference_no = str(uuid.uuid4())
        repaid_time = data['transTime']
        transaction_date = parse_datetime(repaid_time)
        data['transactionDate'] = transaction_date

        dana_payment_bill = DanaPaymentBill.objects.filter(bill_id=data['billId']).last()
        payment_id = dana_payment_bill.payment_id
        payment = Payment.objects.get(id=payment_id)

        account_payment = AccountPayment.objects.select_for_update().get(
            id=payment.account_payment_id
        )
        loan = payment.loan

        if is_refund:
            if payment.late_fee_amount != 0:
                acc_payment_late_fee_amount = (
                    account_payment.late_fee_amount - payment.late_fee_amount
                )
                acc_payment_paid_amount = account_payment.paid_amount - payment.paid_late_fee
                acc_payment_paid_late_fee = account_payment.paid_late_fee - payment.paid_late_fee
                account_payment.update_safely(
                    late_fee_amount=acc_payment_late_fee_amount,
                    paid_amount=acc_payment_paid_amount,
                    paid_late_fee=acc_payment_paid_late_fee,
                )

                old_paid_payment_late_fee = payment.paid_late_fee
                payment_paid_amount = payment.paid_amount - payment.paid_late_fee
                payment.update_safely(
                    paid_amount=payment_paid_amount,
                    late_fee_applied=0,
                    late_fee_amount=0,
                    paid_late_fee=0,
                )

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

                if old_paid_payment_late_fee != 0:
                    PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=old_paid_payment_late_fee,
                        event_due_amount=0,
                        event_date=transaction_date,
                        event_type='dana_late_fee_void',
                        payment_receipt=data['partnerReferenceNo'],
                        can_reverse=False,
                    )

                    AccountTransaction.objects.create(
                        account=loan.account,
                        transaction_date=transaction_date,
                        transaction_amount=old_paid_payment_late_fee,
                        transaction_type='dana_late_fee_void',
                        towards_principal=0,
                        towards_interest=0,
                        towards_latefee=old_paid_payment_late_fee,
                    )

                late_fee_amount = 0

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

            # void interest
            acc_payment_interest_amount = (
                account_payment.interest_amount - payment.installment_interest
            )
            acc_payment_paid_amount = account_payment.paid_amount - payment.paid_interest
            acc_payment_paid_interest = account_payment.paid_interest - payment.paid_interest
            account_payment.update_safely(
                interest_amount=acc_payment_interest_amount,
                paid_amount=acc_payment_paid_amount,
                paid_interest=acc_payment_paid_interest,
            )

            payment_paid_amount = payment.paid_amount - payment.paid_interest
            payment.update_safely(
                paid_amount=payment_paid_amount,
                installment_interest=0,
                paid_interest=0,
            )

            payment_events = payment.paymentevent_set.filter(event_type='payment').order_by('id')
            if payment_events:
                recalculate_payment_event(payment_events, payment, data)

            interest_for_credit_limit = interest_fee_amount
            interest_fee_amount = 0
            total_amount = principal_amount

        payback_transaction = PaybackTransaction.objects.get_or_none(
            transaction_id=data['partnerReferenceNo']
        )

        if not payback_transaction:
            payback_transaction = PaybackTransaction.objects.create(
                transaction_id=data['partnerReferenceNo'],
                is_processed=False,
                virtual_account=None,
                payment_method=None,
                payback_service='dana',
                amount=total_amount,
                transaction_date=transaction_date,
            )
        elif payback_transaction:
            payback_transaction.amount += total_amount
            payback_transaction.save(update_fields=['amount'])

        # Handle Update Payment
        paid_principal = principal_amount
        paid_interest = interest_fee_amount
        paid_late_fee = late_fee_amount
        total_paid_amount = total_amount

        old_payment_detail = {
            "paid_late_fee": payment.paid_late_fee,
            "paid_principal": payment.paid_principal,
            "paid_interest": payment.paid_interest,
            "paid_amount": payment.paid_amount,
        }

        payment.paid_principal += paid_principal
        payment.paid_interest += paid_interest
        payment.paid_late_fee += paid_late_fee
        payment.paid_amount += total_paid_amount

        if bill_status == BILL_STATUS_PAID_OFF:
            """
            This code it's mean if bill status is "PAID",
            we can assume payment should be paid off
            That's why we need to set the due amount as 0
            and check if payment.late_fee_amount not equal with paid_late_fee
            we need replace that because source of truth is Dana (paid_late_fee)
            """
            payment.due_amount = 0

            if payment.late_fee_amount != payment.paid_late_fee:
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

        elif bill_status == BILL_STATUS_PARTIAL:
            """
            This else for "INIT" case,
            Do calculate if this bill_id have payment before as PAID
            No need to calculate again the due amount since due_amount is 0
            handle it in "PAID" case, if not paid before do a normal reduce the due amount
            And if the payment paid before this need to make a same
            paid_late_fee == late_fee_amount
            """
            if (
                payment.status in PaymentStatusCodes.paid_status_codes()
                and payment.paid_late_fee != payment.late_fee_amount
            ):
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

            if payment.status not in PaymentStatusCodes.paid_status_codes():
                payment.due_amount -= total_paid_amount

                """
                This case when INIT send but late fee in DANA greater than late fee in JULO
                Need to set as 0
                """
                if payment.due_amount < 0:
                    payment.due_amount = 0

        total_payment_paid_amount = payment.paid_amount - old_payment_detail["paid_amount"]
        payment_event = None
        if total_payment_paid_amount > 0:
            paid_date = payback_transaction.transaction_date.date()
            payment_receipt = payback_transaction.transaction_id
            payment_method = payback_transaction.payment_method

            """
            Handle amount event_due_amount scenario
            FULL PAID
            1. 0 + 27_025 -> PAID AMOUNT
            2. 27_025 - 27_025 = 0 -> DUE AMOUNT
            3. 0 + 27_025

            PARTIAL PAID
            1. 0 + 10_000 -> PAID AMOUNT
            2. 27_025 - 10_000 = 17_025 -> DUE AMOUNT
            3. 17_025 + 10_000 = 27_025 -> event_due_amount

            PAID
            1. 10_000 + 17_025 -> PAID AMOUNT
            2. 17_025 - 17_025 = 0 -> DUE AMOUNT
            3. 0 + 17_025 = 17_025 -> event_due_amount
            """

            total_payment_amount = (
                payment.installment_principal
                + payment.installment_interest
                + payment.late_fee_amount
            )
            re_calculate_due_amount = total_payment_amount - payment.paid_amount
            event_due_amount = re_calculate_due_amount + total_payment_paid_amount

            payment_event = PaymentEvent.objects.create(
                payment=payment,
                event_payment=total_payment_paid_amount,
                event_due_amount=event_due_amount,
                event_date=paid_date,
                event_type='payment',
                payment_receipt=payment_receipt,
                payment_method=payment_method,
                can_reverse=False,  # reverse (void) must be via account payment level
            )
            paid_principal = payment.paid_principal - old_payment_detail["paid_principal"]
            paid_interest = payment.paid_interest - old_payment_detail["paid_interest"]
            paid_late_fee = payment.paid_late_fee - old_payment_detail["paid_late_fee"]

            create_manual_transaction_mapping(
                payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee
            )

            payment.udate = timezone.localtime(timezone.now())
            payment.paid_date = paid_date
            payment_update_fields = [
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_amount',
                'due_amount',
                'paid_date',
                'udate',
                'late_fee_amount',
            ]

            loan = payment.loan
            payment_history = {
                'payment_old_status_code': payment.status,
                'loan_old_status_code': loan.status,
            }
            if bill_status == BILL_STATUS_PAID_OFF:
                update_payment_paid_off_status(payment)
                payment_update_fields.append('payment_status')

            payment.save(update_fields=payment_update_fields)

            # take care loan level
            unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
            if len(unpaid_payments) == 0:  # this mean loan is paid_off
                # Handling checking if is already paid off, Because there is case payment failure
                if loan.status != LoanStatusCodes.PAID_OFF:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.PAID_OFF,
                        change_by_id=None,
                        change_reason="Loan paid off",
                    )
                loan.refresh_from_db()

                # Handling if there is partial paid but loan is already paid
                # Need to create history also
                if bill_status == BILL_STATUS_PARTIAL and loan.status == LoanStatusCodes.PAID_OFF:
                    payment.create_payment_history(payment_history)

            elif bill_status == BILL_STATUS_PAID_OFF:
                current_loan_status = loan.status
                loan.update_status(record_history=False)
                if current_loan_status != loan.status:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=loan.status,
                        change_by_id=None,
                        change_reason="update loan status after payment paid off",
                    )

            if bill_status == BILL_STATUS_PAID_OFF:
                payment.create_payment_history(payment_history)

            event_type = 'payment'
            note = 'Dana Settlement Payment'
            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payment_method:
                note_payment_method += (
                    'payment_method: %s,\n\
                            payment_receipt: %s'
                    % (payment_method.payment_method_name, payment_event.payment_receipt)
                )
            template_note = (
                '[Add Event %s]\n\
                        amount: %s,\n\
                        date: %s%s%s.'
                % (
                    event_type,
                    display_rupiah(payment_event.event_payment),
                    payment_event.event_date.strftime("%d-%m-%Y"),
                    note_payment_method,
                    note,
                )
            )

            PaymentNote.objects.create(note_text=template_note, payment=payment)

        # Creating Dana Repayment Reference
        dana_customer_data = DanaCustomerData.objects.filter(
            customer__account__loan__payment=payment
        ).last()

        waived_principal_amount = None
        waived_interest_fee_amount = None
        waived_late_fee_amount = None
        total_waived_amount = None

        waived_principal = data.get('waivedPrincipalAmount')
        if waived_principal:
            waived_principal_amount = int(float(waived_principal))

        waived_interest_fee = data.get('waivedInterestFeeAmount')
        if waived_interest_fee:
            waived_interest_fee_amount = int(float(waived_interest_fee))

        waived_late_fee = data.get('waivedLateFeeAmount')
        if waived_late_fee:
            waived_late_fee_amount = int(float(waived_late_fee))

        total_waived = data.get('totalWaivedAmount')
        if total_waived:
            total_waived_amount = int(float(total_waived))

        if not is_pending_process:
            dana_repayment_reference = DanaRepaymentReference.objects.create(
                payment=payment,
                partner_reference_no=data['partnerReferenceNo'],
                customer_id=dana_customer_data.dana_customer_identifier,
                reference_no=reference_no,
                bill_id=data['billId'],
                bill_status=data['billStatus'],
                principal_amount=paid_principal,
                interest_fee_amount=paid_interest,
                late_fee_amount=paid_late_fee,
                total_repayment_amount=total_paid_amount,
                repaid_time=repaid_time,
                credit_usage_mutation=credit_usage_mutation,
                repayment_id=repayment_id,
                lender_product_id=lender_product_id,
                waived_principal_amount=waived_principal_amount,
                waived_interest_fee_amount=waived_interest_fee_amount,
                waived_late_fee_amount=waived_late_fee_amount,
                total_waived_amount=total_waived_amount,
            )

            DanaRepaymentReferenceStatus.objects.create(
                dana_repayment_reference_id=dana_repayment_reference.id,
                status=RepaymentReferenceStatus.SUCCESS,
            )

        # This need to refresh for preventing mismatch calculation in account payment
        payment.refresh_from_db()

        # Handle Update Account Payment
        # Get SUM amount exclude the payment that in progress
        existing_account_payment = account_payment.payment_set.aggregate(
            total_due_amount=Sum('due_amount'), total_late_fee_amount=Sum('late_fee_amount')
        )
        accumulated_payment_due_amount = existing_account_payment['total_due_amount'] or 0
        accumulated_total_late_fee_amount = existing_account_payment['total_late_fee_amount'] or 0

        old_acc_paid_principal = account_payment.paid_principal
        old_acc_paid_interest = account_payment.paid_interest
        old_acc_paid_late_fee = account_payment.paid_late_fee
        old_acc_paid_amount = account_payment.paid_amount
        old_acc_due_amount = account_payment.due_amount

        account_payment.paid_date = payback_transaction.transaction_date.date()
        account_payment.paid_principal += paid_principal
        account_payment.paid_interest += paid_interest
        account_payment.paid_late_fee += paid_late_fee
        account_payment.paid_amount += total_paid_amount

        """
            Need recalculate late_fee_amount and due_amount because we need to consume
            related all payment especially due_amount and late_fee_amount
            because there is always mismatch related late_fee_amount makes due_amount minus
            check if total account_payment.late_fee_amount not equal
            With SUM payment.late_fee_amount
            we need replace that because source of truth is Dana (paid_late_fee)
            because in payment.paid_late_fee == payment.late_fee_amount
        """
        if accumulated_total_late_fee_amount != account_payment.late_fee_amount:
            account_payment.late_fee_amount = accumulated_total_late_fee_amount

        account_payment.due_amount = accumulated_payment_due_amount

        if account_payment.due_amount == 0:
            history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
            update_account_payment_paid_off_status(account_payment)
            account_payment.create_account_payment_status_history(history_data)

        account_payment.udate = timezone.localtime(timezone.now())
        account_payment.save(
            update_fields=[
                'due_amount',
                'paid_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_date',
                'status',
                'udate',
                'late_fee_amount',
            ]
        )

        logger.info(
            {
                'action': 'dana_repayment_update_account_payment',
                'loan_id': payment.loan_id,
                'account_id': account_payment.account_id,
                'old_account_payment_paid_principal': old_acc_paid_principal,
                'old_account_payment_paid_interest': old_acc_paid_interest,
                'old_account_payment_paid_late_fee': old_acc_paid_late_fee,
                'old_account_payment_paid_amount': old_acc_paid_amount,
                'old_account_payment_due_amount': old_acc_due_amount,
                'account_payment_paid_principal': account_payment.paid_principal,
                'account_payment_paid_interest': account_payment.paid_interest,
                'account_payment_paid_late_fee': account_payment.paid_late_fee,
                'account_payment_paid_amount': account_payment.paid_amount,
                'account_payment_due_amount': account_payment.due_amount,
                'paid_principal': paid_principal,
                'paid_interest': paid_interest,
                'paid_late_fee': paid_late_fee,
                'total_paid_amount': total_paid_amount,
                'credit_usage_mutation': credit_usage_mutation,
                'lender_product_id': lender_product_id,
            }
        )

        note = ',\nnote: '
        note_payment_method = ',\n'
        if payback_transaction.payment_method:
            note_payment_method += (
                'payment_method: %s,\n\
                                    payment_receipt: %s'
                % (
                    payback_transaction.payment_method.payment_method_name,
                    payback_transaction.transaction_id,
                )
            )
        template_note = (
            '[Add Event %s]\n\
                                amount: %s,\n\
                                date: %s%s%s.'
            % (
                'payment',
                display_rupiah(paid_principal + paid_interest + paid_late_fee),
                payback_transaction.transaction_date.strftime("%d-%m-%Y"),
                note_payment_method,
                note,
            )
        )

        if account_payment.due_amount == 0:
            update_ptp_for_paid_off_account_payment(account_payment)
            # fmt: off
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(paid_off_id)
            )
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_dialer.delay(paid_off_id)
            )
            # fmt: on
            # this will update ptp_status
            today = timezone.localtime(timezone.now()).date()
            ptp = PTP.objects.filter(ptp_date__gte=today, account_payment=account_payment).last()
            if ptp:
                ptp.update_safely(ptp_status='Paid')
            # handle cootek
            account_payment_form_cootek = CootekRobocall.objects.filter(
                account_payment=account_payment
            ).last()
            if account_payment_form_cootek:
                cancel_phone_call_for_payment_paid_off.delay(account_payment_form_cootek.id)
            else:
                # this will handle partial account payment updates
                ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

        AccountPaymentNote.objects.create(note_text=template_note, account_payment=account_payment)

        if is_refund:
            change_limit_amount = paid_principal + interest_for_credit_limit
        else:
            if lender_product_id == DanaProductType.CASH_LOAN:
                change_limit_amount = paid_principal
            else:
                change_limit_amount = paid_principal + paid_interest

        if is_recalculated:
            update_account_limit(change_limit_amount, loan.account_id, loan.id)

        if hasattr(payback_transaction, 'accounttransaction'):
            account_transaction = payback_transaction.accounttransaction
            account_transaction.transaction_amount += total_paid_amount
            account_transaction.towards_principal += paid_principal
            account_transaction.towards_interest += paid_interest
            account_transaction.towards_latefee += paid_late_fee
            account_transaction.save(
                update_fields=[
                    'transaction_amount',
                    'towards_principal',
                    'towards_interest',
                    'towards_latefee',
                ]
            )
        else:
            account_transaction = AccountTransaction.objects.create(
                account=loan.account,
                payback_transaction=payback_transaction,
                transaction_date=payback_transaction.transaction_date,
                transaction_amount=payback_transaction.amount,
                transaction_type='payment',
                towards_principal=paid_principal,
                towards_interest=paid_interest,
                towards_latefee=paid_late_fee,
            )

        if payment_event:
            payment_event.update_safely(account_transaction=account_transaction)

        payback_transaction.update_safely(is_processed=True)
        execute_after_transaction_safely(lambda: account_reactivation.delay(loan.account_id))

        # delete dialer vendor from DanaCustomerData
        account = account_payment.account
        if account:
            if not account.get_unpaid_account_payment_ids():
                account_id = account.id
                dana_customer_data = DanaCustomerData.objects.filter(account_id=account_id).last()
                if dana_customer_data:
                    dana_customer_data.dialer_vendor = None
                    dana_customer_data.first_date_91_plus_assignment = None
                    dana_customer_data.save()

        # store waived amount
        with transaction.atomic(using='partnership_db'):
            dana_payment_bill.waived_principal_amount = (
                dana_payment_bill.waived_principal_amount or 0
            ) + (waived_principal_amount or 0)
            dana_payment_bill.waived_interest_fee_amount = (
                dana_payment_bill.waived_interest_fee_amount or 0
            ) + (waived_interest_fee_amount or 0)
            dana_payment_bill.waived_late_fee_amount = (
                dana_payment_bill.waived_late_fee_amount or 0
            ) + (waived_late_fee_amount or 0)
            dana_payment_bill.total_waived_amount = (dana_payment_bill.total_waived_amount or 0) + (
                total_waived_amount or 0
            )
            dana_payment_bill.save()

    except Exception as e:
        message = "Failed create manual repayment for billId {} and partnerReferenceNo {}".format(
            data.get('billId'),
            data.get('partnerReferenceNo'),
        )
        logger.exception(
            {
                "action": "failed_create_manual_repayment",
                "message": message,
                "error": str(e),
            }
        )
        raise Exception(e)


@transaction.atomic
def create_manual_repayment_settlement_v2(
    data: Dict,
    is_pending_process: bool = False,
    is_refund: bool = False,
    is_recalculated: bool = True,
) -> None:
    """
    is_pending_process: This flag for exclude re-create dana_repayment_reference
    Since for pending process dana_repayment_reference created in API but status is pending

    Refund Case:
    - is_void_late_fee: this for refund case, we need to waived late fee as 0
    - in refund case late_fee_amount will be set to 0.0 and status should be send as PAID
    - So there will be calculated late fee as 0.0 as well
    - PaymentEvent late_fee update to 0.0 as well
    - if is_pending_process & is_void_late_fee true this should be refund process
    - because no need to create dana_repayment_reference and waived the late fee
    """

    try:
        from juloserver.dana.services import dana_update_loan_status_and_loan_history
        from juloserver.dana.repayment.tasks import account_reactivation
        from juloserver.followthemoney.services import create_manual_transaction_mapping

        lender_product_id = data.get('lenderProductId', '')
        repayment_id = data.get('repaymentId', '')
        credit_usage_mutation = data.get('creditUsageMutation')
        if credit_usage_mutation:
            credit_usage_mutation = int(credit_usage_mutation)
        float_total_amount = float(data['totalAmount'])
        float_principal_amount = float(data['principalAmount'])
        float_interest_fee_amount = float(data['interestFeeAmount'])
        float_late_fee_amount = float(data['lateFeeAmount'])

        total_amount = int(float_total_amount)
        principal_amount = int(float_principal_amount)
        interest_fee_amount = int(float_interest_fee_amount)
        late_fee_amount = int(float_late_fee_amount)

        bill_status = data['billStatus']
        reference_no = str(uuid.uuid4())
        repaid_time = data['transTime']
        transaction_date = parse_datetime(repaid_time)
        data['transactionDate'] = transaction_date

        dana_payment_bill = data['dana_payment_bill']
        payment = data['payment']
        account_payment = payment.account_payment
        loan = payment.loan
        account = loan.account

        if is_refund:
            if payment.late_fee_amount != 0:
                acc_payment_late_fee_amount = (
                    account_payment.late_fee_amount - payment.late_fee_amount
                )
                acc_payment_paid_amount = account_payment.paid_amount - payment.paid_late_fee
                acc_payment_paid_late_fee = account_payment.paid_late_fee - payment.paid_late_fee
                account_payment.update_safely(
                    late_fee_amount=acc_payment_late_fee_amount,
                    paid_amount=acc_payment_paid_amount,
                    paid_late_fee=acc_payment_paid_late_fee,
                    refresh=False,
                )

                old_paid_payment_late_fee = payment.paid_late_fee
                payment_paid_amount = payment.paid_amount - payment.paid_late_fee
                payment.update_safely(
                    paid_amount=payment_paid_amount,
                    late_fee_applied=0,
                    late_fee_amount=0,
                    paid_late_fee=0,
                    refresh=False,
                )

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

                if old_paid_payment_late_fee != 0:
                    PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=old_paid_payment_late_fee,
                        event_due_amount=0,
                        event_date=transaction_date,
                        event_type='dana_late_fee_void',
                        payment_receipt=data['partnerReferenceNo'],
                        can_reverse=False,
                    )
                    AccountTransaction.objects.create(
                        account=loan.account,
                        transaction_date=transaction_date,
                        transaction_amount=old_paid_payment_late_fee,
                        transaction_type='dana_late_fee_void',
                        towards_principal=0,
                        towards_interest=0,
                        towards_latefee=old_paid_payment_late_fee,
                    )

                late_fee_amount = 0

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

            # void interest
            acc_payment_interest_amount = (
                account_payment.interest_amount - payment.installment_interest
            )
            acc_payment_paid_amount = account_payment.paid_amount - payment.paid_interest
            acc_payment_paid_interest = account_payment.paid_interest - payment.paid_interest
            account_payment.update_safely(
                interest_amount=acc_payment_interest_amount,
                paid_amount=acc_payment_paid_amount,
                paid_interest=acc_payment_paid_interest,
                refresh=False,
            )

            payment_paid_amount = payment.paid_amount - payment.paid_interest
            payment.update_safely(
                paid_amount=payment_paid_amount,
                installment_interest=0,
                paid_interest=0,
                refresh=False,
            )

            payment_events = payment.paymentevent_set.filter(event_type='payment').order_by('id')
            if payment_events:
                recalculate_payment_event(payment_events, payment, data)

            interest_for_credit_limit = interest_fee_amount
            interest_fee_amount = 0
            total_amount = principal_amount

        payback_transaction_dicts = data.get('payback_transaction_dicts')
        payback_transaction = payback_transaction_dicts.get(data['partnerReferenceNo'])
        if not payback_transaction:
            payback_transaction = PaybackTransaction.objects.create(
                transaction_id=data['partnerReferenceNo'],
                is_processed=False,
                virtual_account=None,
                payment_method=None,
                payback_service='dana',
                amount=total_amount,
                transaction_date=transaction_date,
            )
            payback_transaction_dicts[data['partnerReferenceNo']] = payback_transaction
        elif payback_transaction:
            payback_transaction.amount += total_amount
            payback_transaction.save(update_fields=['amount'])

        # Handle Update Payment
        paid_principal = principal_amount
        paid_interest = interest_fee_amount
        paid_late_fee = late_fee_amount
        total_paid_amount = total_amount

        old_payment_detail = {
            "paid_late_fee": payment.paid_late_fee,
            "paid_principal": payment.paid_principal,
            "paid_interest": payment.paid_interest,
            "paid_amount": payment.paid_amount,
        }

        payment.paid_principal += paid_principal
        payment.paid_interest += paid_interest
        payment.paid_late_fee += paid_late_fee
        payment.paid_amount += total_paid_amount

        if bill_status == BILL_STATUS_PAID_OFF:
            """
            This code it's mean if bill status is "PAID",
            we can assume payment should be paid off
            That's why we need to set the due amount as 0
            and check if payment.late_fee_amount not equal with paid_late_fee
            we need replace that because source of truth is Dana (paid_late_fee)
            """
            payment.due_amount = 0

            if payment.late_fee_amount != payment.paid_late_fee:
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

        elif bill_status == BILL_STATUS_PARTIAL:
            """
            This else for "INIT" case,
            Do calculate if this bill_id have payment before as PAID
            No need to calculate again the due amount since due_amount is 0
            handle it in "PAID" case, if not paid before do a normal reduce the due amount
            And if the payment paid before this need to make a same
            paid_late_fee == late_fee_amount
            """
            if (
                payment.status in PaymentStatusCodes.paid_status_codes()
                and payment.paid_late_fee != payment.late_fee_amount
            ):
                payment.late_fee_amount = payment.paid_late_fee

                # Handling payment_event
                late_fee_events = payment.paymentevent_set.filter(event_type='late_fee').order_by(
                    'id'
                )

                if late_fee_events:
                    recalculate_payment_event(late_fee_events, payment, data)

            if payment.status not in PaymentStatusCodes.paid_status_codes():
                payment.due_amount -= total_paid_amount

                """
                This case when INIT send but late fee in DANA greater than late fee in JULO
                Need to set as 0
                """
                if payment.due_amount < 0:
                    payment.due_amount = 0

        total_payment_paid_amount = payment.paid_amount - old_payment_detail["paid_amount"]
        payment_event = None
        if total_payment_paid_amount > 0:
            paid_date = payback_transaction.transaction_date.astimezone().date()
            payment_receipt = payback_transaction.transaction_id
            payment_method = payback_transaction.payment_method

            """
            Handle amount event_due_amount scenario
            FULL PAID
            1. 0 + 27_025 -> PAID AMOUNT
            2. 27_025 - 27_025 = 0 -> DUE AMOUNT
            3. 0 + 27_025

            PARTIAL PAID
            1. 0 + 10_000 -> PAID AMOUNT
            2. 27_025 - 10_000 = 17_025 -> DUE AMOUNT
            3. 17_025 + 10_000 = 27_025 -> event_due_amount

            PAID
            1. 10_000 + 17_025 -> PAID AMOUNT
            2. 17_025 - 17_025 = 0 -> DUE AMOUNT
            3. 0 + 17_025 = 17_025 -> event_due_amount
            """

            total_payment_amount = (
                payment.installment_principal
                + payment.installment_interest
                + payment.late_fee_amount
            )
            re_calculate_due_amount = total_payment_amount - payment.paid_amount
            event_due_amount = re_calculate_due_amount + total_payment_paid_amount

            payment_event = PaymentEvent.objects.create(
                payment=payment,
                event_payment=total_payment_paid_amount,
                event_due_amount=event_due_amount,
                event_date=paid_date,
                event_type='payment',
                payment_receipt=payment_receipt,
                payment_method=payment_method,
                can_reverse=False,  # reverse (void) must be via account payment level
            )
            paid_principal = payment.paid_principal - old_payment_detail["paid_principal"]
            paid_interest = payment.paid_interest - old_payment_detail["paid_interest"]
            paid_late_fee = payment.paid_late_fee - old_payment_detail["paid_late_fee"]

            create_manual_transaction_mapping(
                payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee
            )

            payment.udate = timezone.localtime(timezone.now())
            payment.paid_date = paid_date
            payment_update_fields = [
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_amount',
                'due_amount',
                'paid_date',
                'udate',
                'late_fee_amount',
            ]

            # loan = payment.loan
            payment_history = {
                'payment_old_status_code': payment.status,
                'loan_old_status_code': loan.status,
            }
            if bill_status == BILL_STATUS_PAID_OFF:
                update_payment_paid_off_status(payment)
                payment_update_fields.append('payment_status')

            payment.save(update_fields=payment_update_fields)

            # take care loan level
            unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
            if len(unpaid_payments) == 0:  # this mean loan is paid_off
                # Handling checking if is already paid off, Because there is case payment failure
                if loan.status != LoanStatusCodes.PAID_OFF:
                    dana_update_loan_status_and_loan_history(
                        loan_id=loan,
                        new_status_code=LoanStatusCodes.PAID_OFF,
                        change_by_id=None,
                        change_reason="Loan paid off",
                    )

                # Handling if there is partial paid but loan is already paid
                # Need to create history also
                if bill_status == BILL_STATUS_PARTIAL and loan.status == LoanStatusCodes.PAID_OFF:
                    payment.create_payment_history(payment_history)

            elif bill_status == BILL_STATUS_PAID_OFF:
                current_loan_status = loan.status
                loan.update_status(record_history=False)
                if current_loan_status != loan.status:
                    dana_update_loan_status_and_loan_history(
                        loan_id=loan,
                        new_status_code=loan.status,
                        change_by_id=None,
                        change_reason="update loan status after payment paid off",
                    )

            if bill_status == BILL_STATUS_PAID_OFF:
                payment.create_payment_history(payment_history)

            event_type = 'payment'
            note = 'Dana Settlement Payment'
            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payment_method:
                note_payment_method += (
                    'payment_method: %s,\n\
                            payment_receipt: %s'
                    % (payment_method.payment_method_name, payment_event.payment_receipt)
                )
            template_note = (
                '[Add Event %s]\n\
                        amount: %s,\n\
                        date: %s%s%s.'
                % (
                    event_type,
                    display_rupiah(payment_event.event_payment),
                    payment_event.event_date.strftime("%d-%m-%Y"),
                    note_payment_method,
                    note,
                )
            )

            PaymentNote.objects.create(note_text=template_note, payment=payment)

        waived_principal_amount = None
        waived_interest_fee_amount = None
        waived_late_fee_amount = None
        total_waived_amount = None

        waived_principal = data.get('waivedPrincipalAmount')
        if waived_principal:
            waived_principal_amount = int(float(waived_principal))

        waived_interest_fee = data.get('waivedInterestFeeAmount')
        if waived_interest_fee:
            waived_interest_fee_amount = int(float(waived_interest_fee))

        waived_late_fee = data.get('waivedLateFeeAmount')
        if waived_late_fee:
            waived_late_fee_amount = int(float(waived_late_fee))

        total_waived = data.get('totalWaivedAmount')
        if total_waived:
            total_waived_amount = int(float(total_waived))

        if not is_pending_process:
            # Creating Dana Repayment Reference
            dana_customer_data = DanaCustomerData.objects.filter(
                customer__account__loan__payment=payment
            ).last()

            dana_repayment_reference = DanaRepaymentReference.objects.create(
                payment=payment,
                partner_reference_no=data['partnerReferenceNo'],
                customer_id=dana_customer_data.dana_customer_identifier,
                reference_no=reference_no,
                bill_id=data['billId'],
                bill_status=data['billStatus'],
                principal_amount=paid_principal,
                interest_fee_amount=paid_interest,
                late_fee_amount=paid_late_fee,
                total_repayment_amount=total_paid_amount,
                repaid_time=repaid_time,
                credit_usage_mutation=credit_usage_mutation,
                repayment_id=repayment_id,
                lender_product_id=lender_product_id,
                waived_principal_amount=waived_principal_amount,
                waived_interest_fee_amount=waived_interest_fee_amount,
                waived_late_fee_amount=waived_late_fee_amount,
                total_waived_amount=total_waived_amount,
            )

            DanaRepaymentReferenceStatus.objects.create(
                dana_repayment_reference_id=dana_repayment_reference.id,
                status=RepaymentReferenceStatus.SUCCESS,
            )

        # This need to refresh for preventing mismatch calculation in account payment
        payment.refresh_from_db()

        # Handle Update Account Payment
        # Get SUM amount exclude the payment that in progress
        existing_account_payment = account_payment.payment_set.aggregate(
            total_due_amount=Sum('due_amount'), total_late_fee_amount=Sum('late_fee_amount')
        )
        accumulated_payment_due_amount = existing_account_payment['total_due_amount'] or 0
        accumulated_total_late_fee_amount = existing_account_payment['total_late_fee_amount'] or 0

        old_acc_paid_principal = account_payment.paid_principal
        old_acc_paid_interest = account_payment.paid_interest
        old_acc_paid_late_fee = account_payment.paid_late_fee
        old_acc_paid_amount = account_payment.paid_amount
        old_acc_due_amount = account_payment.due_amount

        account_payment.paid_date = payback_transaction.transaction_date.astimezone().date()
        account_payment.paid_principal += paid_principal
        account_payment.paid_interest += paid_interest
        account_payment.paid_late_fee += paid_late_fee
        account_payment.paid_amount += total_paid_amount

        """
            Need recalculate late_fee_amount and due_amount because we need to consume
            related all payment especially due_amount and late_fee_amount
            because there is always mismatch related late_fee_amount makes due_amount minus
            check if total account_payment.late_fee_amount not equal
            With SUM payment.late_fee_amount
            we need replace that because source of truth is Dana (paid_late_fee)
            because in payment.paid_late_fee == payment.late_fee_amount
        """
        if accumulated_total_late_fee_amount != account_payment.late_fee_amount:
            account_payment.late_fee_amount = accumulated_total_late_fee_amount

        account_payment.due_amount = accumulated_payment_due_amount

        if account_payment.due_amount == 0:
            history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
            update_account_payment_paid_off_status(account_payment)
            account_payment.create_account_payment_status_history(history_data)

        account_payment.udate = timezone.localtime(timezone.now())
        account_payment.save(
            update_fields=[
                'due_amount',
                'paid_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_date',
                'status',
                'udate',
                'late_fee_amount',
            ]
        )

        logger.info(
            {
                'action': 'dana_repayment_update_account_payment',
                'loan_id': loan.id,
                'account_id': account.id,
                'old_account_payment_paid_principal': old_acc_paid_principal,
                'old_account_payment_paid_interest': old_acc_paid_interest,
                'old_account_payment_paid_late_fee': old_acc_paid_late_fee,
                'old_account_payment_paid_amount': old_acc_paid_amount,
                'old_account_payment_due_amount': old_acc_due_amount,
                'account_payment_paid_principal': account_payment.paid_principal,
                'account_payment_paid_interest': account_payment.paid_interest,
                'account_payment_paid_late_fee': account_payment.paid_late_fee,
                'account_payment_paid_amount': account_payment.paid_amount,
                'account_payment_due_amount': account_payment.due_amount,
                'paid_principal': paid_principal,
                'paid_interest': paid_interest,
                'paid_late_fee': paid_late_fee,
                'total_paid_amount': total_paid_amount,
                'credit_usage_mutation': credit_usage_mutation,
                'lender_product_id': lender_product_id,
            }
        )

        note = ',\nnote: '
        note_payment_method = ',\n'
        if payback_transaction.payment_method:
            note_payment_method += (
                'payment_method: %s,\n\
                                    payment_receipt: %s'
                % (
                    payback_transaction.payment_method.payment_method_name,
                    payback_transaction.transaction_id,
                )
            )
        template_note = (
            '[Add Event %s]\n\
                                amount: %s,\n\
                                date: %s%s%s.'
            % (
                'payment',
                display_rupiah(paid_principal + paid_interest + paid_late_fee),
                payback_transaction.transaction_date.strftime("%d-%m-%Y"),
                note_payment_method,
                note,
            )
        )

        if account_payment.due_amount == 0:
            update_ptp_for_paid_off_account_payment(account_payment)
            # fmt: off
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(paid_off_id)
            )
            execute_after_transaction_safely(
                lambda paid_off_id=account_payment.id:
                delete_paid_payment_from_dialer.delay(paid_off_id)
            )
            # fmt: on
            # this will update ptp_status
            today = timezone.localtime(timezone.now()).date()
            ptp = PTP.objects.filter(ptp_date__gte=today, account_payment=account_payment).last()
            if ptp:
                ptp.update_safely(ptp_status='Paid', refresh=False)
            # handle cootek
            account_payment_form_cootek = CootekRobocall.objects.filter(
                account_payment=account_payment
            ).last()
            if account_payment_form_cootek:
                cancel_phone_call_for_payment_paid_off.delay(account_payment_form_cootek.id)
            else:
                # this will handle partial account payment updates
                ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

        AccountPaymentNote.objects.create(note_text=template_note, account_payment=account_payment)

        if is_refund:
            if lender_product_id == DanaProductType.CASH_LOAN:
                change_limit_amount = paid_principal
            else:
                change_limit_amount = paid_principal + interest_for_credit_limit
        else:
            if lender_product_id == DanaProductType.CASH_LOAN:
                change_limit_amount = paid_principal
            else:
                change_limit_amount = paid_principal + paid_interest

        if is_recalculated:
            update_account_limit(change_limit_amount, loan.account_id, loan.id)

        if hasattr(payback_transaction, 'accounttransaction'):
            account_transaction = payback_transaction.accounttransaction
            account_transaction.transaction_amount += total_paid_amount
            account_transaction.towards_principal += paid_principal
            account_transaction.towards_interest += paid_interest
            account_transaction.towards_latefee += paid_late_fee
            account_transaction.save(
                update_fields=[
                    'transaction_amount',
                    'towards_principal',
                    'towards_interest',
                    'towards_latefee',
                ]
            )
        else:
            account_transaction = AccountTransaction.objects.create(
                account=account,
                payback_transaction=payback_transaction,
                transaction_date=payback_transaction.transaction_date,
                transaction_amount=payback_transaction.amount,
                transaction_type='payment',
                towards_principal=paid_principal,
                towards_interest=paid_interest,
                towards_latefee=paid_late_fee,
            )

        if payment_event:
            payment_event.update_safely(account_transaction=account_transaction, refresh=False)

        payback_transaction.update_safely(is_processed=True, refresh=False)
        execute_after_transaction_safely(lambda: account_reactivation.delay(loan.account_id))

        # delete dialer vendor from DanaCustomerData
        if account:
            if not account.get_unpaid_account_payment_ids():
                dana_customer_data = getattr(account, 'dana_customer_data')
                if dana_customer_data:
                    dana_customer_data.dialer_vendor = None
                    dana_customer_data.first_date_91_plus_assignment = None
                    dana_customer_data.save()

        # store waived amount
        dana_payment_bill.waived_principal_amount = (
            dana_payment_bill.waived_principal_amount or 0
        ) + (waived_principal_amount or 0)
        dana_payment_bill.waived_interest_fee_amount = (
            dana_payment_bill.waived_interest_fee_amount or 0
        ) + (waived_interest_fee_amount or 0)
        dana_payment_bill.waived_late_fee_amount = (
            dana_payment_bill.waived_late_fee_amount or 0
        ) + (waived_late_fee_amount or 0)
        dana_payment_bill.total_waived_amount = (dana_payment_bill.total_waived_amount or 0) + (
            total_waived_amount or 0
        )
        dana_payment_bill.save()

    except Exception as e:
        message = "Failed create manual repayment for billId {} and partnerReferenceNo {}".format(
            data.get('billId'),
            data.get('partnerReferenceNo'),
        )
        logger.exception(
            {
                "action": "failed_create_manual_repayment",
                "message": message,
                "error": str(e),
            }
        )
        raise Exception(e)


# This function no one uses
@transaction.atomic
def dana_reverse_repayment_reference(
    dana_repayment_reference: DanaRepaymentReference,
    new_repayment_reference: Dict,
    user_id: int = None,
):
    from juloserver.account.services.account_related import (
        update_account_status_based_on_account_payment,
    )
    from juloserver.account_payment.services.reversal import (
        reverse_is_proven,
        void_commision_and_update_ptp_status,
    )
    from juloserver.followthemoney.services import create_manual_transaction_mapping
    from juloserver.julo.services2.payment_event import PaymentEventServices

    dana_customer_id = dana_repayment_reference.customer_id
    dana_customer_data = DanaCustomerData.objects.get(dana_customer_identifier=dana_customer_id)

    reverse_date = timezone.localtime(timezone.now())
    account = dana_customer_data.account
    old_repayment_reference_value = {
        'dana_repayment_reference': dana_repayment_reference.partner_reference_no,
        'bill_id': dana_repayment_reference.bill_id,
        'customer_id': dana_repayment_reference.customer_id,
        'principal_amount': dana_repayment_reference.principal_amount,
        'interest_fee_amount': dana_repayment_reference.interest_fee_amount,
        'late_fee_amount': dana_repayment_reference.late_fee_amount,
        'total_repayment_amount': dana_repayment_reference.total_repayment_amount,
        'payment': dana_repayment_reference.payment,
    }

    dana_payment_bill = DanaPaymentBill.objects.filter(
        bill_id=dana_repayment_reference.bill_id
    ).last()

    payback_transaction = PaybackTransaction.objects.select_for_update().get(
        transaction_id=dana_repayment_reference.partner_reference_no
    )

    account_transaction = payback_transaction.accounttransaction

    payment_id = dana_payment_bill.payment_id
    payment = Payment.objects.get(id=payment_id)
    account_payment = AccountPayment.objects.select_for_update().get(id=payment.account_payment_id)

    # Consume Reversal For Late Fee
    total_reversed_late_fee = 0
    reversed_late_fee = old_repayment_reference_value['late_fee_amount']
    payment.paid_amount -= reversed_late_fee
    payment.due_amount += reversed_late_fee
    payment.paid_late_fee -= reversed_late_fee

    account_payment.paid_amount -= reversed_late_fee
    account_payment.due_amount += reversed_late_fee
    account_payment.paid_late_fee -= reversed_late_fee

    total_reversed_late_fee += reversed_late_fee

    # Consume Reversal For Interest
    total_reversed_interest = 0
    reversed_interest = old_repayment_reference_value['interest_fee_amount']
    payment.paid_amount -= reversed_interest
    payment.due_amount += reversed_interest
    payment.paid_interest -= reversed_interest

    account_payment.paid_amount -= reversed_interest
    account_payment.due_amount += reversed_interest
    account_payment.paid_interest -= reversed_interest

    total_reversed_interest += reversed_interest

    # Consume Reversal For Interest
    total_reversed_principal = 0
    reversed_principal = old_repayment_reference_value['principal_amount']

    payment.paid_amount -= reversed_principal
    payment.due_amount += reversed_principal
    payment.paid_principal -= reversed_principal

    account_payment.paid_amount -= reversed_principal
    account_payment.due_amount += reversed_principal
    account_payment.paid_principal -= reversed_principal

    total_reversed_principal += reversed_principal

    event_type = 'payment_void'
    total_reversed_amount = old_repayment_reference_value['total_repayment_amount']
    payment_event_void = None
    payment_event_void = PaymentEvent.objects.create(
        added_by=user_id,
        payment=payment,
        event_payment=-total_reversed_amount,
        event_due_amount=payment.due_amount - total_reversed_amount,
        event_date=reverse_date,
        event_type=event_type,
        payment_receipt=payback_transaction.transaction_id,
        payment_method=payback_transaction.payment_method,
        can_reverse=False,  # reverse (void) must be via account payment level
    )

    create_manual_transaction_mapping(
        payment.loan,
        payment_event_void,
        old_repayment_reference_value['principal_amount'],
        old_repayment_reference_value['interest_fee_amount'],
        old_repayment_reference_value['late_fee_amount'],
    )
    payment.paid_date = PaymentEventServices().get_paid_date_from_event_before(payment)
    payment_update_fields = [
        'paid_principal',
        'paid_interest',
        'paid_late_fee',
        'paid_amount',
        'due_amount',
        'paid_date',
        'payment_status',
        'udate',
    ]

    loan = payment.loan
    payment_history = {
        'payment_old_status_code': payment.status,
        'loan_old_status_code': payment.loan.status,
    }

    # monkey patch for paid_off status always get 312,
    # set to not due before calling the function
    payment.payment_status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
    payment.update_status_based_on_due_date()

    payment.save(update_fields=payment_update_fields)

    # Update loan status
    changed_by_id = payment_event_void.added_by.id if payment_event_void.added_by else None
    loan.update_status(record_history=False)
    if payment_history['loan_old_status_code'] != loan.status:
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=loan.status,
            change_by_id=changed_by_id,
            change_reason=event_type,
        )

    # create payment history regarding to loan status as well
    if payment_history['payment_old_status_code'] != payment.status:
        payment.create_payment_history(payment_history)

    note = "Reversed dana payment"
    note = ',\nnote: %s' % note
    note_payment_method = ',\n'
    if payment_event_void.payment_method:
        note_payment_method += (
            'payment_method: %s,\n\
                    payment_receipt: %s'
            % (
                payment_event_void.payment_method.payment_method_name,
                payment_event_void.payment_receipt,
            )
        )
    template_note = (
        '[Add Event %s]\n\
                amount: %s,\n\
                date: %s%s%s.'
        % (
            event_type,
            display_rupiah(payment_event_void.event_payment),
            payment_event_void.event_date.strftime("%d-%m-%Y"),
            note_payment_method,
            note,
        )
    )

    PaymentNote.objects.create(note_text=template_note, payment=payment)

    # Account Payment
    transaction_type = 'payment_void'

    acc_payment_history_data = {
        'status_old': account_payment.status,
        'change_reason': transaction_type,
    }

    account_payment.update_status_based_on_payment()
    account_payment.update_paid_date_based_on_payment()

    if acc_payment_history_data['status_old'] != account_payment.status:
        account_payment.create_account_payment_status_history(acc_payment_history_data)

    account_payment_updated_fields = [
        'due_amount',
        'paid_amount',
        'paid_principal',
        'paid_interest',
        'paid_late_fee',
        'paid_date',
        'status',
        'udate',
    ]

    account_payment.save(update_fields=account_payment_updated_fields)

    # need to call this task for re-updating account status
    update_account_status_based_on_account_payment(
        account_payment, reason_override=transaction_type
    )

    # TODO-DANA: Rverse void PTP and account is proven
    #   # reverse back account property
    #   reverse_is_proven(account)

    # if transaction_type == 'payment_void':
    #     void_commision_and_update_ptp_status(reversal_account_trx)

    local_trx_time = timezone.localtime(timezone.now())
    reversal_account_trx = AccountTransaction.objects.create(
        account=account_transaction.account,
        transaction_date=local_trx_time,
        transaction_amount=-account_transaction.transaction_amount,
        transaction_type=transaction_type,
        towards_principal=-account_transaction.towards_principal,
        towards_interest=-account_transaction.towards_interest,
        towards_latefee=-account_transaction.towards_latefee,
        can_reverse=False,
    )

    if payment_event_void:
        payment_event_void.update_safely(account_transaction=reversal_account_trx)

    account_transaction.update_safely(can_reverse=False, reversal_transaction=reversal_account_trx)

    reverse_is_proven(account)

    if transaction_type == 'payment_void':
        void_commision_and_update_ptp_status(reversal_account_trx)

    # Reverse account transaction
    account_transaction.transaction_amount -= old_repayment_reference_value[
        'total_repayment_amount'
    ]
    account_transaction.towards_principal -= old_repayment_reference_value['principal_amount']
    account_transaction.towards_interest -= old_repayment_reference_value['interest_fee_amount']
    account_transaction.towards_latefee -= old_repayment_reference_value['late_fee_amount']
    account_transaction_fields_update = [
        'transaction_amount',
        'towards_principal',
        'towards_interest',
        'towards_latefee',
    ]
    account_transaction.save(update_fields=account_transaction_fields_update)

    payback_transaction.amount -= old_repayment_reference_value['total_repayment_amount']
    payback_transaction.save(update_fields=['amount'])

    # Update Account Limit
    change_limit_amount = (
        old_repayment_reference_value['principal_amount']
        + old_repayment_reference_value['interest_fee_amount']
    )
    account_limit = AccountLimit.objects.filter(account=account).last()
    new_available_limit = account_limit.available_limit - change_limit_amount
    new_used_limit = account_limit.used_limit + change_limit_amount
    account_limit.update_safely(available_limit=new_available_limit, used_limit=new_used_limit)

    # Creating current data to history
    DanaRepaymentReferenceHistory.objects.create(
        repayment_reference=dana_repayment_reference,
        repaid_time=payback_transaction.transaction_date,
        bill_id=dana_repayment_reference.bill_id,
        customer_id=dana_repayment_reference.customer_id,
        bill_status=dana_repayment_reference.bill_status,
        principal_amount=dana_repayment_reference.principal_amount,
        interest_fee_amount=dana_repayment_reference.interest_fee_amount,
        late_fee_amount=dana_repayment_reference.late_fee_amount,
        total_repayment_amount=dana_repayment_reference.total_repayment_amount,
    )

    # Refresh all data
    payment.refresh_from_db()
    account_payment.refresh_from_db()
    account_transaction.refresh_from_db()
    payback_transaction.refresh_from_db()

    # Update to new data
    update_reverse_repayment_to_new_payment(
        dana_repayment_reference, new_repayment_reference, user_id
    )


@transaction.atomic
def update_reverse_repayment_to_new_payment(
    dana_repayment_reference: DanaRepaymentReference,
    new_repayment_reference: Dict,
    user_id: int = None,
) -> None:
    from juloserver.followthemoney.services import create_manual_transaction_mapping
    from juloserver.dana.repayment.tasks import account_reactivation

    event_type = "payment"
    dana_payment_bill = DanaPaymentBill.objects.filter(
        bill_id=dana_repayment_reference.bill_id
    ).last()

    payback_transaction = PaybackTransaction.objects.select_for_update().get(
        transaction_id=dana_repayment_reference.partner_reference_no
    )
    account_transaction = payback_transaction.accounttransaction
    payment_id = dana_payment_bill.payment_id
    payment = Payment.objects.get(id=payment_id)

    update_date = timezone.localtime(timezone.now())

    paid_late_fee = int(new_repayment_reference['lateFeeAmount'])
    paid_principal = int(new_repayment_reference['principalAmount'])
    paid_interest = int(new_repayment_reference['interestFeeAmount'])
    total_paid_amount = int(new_repayment_reference['totalAmount'])

    payment.paid_principal += paid_principal
    payment.paid_interest += paid_interest
    payment.paid_late_fee += paid_late_fee
    payment.paid_amount += total_paid_amount
    payment.due_amount -= total_paid_amount

    payment_event_paid = PaymentEvent.objects.create(
        added_by=user_id,
        payment=payment,
        event_payment=total_paid_amount,
        event_due_amount=payment.due_amount + total_paid_amount,
        event_date=update_date,
        event_type=event_type,
        payment_receipt=payback_transaction.transaction_id,
        payment_method=payback_transaction.payment_method,
        can_reverse=False,  # reverse (void) must be via account payment level
        account_transaction=account_transaction,
    )

    create_manual_transaction_mapping(
        payment.loan,
        payment_event_paid,
        paid_principal,
        paid_interest,
        paid_late_fee,
    )

    payment.paid_date = payback_transaction.transaction_date.date()
    payment_update_fields = [
        'paid_principal',
        'paid_interest',
        'paid_late_fee',
        'paid_amount',
        'due_amount',
        'paid_date',
        'udate',
    ]

    loan = payment.loan
    if new_repayment_reference['billStatus'] == BILL_STATUS_PAID_OFF:
        payment_history = {
            'payment_old_status_code': payment.status,
            'loan_old_status_code': loan.status,
        }

        update_payment_paid_off_status(payment)
        payment_update_fields.append('payment_status')

    payment.save(update_fields=payment_update_fields)

    # take care loan level
    unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
    if len(unpaid_payments) == 0:  # this mean loan is paid_off
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.PAID_OFF,
            change_by_id=None,
            change_reason="Loan paid off",
        )
        loan.refresh_from_db()
    elif new_repayment_reference['billStatus'] == BILL_STATUS_PAID_OFF:
        current_loan_status = loan.status
        loan.update_status(record_history=False)
        if current_loan_status != loan.status:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=loan.status,
                change_by_id=None,
                change_reason="update loan status after payment paid off",
            )

    if new_repayment_reference['billStatus'] == BILL_STATUS_PAID_OFF:
        payment.create_payment_history(payment_history)

    note = "Updated dana payment"
    note = ',\nnote: %s' % note
    note_payment_method = ',\n'
    if payment_event_paid.payment_method:
        note_payment_method += (
            'payment_method: %s,\n\
                    payment_receipt: %s'
            % (
                payment_event_paid.payment_method.payment_method_name,
                payment_event_paid.payment_event.payment_receipt,
            )
        )
    template_note = (
        '[Add Event %s]\n\
                amount: %s,\n\
                date: %s%s%s.'
        % (
            event_type,
            display_rupiah(payment_event_paid.event_payment),
            payment_event_paid.event_date.strftime("%d-%m-%Y"),
            note_payment_method,
            note,
        )
    )

    PaymentNote.objects.create(note_text=template_note, payment=payment)

    # Account Payment
    account_payment = AccountPayment.objects.select_for_update().get(id=payment.account_payment_id)
    account_payment.paid_date = payback_transaction.transaction_date.date()
    account_payment.paid_principal += paid_principal
    account_payment.paid_interest += paid_interest
    account_payment.paid_late_fee += paid_late_fee
    account_payment.paid_amount += total_paid_amount
    account_payment.due_amount -= total_paid_amount

    if account_payment.due_amount == 0:
        history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
        update_account_payment_paid_off_status(account_payment)
        account_payment.create_account_payment_status_history(history_data)

    account_payment.save(
        update_fields=[
            'due_amount',
            'paid_amount',
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
            'paid_date',
            'status',
            'udate',
        ]
    )

    note = ',\nnote: '
    note_payment_method = ',\n'
    if payback_transaction.payment_method:
        note_payment_method += (
            'payment_method: %s,\n\
                                payment_receipt: %s'
            % (
                payback_transaction.payment_method.payment_method_name,
                payback_transaction.transaction_id,
            )
        )
    template_note = (
        '[Add Event %s]\n\
                            amount: %s,\n\
                            date: %s%s%s.'
        % (
            'payment',
            display_rupiah(paid_principal + paid_interest + paid_late_fee),
            payback_transaction.transaction_date.strftime("%d-%m-%Y"),
            note_payment_method,
            note,
        )
    )
    AccountPaymentNote.objects.create(note_text=template_note, account_payment=account_payment)

    if account_payment.due_amount == 0:
        update_ptp_for_paid_off_account_payment(account_payment)
        # fmt: off
        execute_after_transaction_safely(
            lambda paid_off_id=account_payment.id:
            delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(paid_off_id)
        )
        execute_after_transaction_safely(
            lambda paid_off_id=account_payment.id:
            delete_paid_payment_from_dialer.delay(paid_off_id)
        )
        # fmt: on
        # this will update ptp_status
        today = timezone.localtime(timezone.now()).date()
        ptp = PTP.objects.filter(ptp_date__gte=today, account_payment=account_payment).last()
        if ptp:
            ptp.update_safely(ptp_status='Paid')
        # handle cootek
        account_payment_form_cootek = CootekRobocall.objects.filter(
            account_payment=account_payment
        ).last()
        if account_payment_form_cootek:
            cancel_phone_call_for_payment_paid_off.delay(account_payment_form_cootek.id)
    else:
        # this will handle partial account payment updates
        ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

    change_limit_amount = paid_principal + paid_interest
    update_account_limit(change_limit_amount, loan.account_id, loan.id)

    # Update account transaction
    account_transaction.transaction_amount += total_paid_amount
    account_transaction.towards_principal += paid_principal
    account_transaction.towards_interest += paid_interest
    account_transaction.towards_latefee += paid_late_fee
    account_transaction_fields_update = [
        'transaction_amount',
        'towards_principal',
        'towards_interest',
        'towards_latefee',
    ]
    account_transaction.save(update_fields=account_transaction_fields_update)

    payback_transaction.amount += total_paid_amount
    payback_transaction.save(update_fields=['amount'])

    execute_after_transaction_safely(lambda: account_reactivation.delay(loan.account_id))

    # Update Dana repayment reference
    dana_repayment_reference.principal_amount = new_repayment_reference['principalAmount']
    dana_repayment_reference.interest_fee_amount = new_repayment_reference['interestFeeAmount']
    dana_repayment_reference.late_fee_amount = new_repayment_reference['lateFeeAmount']
    dana_repayment_reference.total_repayment_amount = new_repayment_reference['totalAmount']
    dana_repayment_reference.bill_status = new_repayment_reference['billStatus']
    dana_repayment_reference.save(
        update_fields=[
            'principal_amount',
            'interest_fee_amount',
            'late_fee_amount',
            'total_repayment_amount',
            'bill_status',
        ]
    )
    dana_repayment_reference.refresh_from_db()


def check_invalid_loan_status(bill_id: str, customer_id: str) -> Tuple:
    """
    This function will check if:
    1. Loan Status Canceled To not processed (216)
    2. Is Loan status is pending (211, 212) will mark as pending
    """

    LoanResult = namedtuple('LoanResult', ['is_valid', 'loan_status'])

    dana_payment_bill = DanaPaymentBill.objects.filter(
        bill_id=bill_id,
    ).last()

    loan_status = 0
    if dana_payment_bill:
        payment = (
            Payment.objects.select_related('loan__loan_status')
            .filter(
                id=dana_payment_bill.payment_id,
                loan__account__dana_customer_data__dana_customer_identifier=customer_id,
            )
            .last()
        )
        loan_status = payment.loan.loan_status.status_code

    not_processed_now = {
        LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.LENDER_APPROVAL,
    }

    if loan_status in not_processed_now:
        return LoanResult(False, loan_status)

    return LoanResult(True, loan_status)


def resume_dana_repayment(loan_id: int = None, list_dana_repayment_references: List = None) -> None:
    drr_ids = set()
    pending_dana_repayment_reference_ids = set()

    if list_dana_repayment_references:
        dana_repayment_references = list_dana_repayment_references
    elif loan_id:
        dana_repayment_references = DanaRepaymentReference.objects.filter(
            payment__loan__id=loan_id,
        ).order_by("id")
    else:
        raise Exception("List dana repayment and loan_id not found")

    if dana_repayment_references:
        for drr in dana_repayment_references:
            drr_ids.add(drr.id)

        pending_dana_repayment_reference_statuses = DanaRepaymentReferenceStatus.objects.filter(
            dana_repayment_reference_id__in=drr_ids,
            status=RepaymentReferenceStatus.PENDING,
        )

        drr_status_dicts = {}
        for pending_drr_status in pending_dana_repayment_reference_statuses:
            drr_status_dicts[pending_drr_status.dana_repayment_reference_id] = pending_drr_status
            pending_dana_repayment_reference_ids.add(pending_drr_status.dana_repayment_reference_id)

        update_reference_status = []

        partner_reference_nos = []
        bill_ids = []
        for dana_repayment_reference in dana_repayment_references:
            partner_reference_nos.append(dana_repayment_reference.partner_reference_no)
            bill_ids.append(dana_repayment_reference.bill_id)

        payback_transactions = PaybackTransaction.objects.filter(
            transaction_id__in=partner_reference_nos
        ).select_related("accounttransaction")
        payback_transaction_dicts = {}
        for payback_transaction in payback_transactions:
            payback_transaction_dicts[payback_transaction.transaction_id] = payback_transaction

        dana_payment_bills = DanaPaymentBill.objects.filter(bill_id__in=bill_ids)
        dana_payment_bill_dicts = {}
        payment_ids = []
        for dana_payment_bill in dana_payment_bills:
            dana_payment_bill_dicts[dana_payment_bill.bill_id] = dana_payment_bill
            payment_ids.append(dana_payment_bill.payment_id)

        payments = Payment.objects.filter(id__in=payment_ids).select_related(
            "loan",
            "loan__account",
            "loan__lender",
            "account_payment",
            "account_payment__account",
            "account_payment__account__customer",
        )
        payment_dicts = {}
        for payment in payments:
            payment_dicts[payment.id] = payment

        dana_repayment_fs = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.DANA_REPAYMENT_VERSION, is_active=True
        ).first()
        for dana_repayment_reference in dana_repayment_references:
            if dana_repayment_reference.id not in pending_dana_repayment_reference_ids:
                continue

            time_to_str = str(timezone.localtime(dana_repayment_reference.repaid_time))
            dana_payment_bill = dana_payment_bill_dicts[dana_repayment_reference.bill_id]
            data = {
                "partnerReferenceNo": dana_repayment_reference.partner_reference_no,
                "billId": dana_repayment_reference.bill_id,
                "billStatus": dana_repayment_reference.bill_status,
                "principalAmount": dana_repayment_reference.principal_amount,
                "interestFeeAmount": dana_repayment_reference.interest_fee_amount,
                "lateFeeAmount": dana_repayment_reference.late_fee_amount,
                "totalAmount": dana_repayment_reference.total_repayment_amount,
                "transTime": time_to_str,
                "creditUsageMutation": dana_repayment_reference.credit_usage_mutation,
                "repaymentId": dana_repayment_reference.repayment_id,
                "lenderProductId": (
                    dana_repayment_reference.payment.loan.danaloanreference.lender_product_id
                ),
                "waivedPrincipalAmount": dana_repayment_reference.waived_principal_amount,
                "waivedInterestFeeAmount": dana_repayment_reference.waived_interest_fee_amount,
                "waivedLateFeeAmount": dana_repayment_reference.waived_late_fee_amount,
                "totalWaivedAmount": dana_repayment_reference.total_waived_amount,
                # for event payment needed
                "danaLateFeeAmount": dana_repayment_reference.late_fee_amount,
                "dana_payment_bill": dana_payment_bill,
                "payment": payment_dicts[dana_payment_bill.payment_id],
                "payback_transaction_dicts": payback_transaction_dicts,
            }

            is_recalculated = True
            if hasattr(
                dana_repayment_reference.payment.loan.danaloanreference,
                "danaloanreferenceinsufficienthistory",
            ):
                dana_loan_reference = dana_repayment_reference.payment.loan.danaloanreference
                is_recalculated = (
                    dana_loan_reference.danaloanreferenceinsufficienthistory.is_recalculated
                )

            if dana_repayment_fs:
                create_manual_repayment_settlement_v2(
                    data=data, is_pending_process=True, is_recalculated=is_recalculated
                )
            else:
                create_manual_repayment_settlement(
                    data=data, is_pending_process=True, is_recalculated=is_recalculated
                )

            repayment_reference_status = drr_status_dicts.get(dana_repayment_reference.id)
            repayment_reference_status.udate = timezone.localtime(timezone.now())
            repayment_reference_status.status = RepaymentReferenceStatus.SUCCESS

            update_reference_status.append(repayment_reference_status)

        bulk_update(
            update_reference_status,
            using="partnership_db",
            update_fields=["status", "udate"],
            batch_size=100,
        )


def create_pending_repayment_reference(
    list_bill_pending: List,
    partner_reference_no: str,
    dana_customer_id: str,
    reference_no: str,
    repaid_time: datetime,
    credit_usage_mutation: int,
    repayment_id: str,
    lender_product_id: str,
) -> Tuple:
    bill_ids = []
    list_partner_reference_no = []
    dana_repayment_reference_list = []

    RepaymentReferenceResult = namedtuple(
        'RepaymentReferenceResult', ['bill_ids', 'list_partner_references_no']
    )

    for repayment_detail in list_bill_pending:
        bill_id = repayment_detail['billId']
        paid_principal = int(float(repayment_detail['repaymentPrincipalAmount']['value']))
        paid_interest = int(float(repayment_detail['repaymentInterestFeeAmount']['value']))
        paid_late_fee = int(float(repayment_detail['repaymentLateFeeAmount']['value']))
        total_paid_amount = int(float(repayment_detail['totalRepaymentAmount']['value']))
        waived_principal_amount = None
        waived_interest_fee_amount = None
        waived_late_fee_amount = None
        total_waived_amount = None
        waived_principal = repayment_detail.get('waivedPrincipalAmount')
        if waived_principal:
            waived_principal_amount = int(float(waived_principal.get('value', 0)))

        waived_interest_fee = repayment_detail.get('waivedInterestFeeAmount')
        if waived_interest_fee:
            waived_interest_fee_amount = int(float(waived_interest_fee.get('value', 0)))

        waived_late_fee = repayment_detail.get('waivedLateFeeAmount')
        if waived_late_fee:
            waived_late_fee_amount = int(float(waived_late_fee.get('value', 0)))

        total_waived = repayment_detail.get('totalWaivedAmount')
        if total_waived:
            total_waived_amount = int(float(total_waived.get('value', 0)))

        dana_payment_bill = DanaPaymentBill.objects.filter(bill_id=bill_id).last()
        payment_id = dana_payment_bill.payment_id
        payment = Payment.objects.get(id=payment_id)
        repayment_data = {
            'payment': payment,
            'partner_reference_no': partner_reference_no,
            'customer_id': dana_customer_id,
            'reference_no': reference_no,
            'bill_id': bill_id,
            'bill_status': repayment_detail['billStatus'],
            'principal_amount': paid_principal,
            'interest_fee_amount': paid_interest,
            'late_fee_amount': paid_late_fee,
            'total_repayment_amount': total_paid_amount,
            'repaid_time': repaid_time,
            'credit_usage_mutation': credit_usage_mutation,
            'repayment_id': repayment_id,
            'lender_product_id': lender_product_id,
            'waived_principal_amount': waived_principal_amount,
            'waived_interest_fee_amount': waived_interest_fee_amount,
            'waived_late_fee_amount': waived_late_fee_amount,
            'total_waived_amount': total_waived_amount,
        }
        dana_repayment_reference = DanaRepaymentReference(**repayment_data)
        dana_repayment_reference_list.append(dana_repayment_reference)

        list_partner_reference_no.append(partner_reference_no)
        bill_ids.append(repayment_detail['billId'])

    # Create Dana Repayment Reference and Dana Repayment Reference Status
    DanaRepaymentReference.objects.bulk_create(dana_repayment_reference_list, batch_size=30)

    created_dana_repayment_references = DanaRepaymentReference.objects.filter(
        partner_reference_no__in=list_partner_reference_no,
        bill_id__in=bill_ids,
    )

    dana_repayment_reference_status_list = []

    for repayment_reference in created_dana_repayment_references.iterator():
        dana_repayment_reference_status_list.append(
            DanaRepaymentReferenceStatus(
                dana_repayment_reference_id=repayment_reference.id,
                status=RepaymentReferenceStatus.PENDING,
            )
        )

    DanaRepaymentReferenceStatus.objects.bulk_create(
        dana_repayment_reference_status_list, batch_size=30
    )

    return RepaymentReferenceResult(bill_ids, list_partner_reference_no)


@transaction.atomic
def run_repayment_sync_process(
    validated_data: Dict,
    partner_reference_no: str,
    reference_no: str,
    account: Account,
    total_repayment_amount: int,
    repaid_time: datetime,
    is_active_log_feature_setting=False,
    log_data: Dict = {},
    repayment_redis_key: str = None,
) -> bool:
    from juloserver.dana.repayment.tasks import account_reactivation

    is_success_to_process = True

    # Start Check Logger Payback Execution Time
    if is_active_log_feature_setting:
        start_payback_execution_time = time.time()
        start_payback_execution_datetime = timezone.localtime(timezone.now())

    payback_transaction = PaybackTransaction.objects.get_or_none(
        transaction_id=partner_reference_no
    )

    if not payback_transaction:
        payback_transaction = PaybackTransaction.objects.create(
            transaction_id=partner_reference_no,
            is_processed=False,
            virtual_account=None,
            payment_method=None,
            payback_service='dana',
            amount=total_repayment_amount,
            transaction_date=repaid_time,
        )
    elif payback_transaction.is_processed:
        is_success_to_process = False

        # End Check Logger Payback Execution Time
        if is_active_log_feature_setting:
            payback_logger = construct_massive_logger(
                start_payback_execution_time,
                start_payback_execution_datetime,
            )

            log_data['payback_creation_execution_time'] = payback_logger
            logger.info(log_data)

        return is_success_to_process

    # End Check Logger Payback Execution Time
    if is_active_log_feature_setting:
        payback_logger = construct_massive_logger(
            start_payback_execution_time,
            start_payback_execution_datetime,
        )

        log_data['payback_creation_execution_time'] = payback_logger

    # Start Check Logger Payment Execution Time
    if is_active_log_feature_setting:
        start_payment_execution_time = time.time()
        start_payment_execution_datetime = timezone.localtime(timezone.now())

    paid_amount_account_payments, payment_events = consume_paid_amount_for_payment(
        validated_data, payback_transaction, reference_no
    )

    # End Check Logger Payment Execution Time
    if is_active_log_feature_setting:
        payment_logger = construct_massive_logger(
            start_payment_execution_time,
            start_payment_execution_datetime,
        )

        log_data['payment_creation_execution_time'] = payment_logger

    # Start Check Logger Account Payment Execution Time
    if is_active_log_feature_setting:
        start_acc_payment_execution_time = time.time()
        start_acc_payment_execution_datetime = timezone.localtime(timezone.now())

    (
        total_paid_principal,
        total_paid_interest,
        total_paid_late_fee,
    ) = consume_paid_amount_for_account_payment(paid_amount_account_payments, payback_transaction)

    # End Check Logger Account Payment Execution Time
    if is_active_log_feature_setting:
        acc_payment_logger = construct_massive_logger(
            start_acc_payment_execution_time,
            start_acc_payment_execution_datetime,
        )

        log_data['acc_payment_creation_execution_time'] = acc_payment_logger

    # Start Check Logger Account Limit Execution Time
    if is_active_log_feature_setting:
        start_acc_limit_execution_time = time.time()
        start_acc_limit_execution_datetime = timezone.localtime(timezone.now())

    lender_product_id = validated_data.get('lenderProductId')
    if lender_product_id == DanaProductType.CASH_LOAN:
        float_credit_usage_mutation = float(
            validated_data.get('creditUsageMutation', {}).get('value', 0)
        )
        credit_usage_mutation = int(float_credit_usage_mutation)
        change_limit_amount = credit_usage_mutation
    else:
        change_limit_amount = total_paid_principal + total_paid_interest

    loan_id = None
    if payment_events:
        loan_id = payment_events[0].payment.loan_id

    update_account_limit(change_limit_amount, account.id, loan_id)
    account_trx = AccountTransaction.objects.create(
        account=account,
        payback_transaction=payback_transaction,
        transaction_date=payback_transaction.transaction_date,
        transaction_amount=payback_transaction.amount,
        transaction_type='payment',
        towards_principal=total_paid_principal,
        towards_interest=total_paid_interest,
        towards_latefee=total_paid_late_fee,
    )
    for payment_event in payment_events:
        payment_event.update_safely(account_transaction=account_trx)
    payback_transaction.update_safely(is_processed=True)
    execute_after_transaction_safely(lambda: account_reactivation.delay(account.id))
    if repayment_redis_key:
        set_redis_key(repayment_redis_key, reference_no, 300)

    # End Check Logger Account Limit Execution Time
    if is_active_log_feature_setting:
        acc_limit_logger = construct_massive_logger(
            start_acc_limit_execution_time,
            start_acc_limit_execution_datetime,
        )

        log_data['acc_limit_creation_execution_time'] = acc_limit_logger

        logger.info(log_data)

    return is_success_to_process
