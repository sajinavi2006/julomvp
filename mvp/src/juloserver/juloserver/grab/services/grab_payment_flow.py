from django.db import transaction
from django.utils import timezone

from juloserver.account.models import AccountTransaction
from juloserver.account_payment.models import AccountPaymentNote, AccountPayment
from juloserver.account_payment.services.earning_cashback import (
    j1_update_cashback_earned,
    make_cashback_available
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Payment, PaymentEvent, PaymentNote
from juloserver.julo.utils import display_rupiah
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.minisquad.tasks2.intelix_task import (
    delete_paid_payment_from_intelix_if_exists_async_for_j1)
from juloserver.minisquad.services import insert_data_into_commission_table_for_j1
from juloserver.account_payment.services.collection_related import (
    update_ptp_for_paid_off_account_payment)
from juloserver.collection_vendor.task import process_unassignment_when_paid_for_j1
from juloserver.grab.services.loan_related import update_grab_transaction_id
from juloserver.grab.exceptions import GrabLogicException
from juloserver.account_payment.services.payment_flow import (
    update_account_payment_paid_off_status,
    notify_account_payment_over_paid,
    update_payment_paid_off_status
)
from juloserver.cashback.constants import CashbackChangeReason


def construct_old_paid_amount_grab(payment):
    old_paid_amount_list = dict()
    old_paid_amount_list[payment.id] = payment.paid_amount
    old_paid_amount_list["%s_detail" % payment.id] = {
        "paid_late_fee": payment.paid_late_fee,
        "paid_principal": payment.paid_principal,
        "paid_interest": payment.paid_interest,
    }
    return old_paid_amount_list


def process_grab_repayment_trx(payback_transaction_obj, note=None,
                               using_cashback=False, grab_txn_id='',
                               over_paid=True):
    if payback_transaction_obj.is_processed:
        raise JuloException("can't process payback transaction that has been processed")
    customer = payback_transaction_obj.customer
    account = customer.account
    loan = payback_transaction_obj.loan
    unpaid_payment_ids = loan.get_unpaid_payment_ids()
    remaining_amount = payback_transaction_obj.amount
    payment_events = []

    with transaction.atomic():
        towards_principal = 0
        towards_interest = 0
        towards_latefee = 0
        total_principal_paid = 0
        transaction_type = 'customer_wallet' if using_cashback else 'payment'
        for payment_id in unpaid_payment_ids:
            if remaining_amount == 0:
                break

            payment = Payment.objects.select_for_update().get(pk=payment_id)

            account_payment = AccountPayment.objects.select_for_update().get(
                pk=payment.account_payment.id)
            old_paid_amount_list = construct_old_paid_amount_grab(payment)

            remaining_amount, total_paid_principal = consume_payment_for_grab_principal(
                payment, remaining_amount, account_payment
            )
            total_principal_paid += total_paid_principal
            total_paid_interest = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_interest = consume_payment_for_grab_interest(
                    payment, remaining_amount, account_payment
                )
            total_paid_late_fee = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_late_fee = consume_payment_for_grab_late_fee(
                    payment, remaining_amount, account_payment
                )
            local_trx_date = timezone.localtime(payback_transaction_obj.transaction_date).date()
            payment_events += store_calculated_grab_payments(
                payment,
                local_trx_date,
                payback_transaction_obj.transaction_id,
                payback_transaction_obj.payment_method,
                old_paid_amount_list,
                using_cashback,
                note=note,
                grab_txn_id=grab_txn_id
            )
            account_payment.paid_date = local_trx_date
            if account_payment.due_amount == 0:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'paid_off'
                }
                update_account_payment_paid_off_status(account_payment)
                account_payment.create_account_payment_status_history(history_data)
            account_payment.save(update_fields=[
                'due_amount',
                'paid_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_date',
                'status',
                'udate'
            ])

            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payback_transaction_obj.payment_method:
                note_payment_method += 'payment_method: %s,\n\
                                        payment_receipt: %s' % (
                    payback_transaction_obj.payment_method.payment_method_name,
                    payback_transaction_obj.transaction_id
                )
            template_note = '[Add Event %s]\n\
                                    amount: %s,\n\
                                    date: %s%s%s.' % (
                transaction_type,
                display_rupiah(total_paid_principal + total_paid_interest + total_paid_late_fee),
                payback_transaction_obj.transaction_date.strftime("%d-%m-%Y"),
                note_payment_method,
                note
            )

            AccountPaymentNote.objects.create(
                note_text=template_note,
                account_payment=account_payment)

            if account_payment.due_amount == 0:
                update_ptp_for_paid_off_account_payment(account_payment)
                process_unassignment_when_paid_for_j1.delay(account_payment.id)
                delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(
                    account_payment.id)

            towards_principal += total_paid_principal
            towards_interest += total_paid_interest
            towards_latefee += total_paid_late_fee

        if remaining_amount > 0 and over_paid:
            # handle if paid off account do repayment
            if len(payment_events)>0:
                cashback_payment_event = payment_events[-1]
            else:
                cashback_payment_event = None
                
            if not account.get_unpaid_account_payment_ids():
                account_payment = account.accountpayment_set.last()

            notify_account_payment_over_paid(account_payment, remaining_amount)
            customer.change_wallet_balance(change_accruing=remaining_amount,
                                           change_available=remaining_amount,
                                           reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                                           account_payment=account_payment,
                                           payment_event=cashback_payment_event)
        payback_transaction_obj.update_safely(is_processed=True)

        account_trx = AccountTransaction.objects.create(
            account=account,
            payback_transaction=payback_transaction_obj,
            transaction_date=payback_transaction_obj.transaction_date,
            transaction_amount=payback_transaction_obj.amount,
            transaction_type=transaction_type,
            towards_principal=towards_principal,
            towards_interest=towards_interest,
            towards_latefee=towards_latefee
        )
        for payment_event in payment_events:
            payment_event.update_safely(account_transaction=account_trx)

        insert_data_into_commission_table_for_j1(payment_events)

        return account_trx, total_principal_paid


def consume_payment_for_grab_principal(
        payment, remaining_amount, account_payment, waiver_request=None, waiver_amount=None):
    total_paid_principal = 0

    if payment.paid_principal == payment.installment_principal:
        return remaining_amount, total_paid_principal
    remaining_principal = payment.installment_principal - payment.paid_principal
    if not waiver_request:
        if remaining_amount > remaining_principal:
            paid_principal = remaining_principal
        else:
            paid_principal = remaining_amount
    else:
        waiver_approval = waiver_request.waiverapproval_set.last()
        if waiver_approval:
            waiver_payment = waiver_approval.waiverpaymentapproval_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_principal = waiver_payment.approved_principal_waiver_amount
        else:
            waiver_payment = waiver_request.waiverpaymentrequest_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_principal = waiver_payment.requested_principal_waiver_amount

        if paid_principal > waiver_amount:
            paid_principal = waiver_amount
        waiver_amount -= paid_principal

    payment.paid_amount += paid_principal
    payment.due_amount -= paid_principal
    payment.paid_principal += paid_principal

    if not account_payment:
        raise GrabLogicException("AccountPayment not found for "
                                 "payment_id {}".format(payment.id))
    account_payment.paid_amount += paid_principal
    account_payment.due_amount -= paid_principal
    account_payment.paid_principal += paid_principal

    remaining_amount -= paid_principal
    total_paid_principal += paid_principal
    if remaining_amount == 0:
        return remaining_amount, total_paid_principal
    return remaining_amount, total_paid_principal


def consume_payment_for_grab_interest(
        payment, remaining_amount, account_payment, waiver_request=None, waiver_amount=None):
    total_paid_interest = 0
    if payment.paid_interest == payment.installment_interest:
        return remaining_amount, total_paid_interest
    remaining_interest = payment.installment_interest - payment.paid_interest
    if not waiver_request:
        if remaining_amount > remaining_interest:
            paid_interest = remaining_interest
        else:
            paid_interest = remaining_amount
    else:
        waiver_approval = waiver_request.waiverapproval_set.last()
        if waiver_approval:
            waiver_payment = waiver_approval.waiverpaymentapproval_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_interest = waiver_payment.approved_interest_waiver_amount
        else:
            waiver_payment = waiver_request.waiverpaymentrequest_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_interest = waiver_payment.requested_interest_waiver_amount

        if paid_interest > waiver_amount:
            paid_interest = waiver_amount
        waiver_amount -= paid_interest

    payment.paid_amount += paid_interest
    payment.due_amount -= paid_interest
    payment.paid_interest += paid_interest

    if not account_payment:
        raise GrabLogicException("AccountPayment not found for "
                                 "payment_id {}".format(payment.id))

    account_payment.paid_amount += paid_interest
    account_payment.due_amount -= paid_interest
    account_payment.paid_interest += paid_interest

    remaining_amount -= paid_interest
    total_paid_interest += paid_interest
    if remaining_amount == 0:
        return remaining_amount, total_paid_interest
    return remaining_amount, total_paid_interest


def consume_payment_for_grab_late_fee(
        payment, remaining_amount, account_payment, waiver_request=None, waiver_amount=None):
    total_paid_late_fee = 0
    if payment.paid_late_fee == payment.late_fee_amount:
        return remaining_amount, total_paid_late_fee
    remaining_late_fee = payment.late_fee_amount - payment.paid_late_fee
    if not waiver_request:
        if remaining_amount > remaining_late_fee:
            paid_late_fee = remaining_late_fee
        else:
            paid_late_fee = remaining_amount
    else:
        waiver_approval = waiver_request.waiverapproval_set.last()
        if waiver_approval:
            waiver_payment = waiver_approval.waiverpaymentapproval_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_late_fee = waiver_payment.approved_late_fee_waiver_amount
        else:
            waiver_payment = waiver_request.waiverpaymentrequest_set.get(payment=payment)
            if not waiver_payment:
                raise GrabLogicException("waiver_payment is empty")
            paid_late_fee = waiver_payment.requested_late_fee_waiver_amount

        if paid_late_fee > waiver_amount:
            paid_late_fee = waiver_amount
        waiver_amount -= paid_late_fee

    payment.paid_amount += paid_late_fee
    payment.due_amount -= paid_late_fee
    payment.paid_late_fee += paid_late_fee

    if not account_payment:
        raise GrabLogicException("AccountPayment not found for "
                                 "payment_id {}".format(payment.id))

    account_payment.paid_amount += paid_late_fee
    account_payment.due_amount -= paid_late_fee
    account_payment.paid_late_fee += paid_late_fee

    remaining_amount -= paid_late_fee
    total_paid_late_fee += paid_late_fee
    if remaining_amount == 0:
        return remaining_amount, total_paid_late_fee
    return remaining_amount, total_paid_late_fee


def store_calculated_grab_payments(payment, paid_date, payment_receipt,
                                   payment_method, old_paid_amount_list, using_cashback,
                                   event_type=None, note='', grab_txn_id=''):
    from juloserver.followthemoney.services import create_manual_transaction_mapping
    payment_events = []
    total_paid_amount = payment.paid_amount - old_paid_amount_list[payment.id]
    if total_paid_amount > 0:
        if not event_type:
            event_type = 'customer_wallet' if using_cashback else 'payment'
        payment_event = PaymentEvent.objects.create(
            payment=payment,
            event_payment=total_paid_amount,
            event_due_amount=payment.due_amount + total_paid_amount,
            event_date=paid_date,
            event_type=event_type,
            payment_receipt=payment_receipt,
            payment_method=payment_method,
            can_reverse=False  # reverse (void) must be via account payment level
        )
        payment_events.append(payment_event)
        if event_type == "payment":
            old_payment_detail = old_paid_amount_list["%s_detail" % payment.id]
            paid_principal = payment.paid_principal - old_payment_detail["paid_principal"]
            paid_interest = payment.paid_interest - old_payment_detail["paid_interest"]
            paid_late_fee = payment.paid_late_fee - old_payment_detail["paid_late_fee"]
            create_manual_transaction_mapping(
                payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee)

        payment.paid_date = paid_date
        payment_update_fields = [
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
            'paid_amount',
            'due_amount',
            'paid_date',
            'udate']

        loan = payment.loan
        if payment.due_amount == 0:
            payment_history = {
                'payment_old_status_code': payment.status,
                'loan_old_status_code': payment.loan.status}

            update_payment_paid_off_status(payment)
            payment_update_fields.append('payment_status')

            # check cashback earning
            if payment.paid_late_days <= 0 and loan.product.has_cashback_pmt:
                j1_update_cashback_earned(payment)
                loan.update_cashback_earned_total(payment.cashback_earned)
                loan.save()
                payment_update_fields.append('cashback_earned')

        payment.save(update_fields=payment_update_fields)

        # take care loan level
        unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
        if payment.account_payment:
            changed_by_id = None
        else:
            changed_by_id = payment_event.added_by.id if payment_event.added_by else None
        if len(unpaid_payments) == 0:  # this mean loan is paid_off
            update_loan_status_and_loan_history(loan_id=loan.id,
                                                new_status_code=LoanStatusCodes.PAID_OFF,
                                                change_by_id=changed_by_id,
                                                change_reason="Loan paid off")
            loan.refresh_from_db()
            if loan.product.has_cashback:
                make_cashback_available(loan)
        elif payment.due_amount == 0:
            loan.refresh_from_db()
            current_loan_status = loan.status
            loan.update_status(record_history=False)
            if current_loan_status != loan.status:
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=loan.status,
                    change_by_id=changed_by_id,
                    change_reason="update loan status after payment paid off")

        # create payment history regarding to loan status as well
        if payment.due_amount == 0:
            payment.create_payment_history(payment_history)

        note = ',\nnote: %s' % note
        note_payment_method = ',\n'
        if payment_method:
            note_payment_method += 'payment_method: %s,\n\
                        payment_receipt: %s' % (
                payment_method.payment_method_name,
                payment_event.payment_receipt
            )
        template_note = '[Add Event %s]\n\
                    amount: %s,\n\
                    date: %s%s%s.' % (
            event_type,
            display_rupiah(payment_event.event_payment),
            payment_event.event_date.strftime("%d-%m-%Y"),
            note_payment_method,
            note
        )
        if grab_txn_id:
            update_grab_transaction_id(payment, grab_txn_id, total_paid_amount)

        PaymentNote.objects.create(
            note_text=template_note,
            payment=payment)

    return payment_events
