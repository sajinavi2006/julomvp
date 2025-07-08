import logging
import collections

from django.db import transaction
from django.db.models import Sum
from django.forms.models import model_to_dict
from django.utils import timezone
from copy import deepcopy

from juloserver.account.models import AccountTransaction
from juloserver.account.constants import AccountTransactionNotes
from juloserver.account.services.account_related import (
    update_account_status_based_on_account_payment,
    update_cashback_counter_account,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.collection_related import (
    update_ptp_for_paid_off_account_payment,
    get_cashback_claim_experiment,
    void_cashback_claim_experiment,
    void_cashback_claim_payment_experiment,
)
from juloserver.account_payment.services.earning_cashback import (
    reverse_cashback_available,
    j1_update_cashback_earned, make_cashback_available,
)
from juloserver.account_payment.services.payment_flow import (
    construct_old_paid_amount_list,
    update_payment_paid_off_status,
    update_account_payment_paid_off_status,
)
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.collection_vendor.task import process_unassignment_when_paid_for_j1
from juloserver.early_limit_release.tasks import rollback_early_limit_release
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Payment, PaymentEvent, PaymentNote, CustomerWalletHistory, Loan, PTP, CashbackCounterHistory)
from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely
)
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.minisquad.tasks2.intelix_task import \
    delete_paid_payment_from_intelix_if_exists_async_for_j1
from juloserver.minisquad.models import CommissionLookup
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.minisquad.services2.dialer_related import (
    delete_temp_bucket_base_on_account_payment_ids_and_bucket,
)
from juloserver.minisquad.tasks2.dialer_system_task import delete_paid_payment_from_dialer
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.constants import NewCashbackConst

logger = logging.getLogger(__name__)


def consume_reversal_for_late_fee(payments, remaining_amount, account_payment):
    total_reversed_late_fee = 0
    for payment in payments:
        paid_late_fee = payment.paid_late_fee
        if paid_late_fee == 0:
            continue
        if remaining_amount > paid_late_fee:
            reversed_late_fee = paid_late_fee
        else:
            reversed_late_fee = remaining_amount
        payment.paid_amount -= reversed_late_fee
        payment.due_amount += reversed_late_fee
        payment.paid_late_fee -= reversed_late_fee

        account_payment.paid_amount -= reversed_late_fee
        account_payment.due_amount += reversed_late_fee
        account_payment.paid_late_fee -= reversed_late_fee

        remaining_amount -= reversed_late_fee
        total_reversed_late_fee += reversed_late_fee
        if remaining_amount == 0:
            break
    return remaining_amount, total_reversed_late_fee


def consume_reversal_for_interest(payments, remaining_amount, account_payment):
    total_reversed_interest = 0
    for payment in payments:
        paid_interest = payment.paid_interest
        if paid_interest == 0:
            continue
        if remaining_amount > paid_interest:
            reversed_interest = paid_interest
        else:
            reversed_interest = remaining_amount
        payment.paid_amount -= reversed_interest
        payment.due_amount += reversed_interest
        payment.paid_interest -= reversed_interest

        account_payment.paid_amount -= reversed_interest
        account_payment.due_amount += reversed_interest
        account_payment.paid_interest -= reversed_interest

        remaining_amount -= reversed_interest
        total_reversed_interest += reversed_interest
        if remaining_amount == 0:
            break
    return remaining_amount, total_reversed_interest


def consume_reversal_for_principal(payments, remaining_amount, account_payment):
    total_reversed_principal = 0
    for payment in payments:
        paid_principal = payment.paid_principal
        if paid_principal == 0:
            continue
        if remaining_amount > paid_principal:
            reversed_principal = paid_principal
        else:
            reversed_principal = remaining_amount
        payment.paid_amount -= reversed_principal
        payment.due_amount += reversed_principal
        payment.paid_principal -= reversed_principal

        account_payment.paid_amount -= reversed_principal
        account_payment.due_amount += reversed_principal
        account_payment.paid_principal -= reversed_principal

        remaining_amount -= reversed_principal
        total_reversed_principal += reversed_principal
        if remaining_amount == 0:
            break
    return remaining_amount, total_reversed_principal


def store_reversed_payments(
    payment_list,
    reversed_date,
    payment_receipt,
    payment_method,
    old_paid_amount_list,
    note='',
    paid_with_cashback=False,
    is_eligible_cashback_new_scheme=False,
    percentage_mapping=dict(),
):
    from juloserver.followthemoney.services import create_manual_transaction_mapping

    payment_event_voids = []
    for payment in payment_list:
        total_reversed_amount = old_paid_amount_list[payment.id] - payment.paid_amount
        if total_reversed_amount > 0:
            event_type = 'customer_wallet_void' if paid_with_cashback else 'payment_void'
            payment_event = PaymentEvent.objects.create(
                payment=payment,
                event_payment=-total_reversed_amount,
                event_due_amount=payment.due_amount - total_reversed_amount,
                event_date=reversed_date,
                event_type=event_type,
                payment_receipt=payment_receipt,
                payment_method=payment_method,
                can_reverse=False,  # reverse (void) must be via account payment level
            )
            payment_event_voids.append(payment_event)
            if event_type == "payment_void":
                old_payment_detail = old_paid_amount_list["%s_detail" % payment.id]
                paid_principal = old_payment_detail["paid_principal"] - payment.paid_principal
                paid_interest = old_payment_detail["paid_interest"] - payment.paid_interest
                paid_late_fee = old_payment_detail["paid_late_fee"] - payment.paid_late_fee
                create_manual_transaction_mapping(
                    payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee
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

            counter = 0
            if is_eligible_cashback_new_scheme and not paid_with_cashback:
                counter_data = (
                    CashbackCounterHistory.objects.filter(payment_id=payment.id)
                    .values('counter', 'cdate')
                    .last()
                    or 0
                )
                if counter_data:
                    counter = counter_data['counter']
                    if counter == NewCashbackConst.MAX_CASHBACK_COUNTER:
                        old_counter = (
                            CashbackCounterHistory.objects.filter(
                                cdate__lt=counter_data['cdate'],
                                account_payment__account_id=payment.account_payment.account.id,
                            )
                            .exclude(account_payment_id=payment.account_payment.id)
                            .order_by('-cdate')
                            .values('counter', 'cdate')
                        )
                        if old_counter[0]['counter'] == NewCashbackConst.MAX_CASHBACK_COUNTER:
                            counter = NewCashbackConst.MAX_CASHBACK_COUNTER
                        else:
                            counter = counter - 1 if counter > 0 else counter
                    else:
                        counter = counter - 1 if counter > 0 else counter

            # reverse for cashback overpaid if any
            if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF:
                overpaid_cashback = CustomerWalletHistory.objects.filter(
                    loan=loan,
                    change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                ).last()

                if overpaid_cashback:
                    reversed_accruing = overpaid_cashback.wallet_balance_accruing_old - \
                        overpaid_cashback.wallet_balance_accruing

                    reversed_available = overpaid_cashback.wallet_balance_available_old - \
                        overpaid_cashback.wallet_balance_available

                    loan.customer.change_wallet_balance(
                        change_accruing=reversed_accruing,
                        change_available=reversed_available,
                        reason=CashbackChangeReason.CASHBACK_OVER_PAID_VOID,
                        account_payment=payment.account_payment,
                    )

            # reverse cashback available
            if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF:
                reverse_cashback_available(loan)

            new_cashback_percentage = percentage_mapping.get(str(counter), 0)
            # reverse cashback earning
            if payment.cashback_earned:
                loan.customer.change_wallet_balance(
                    change_accruing=-payment.cashback_earned,
                    change_available=0,
                    reason=event_type,
                    payment=payment,
                    account_payment=payment.account_payment,
                    is_eligible_new_cashback=is_eligible_cashback_new_scheme,
                    counter=counter,
                    new_cashback_percentage=new_cashback_percentage,
                    reversal_counter=True
                )
                loan.cashback_earned_total -= payment.cashback_earned
                loan.save()
                payment.cashback_earned = 0
                payment_update_fields.append('cashback_earned')

            # reverse void cashback claim experiment
            _, is_cashback_experiment = get_cashback_claim_experiment(
                date=reversed_date, account=loan.account
            )
            if is_cashback_experiment:
                void_cashback_claim_payment_experiment(
                    payment,
                    is_eligible_new_cashback=is_eligible_cashback_new_scheme,
                    counter=counter,
                    new_cashback_percentage=new_cashback_percentage,
                )

            # monkey patch for paid_off status always get 312,
            # set to not due before calling the function
            payment.payment_status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
            payment.update_status_based_on_due_date()

            # to handle really really edge case
            # payment done but not paid off -> late fee void and paid off -> payment void
            total_outstanding_amount = (
                (payment.installment_principal - payment.paid_principal)
                + (payment.installment_interest - payment.paid_interest)
                + (payment.late_fee_amount - payment.paid_late_fee)
            )

            if payment.due_amount > total_outstanding_amount:
                payment.due_amount = total_outstanding_amount

            payment.save(update_fields=payment_update_fields)

            # take care loan level
            changed_by_id = payment_event.added_by.id if payment_event.added_by else None
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

            if paid_with_cashback:
                # refund cashback
                loan.customer.change_wallet_balance(
                    change_accruing=abs(payment_event.event_payment),
                    change_available=abs(payment_event.event_payment),
                    reason=event_type,
                    payment=payment,
                    account_payment=payment.account_payment,
                )
                reversal_type = 'Customer Wallet'
            else:
                reversal_type = 'Payment'

            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payment_method:
                note_payment_method += (
                    'payment_method: %s,\n\
                payment_receipt: %s'
                    % (payment_method.payment_method_name, payment_event.payment_receipt)
                )
            template_note = (
                '[Reversal %s]\n\
            amount: %s,\n\
            date: %s%s%s.'
                % (
                    reversal_type,
                    display_rupiah(payment_event.event_payment),
                    payment_event.event_date.strftime("%d-%m-%Y"),
                    note_payment_method,
                    note,
                )
            )

            PaymentNote.objects.create(note_text=template_note, payment=payment)

    return payment_event_voids


def void_commision_and_update_ptp_status(payment_void_trx):
    try:
        original_transaction = payment_void_trx.original_transaction
        original_transaction.refresh_from_db()
        void_original_transaction = original_transaction.reversal_transaction
        account_payment_ids = (
            original_transaction.paymentevent_set.filter(event_type='payment')
            .order_by('id')
            .values_list('payment__account_payment', flat=True)
        )

        for account_payment_id in account_payment_ids:
            account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
            if account_payment:
                active_ptps = PTP.objects.filter(
                    ptp_date__gte=original_transaction.transaction_date.date(),
                    cdate__date__lte=original_transaction.transaction_date.date(),
                    account=original_transaction.account,
                    account_payment=account_payment,
                )

                # handle case for paid after ptp date
                # bring back ptp_date and ptp_status
                paid_date = original_transaction.transaction_date.date()
                expired_ptp = PTP.objects.filter(
                    ptp_date__lt=paid_date,
                    ptp_status__isnull=False,
                    account_payment=account_payment,
                ).last()

                if expired_ptp:
                    account_payment.update_safely(ptp_date=expired_ptp.ptp_date)
                    expired_ptp.update_safely(ptp_status=None)

                with transaction.atomic():
                    if active_ptps:
                        commission_lookup = CommissionLookup.objects.filter(
                            account=original_transaction.account,
                            account_payment=account_payment,
                            credited_amount=original_transaction.transaction_amount,
                        ).last()
                        if commission_lookup:
                            commission_lookup.payment_amount -= abs(
                                payment_void_trx.transaction_amount
                            )
                            commission_lookup.credited_amount -= abs(
                                payment_void_trx.transaction_amount
                            )
                            commission_lookup.save()

                        for ptp in active_ptps:
                            sum_of_payments = 0
                            all_payment_events = PaymentEvent.objects.filter(
                                payment__account_payment=ptp.account_payment,
                                payment__account_payment__account=ptp.account,
                                event_date__lte=ptp.ptp_date,
                                event_date__gte=ptp.cdate,
                                account_transaction=original_transaction,
                            )

                            sum_of_payments = all_payment_events.filter(
                                event_type='payment'
                            ).aggregate(Sum('event_payment'))['event_payment__sum']

                            sum_of_payment_voids = 0
                            if void_original_transaction:
                                all_payment_void_events = PaymentEvent.objects.filter(
                                    payment__account_payment=ptp.account_payment,
                                    payment__account_payment__account=ptp.account,
                                    event_date__gte=ptp.cdate,
                                    account_transaction=void_original_transaction,
                                )

                                sum_of_payment_voids = all_payment_void_events.filter(
                                    event_type='payment_void'
                                ).aggregate(Sum('event_payment'))['event_payment__sum']

                            if sum_of_payments - abs(sum_of_payment_voids) < ptp.ptp_amount:
                                ptp.ptp_status = None
                                ptp.save()
                                account_payment.update_safely(ptp_date=ptp.ptp_date)

                        return True
                    return False
    except Exception as exc:
        logger.exception(exc)
        return False


def process_account_transaction_reversal(account_transaction, note='', refinancing_reversal=False):
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )

    target_payment_events = account_transaction.paymentevent_set.all()
    if not target_payment_events:
        raise JuloException(
            'Payment_event for '
            'account_transaction_id=%s not found'
            'potentially this is an old '
            'account_transaction which not reversable ' % account_transaction.id
        )
    account = account_transaction.account
    is_eligible_cashback_new_scheme = account.is_eligible_for_cashback_new_scheme
    _, percentage_mapping = get_paramters_cashback_new_scheme()
    payback_trx = account_transaction.payback_transaction
    payment_receipt = payback_trx.transaction_id
    payment_method = payback_trx.payment_method

    paid_with_cashback = True if payback_trx.payback_service == 'cashback' else False

    with transaction.atomic(), transaction.atomic(using='collection_db'):
        towards_principal = 0
        towards_interest = 0
        towards_latefee = 0
        voided_events = []
        unpaid_account_payment_ids = []
        payment_ids = target_payment_events.values_list('payment_id', flat=True)
        payments = Payment.objects.filter(id__in=payment_ids)
        old_paid_amount_list = construct_old_paid_amount_list(payments)
        for target_payment_event in target_payment_events:
            payments = [target_payment_event.payment]

            # lock account_payment data
            account_payment = AccountPayment.objects.select_for_update().get(
                pk=target_payment_event.payment.account_payment.id
            )

            remaining_amount = target_payment_event.event_payment

            remaining_amount, total_reversed_late_fee = consume_reversal_for_late_fee(
                payments, remaining_amount, account_payment
            )
            total_reversed_interest = 0
            if remaining_amount > 0:
                remaining_amount, total_reversed_interest = consume_reversal_for_interest(
                    payments, remaining_amount, account_payment
                )
            total_reversed_principal = 0
            if remaining_amount > 0:
                remaining_amount, total_reversed_principal = consume_reversal_for_principal(
                    payments, remaining_amount, account_payment
                )

            local_trx_time = timezone.localtime(timezone.now())
            payment_event_voids = store_reversed_payments(
                payments,
                target_payment_event.event_date,
                payment_receipt,
                payment_method,
                old_paid_amount_list,
                note=note,
                paid_with_cashback=paid_with_cashback,
                is_eligible_cashback_new_scheme=is_eligible_cashback_new_scheme,
                percentage_mapping=percentage_mapping,
            )

            transaction_type = 'customer_wallet_void' if paid_with_cashback else 'payment_void'

            history_data = {'status_old': account_payment.status, 'change_reason': transaction_type}
            account_payment.update_status_based_on_payment()
            account_payment.update_paid_date_based_on_payment()
            if history_data['status_old'] != account_payment.status:
                unpaid_account_payment_ids.append(account_payment.id)
                account_payment.create_account_payment_status_history(history_data)
                update_cashback_counter_account(account_payment, is_reversal=True)

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

            # to handle really really edge case
            # payment done but not paid off -> late fee void and paid off -> payment void
            total_outstanding_amount = 0
            for payment in account_payment.payment_set.filter(
                payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
            ):
                total_outstanding_amount += (
                    (payment.installment_principal - payment.paid_principal)
                    + (payment.installment_interest - payment.paid_interest)
                    + (payment.late_fee_amount - payment.paid_late_fee)
                )

            if account_payment.due_amount > total_outstanding_amount:
                account_payment.due_amount = total_outstanding_amount

            account_payment.save(update_fields=account_payment_updated_fields)

            # need to call this task for re-updating account status
            update_account_status_based_on_account_payment(
                account_payment, reason_override=transaction_type
            )

            towards_principal += total_reversed_principal
            towards_interest += total_reversed_interest
            towards_latefee += total_reversed_late_fee
            voided_events += payment_event_voids

        payments = Payment.objects.filter(id__in=payment_ids)
        loan_payments_list = construct_loan_payments_list(payments, old_paid_amount_list)
        account_transaction_dict = dict(
            account=account,
            transaction_date=local_trx_time,
            transaction_amount=-account_transaction.transaction_amount,
            transaction_type=transaction_type,
            towards_principal=-towards_principal,
            towards_interest=-towards_interest,
            towards_latefee=-towards_latefee,
            can_reverse=False,
        )
        if refinancing_reversal:
            account_transaction_dict.update(
                account_transaction_note=AccountTransactionNotes.VoidRefinancing,
            )
        else:
            if loan_payments_list:
                execute_after_transaction_safely(
                    lambda: rollback_early_limit_release.delay(loan_payments_list)
                )

        reversal_account_trx = AccountTransaction.objects.create(**account_transaction_dict)
        for payment_event_void in voided_events:
            payment_event_void.update_safely(account_transaction=reversal_account_trx)

        account_transaction.update_safely(
            can_reverse=False, reversal_transaction=reversal_account_trx
        )

        # reverse back account property
        reverse_is_proven(account)

        if transaction_type == 'payment_void':
            void_commision_and_update_ptp_status(reversal_account_trx)

        if unpaid_account_payment_ids:
            void_cashback_claim_experiment(unpaid_account_payment_ids)

        return reversal_account_trx


def process_late_fee_reversal(account_transaction, note=''):
    if not account_transaction.can_reverse:
        raise JuloException('account_transaction is not reversible')

    # circular import
    if account_transaction.transaction_type != 'late_fee':
        raise JuloException('invalid transaction type')

    transaction_time = timezone.localtime(timezone.now())
    late_fee_events = PaymentEvent.objects.filter(
        event_type='late_fee', account_transaction=account_transaction
    )

    if not late_fee_events:
        raise JuloException('no late_fee payment event for this account_payment')
    transaction_amount = 0
    with transaction.atomic():
        late_fee_event_voids = []
        account_payments = []

        def default_value():
            return 0
        account_payments_late_fee = collections.defaultdict(default_value)
        for late_fee_event in late_fee_events:
            payment = late_fee_event.payment
            note = ',\nnote: %s' % (note)
            template_note = (
                '[Reversal Late Fee]\n\
            amount: %s,\n\
            date: %s%s.'
                % (
                    display_rupiah(abs(late_fee_event.event_payment)),
                    late_fee_event.event_date.strftime("%d-%m-%Y"),
                    note,
                )
            )
            affected_amount = payment.due_amount - abs(late_fee_event.event_payment)
            due_amount_after = affected_amount if affected_amount >= 0 else 0
            due_amount_before = payment.due_amount
            payment.late_fee_applied -= 1
            payment.due_amount = due_amount_after
            payment.late_fee_amount -= abs(late_fee_event.event_payment)
            payment.update_status_based_on_due_date()
            if payment.account_payment:
                if payment.account_payment not in account_payments:
                    account_payments.append(payment.account_payment)
                account_payments_late_fee[payment.account_payment.id] -= abs(
                    late_fee_event.event_payment)

            payment_update_fields = [
                'late_fee_applied',
                'due_amount',
                'late_fee_amount',
                'payment_status',
                'udate',
            ]
            # check if payment is paid off after voiding late fee
            loan = payment.loan
            if payment.due_amount == 0:
                payment_history = {
                    'payment_old_status_code': payment.status,
                    'loan_old_status_code': loan.status,
                }

                update_payment_paid_off_status(payment)

                # check cashback earning
                if payment.paid_late_days <= 0 and loan.product.has_cashback_pmt:
                    j1_update_cashback_earned(payment)
                    loan.update_cashback_earned_total(payment.cashback_earned)
                    loan.save()
                    payment_update_fields.append('cashback_earned')
            payment.save(update_fields=payment_update_fields)

            # create payment history regarding to loan status as well
            if payment.due_amount == 0:
                payment.create_payment_history(payment_history)

            late_fee_event_void = reverse_late_fee_event(late_fee_event, due_amount_before)
            late_fee_event_voids.append(late_fee_event_void)
            PaymentNote.objects.create(
                note_text=template_note,
                payment=payment)

            # check whether there's an overpaid amount indicated with minus affected_amount
            overpaid = affected_amount < 0
            if overpaid:
                customer = loan.customer
                customer.change_wallet_balance(
                    change_accruing=abs(affected_amount),
                    change_available=abs(affected_amount),
                    reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                    payment=payment,
                    account_payment=payment.account_payment,
                    payment_event=late_fee_event_void
                )

            # take care loan level
            unpaid_payments = list(Payment.objects.by_loan(loan).not_paid())
            changed_by_id = (
                late_fee_event_void.added_by.id if late_fee_event_void.added_by else None
            )
            if len(unpaid_payments) == 0:  # this mean loan is paid_off
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.PAID_OFF,
                    change_by_id=changed_by_id,
                    change_reason="Loan paid off",
                )
                loan.refresh_from_db()
                if loan.product.has_cashback:
                    make_cashback_available(loan)
            elif payment.due_amount == 0:
                current_loan_status = loan.status
                loan.update_status(record_history=False)
                if current_loan_status != loan.status:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=loan.status,
                        change_by_id=changed_by_id,
                        change_reason="update loan status after payment paid off",
                    )

            transaction_amount += late_fee_event.event_payment

        reversal_account_trx = AccountTransaction.objects.create(
            account=account_transaction.account,
            transaction_date=transaction_time,
            transaction_amount=abs(transaction_amount),
            transaction_type='late_fee_void',
            towards_latefee=abs(transaction_amount),
            can_reverse=False,
        )

        for late_fee_event_void in late_fee_event_voids:
            late_fee_event_void.update_safely(account_transaction=reversal_account_trx)

        for account_payment in account_payments:
            account_affected_amount = account_payment.due_amount - \
                abs(account_payments_late_fee[account_payment.id])
            account_due_amount_after = account_affected_amount \
                if account_affected_amount >= 0 else 0

            account_payment.late_fee_amount -= abs(account_payments_late_fee[account_payment.id])
            account_payment.due_amount = account_due_amount_after
            account_payment.late_fee_applied -= 1

            if account_payment.due_amount == 0:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'paid_off %s' % note,
                }
                update_account_payment_paid_off_status(account_payment)
                # delete account_payment bucket 3 data on collection table
                # logic paid off
                delete_temp_bucket_base_on_account_payment_ids_and_bucket([account_payment.id])
                account_payment.create_account_payment_status_history(history_data)

            account_payment.save()
            update_va_bni_transaction.delay(
                account_transaction.account.id,
                'account_payment.services.reversal.process_late_fee_reversal',
            )
            if account_payment.due_amount == 0:
                update_ptp_for_paid_off_account_payment(account_payment)
                process_unassignment_when_paid_for_j1(account_payment.id)
                delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(account_payment.id)
                delete_paid_payment_from_dialer.delay(account_payment.id)

        account_transaction.update_safely(
            can_reverse=False, reversal_transaction=reversal_account_trx
        )

    return reversal_account_trx


def update_ptp_status_for_origin_account_transaction(origin_account_trx):
    try:
        origin_account_payment = (
            origin_account_trx.paymentevent_set.filter(event_type='payment')
            .last()
            .payment.account_payment
        )

        with transaction.atomic():
            # bring back ptp_status and ptp_date origin_account_trx
            origin_active_ptp = PTP.objects.filter(
                ptp_date__gte=origin_account_trx.transaction_date,
                cdate__lte=origin_account_trx.transaction_date,
                account=origin_account_trx.account,
                account_payment=origin_account_payment,
                ptp_status__isnull=False,
            ).last()

            if origin_active_ptp:
                origin_account_payment.update_safely(ptp_date=origin_active_ptp.ptp_date)
                origin_active_ptp.update_safely(ptp_status=None)

            return True
    except Exception as exc:
        logger.exception(exc)
        return False


def reverse_late_fee_event(payment_event, payment_due_amount):
    logger.info({'action': 'reverse_late_fee_event', 'payment_event': payment_event.id})
    with transaction.atomic():
        payment_event.can_reverse = False
        payment_event.save()
        payment_event_void = PaymentEvent.objects.create(
            payment=payment_event.payment,
            event_payment=payment_event.event_payment * -1,
            event_due_amount=payment_due_amount,
            event_date=(timezone.localtime(timezone.now())).date(),
            event_type='%s_void' % payment_event.event_type,
            payment_receipt=payment_event.payment_receipt,
            payment_method=payment_event.payment_method,
            can_reverse=False,
        )
    return payment_event_void


def transfer_payment_after_reversal(origin_account_trx, account_destination,
                                    reversal_account_trx, from_refinancing=False):
    from juloserver.account_payment.services.payment_flow import process_repayment_trx

    note = 'Transferred from account_transaction_id %s with amount %s due to reversal' % (
        origin_account_trx.id,
        origin_account_trx.transaction_amount,
    )

    if origin_account_trx.payback_transaction.payback_service == 'cashback' \
            and not from_refinancing:
        raise JuloException('invalid transaction type, payment using cashback not transferable')

    # copy original payback_trx then change the value needed for feeding process_repayment_trx
    # using copy to avoid damaging original payback_transaction
    payback_trx_destination = deepcopy(origin_account_trx.payback_transaction)

    payback_trx_destination.id = None
    payback_trx_destination.account = account_destination
    payback_trx_destination.customer = account_destination.customer
    payback_trx_destination.is_processed = False
    payback_trx_destination.payback_service = (
        'reversal (transferred from payback_trx_id %s)' % origin_account_trx.payback_transaction.id
    )
    if origin_account_trx.payback_transaction.payback_service == 'cashback':
        payback_trx_destination.transaction_id = (
            'cashback-trans-%s' % origin_account_trx.payback_transaction.id
        )

        account_payment = account_destination.get_oldest_unpaid_account_payment() \
            or account_destination.accountpayment_set.last()
        if not account_payment:
            raise JuloException('user do not have account payment')
        payment = account_payment.payment_set.last()
        if not payment:
            raise JuloException('account payment do not have payment')

        payback_trx_destination.account.customer.change_wallet_balance(
            change_accruing=-payback_trx_destination.amount,
            change_available=-payback_trx_destination.amount,
            reason='used_on_payment',
            account_payment=account_payment,
            payment=payment,
        )

        using_cashback = True
    else:
        payback_trx_destination.transaction_id += (
            '-trans-%s' % origin_account_trx.payback_transaction.id
        )
        using_cashback = False

    payback_trx_destination.loan = None
    payback_trx_destination.payment = None
    payback_trx_destination.save()

    account_trx_destination = process_repayment_trx(
        payback_trx_destination,
        note=note,
        using_cashback=using_cashback,
        from_refinancing=from_refinancing,
    )
    if account_trx_destination:
        execute_after_transaction_safely(
            lambda: update_moengage_for_payment_received_task.delay(account_trx_destination.id)
        )

    account_trx_destination.update_safely(reversed_transaction_origin=reversal_account_trx)
    update_ptp_status_for_origin_account_transaction(origin_account_trx)


def process_customer_payment_reversal(target_account_trx, account_destination=None, note=''):
    from juloserver.account_payment.tasks.repayment_tasks import (
        reversal_update_collection_risk_bucket_paid_first_installment_task,
    )

    if not target_account_trx.can_reverse:
        raise JuloException('account_transaction is not reversible')

    if target_account_trx.transaction_type not in ('customer_wallet', 'payment'):
        raise JuloException('invalid transaction type')
    newer_account_trxs = target_account_trx.account.accounttransaction_set.filter(
        cdate__gt=target_account_trx.cdate,
        transaction_type__in=('payment', 'customer_wallet'),
        can_reverse=True,
    ).order_by('-cdate')

    temp_note = 'Temporary void due to reversal for account_id: %s' % target_account_trx.id

    # if any newer account_trx comparing to target, temporary void all
    temp_reversed_account_trxs = []
    with transaction.atomic():
        if newer_account_trxs:
            for newer_account_trx in newer_account_trxs:
                temp_reversed_account_trxs.append(
                    process_account_transaction_reversal(newer_account_trx, temp_note)
                )

        # void the target
        reversed_account_trx = process_account_transaction_reversal(target_account_trx, note=note)

        # bring back temporary voided payment
        if temp_reversed_account_trxs:
            for temp_reversed_account_trx in temp_reversed_account_trxs:
                transfer_payment_after_reversal(
                    temp_reversed_account_trx.original_transaction,
                    temp_reversed_account_trx.account,
                    temp_reversed_account_trx,
                )

        if account_destination:
            transfer_payment_after_reversal(
                target_account_trx, account_destination, reversed_account_trx
            )

        # update reversal collection_risk_bucket_paid_first_installment
        reversal_update_collection_risk_bucket_paid_first_installment_task.delay(
            target_account_trx.account.id
        )


def reverse_is_proven(account):
    from juloserver.account.services.credit_limit import store_account_property_history

    account_property = account.accountproperty_set.last()
    if not account_property:
        return
    if account_property.concurrency is False and account_property.is_proven is False:
        return

    total_loan_amount = Loan.objects.filter(
        account=account, loan_status_id=LoanStatusCodes.PAID_OFF
    ).aggregate(Sum('loan_amount'))['loan_amount__sum']

    if (total_loan_amount or 0) < (account_property.proven_threshold or 0):
        current_account_property = model_to_dict(account.accountproperty_set.last())
        input_params = dict(is_proven=False, voice_recording=True)
        account_property.update_safely(**input_params)
        # create history
        store_account_property_history(input_params, account_property, current_account_property)


def construct_loan_payments_list(payment_list, old_paid_amount_list):
    loan_payment = collections.defaultdict(list)
    loan_payments_list = []
    for payment in payment_list:
        if payment.payment_status_id < PaymentStatusCodes.PAID_ON_TIME and \
                old_paid_amount_list['%s_status' % payment.id] >= PaymentStatusCodes.PAID_ON_TIME:
            loan_payment[payment.loan.id].append(payment.id)
    for loan_id in loan_payment.keys():
        loan_payments_list.append({
            'loan_id': loan_id,
            'payment_ids': loan_payment[loan_id]
        })
    return loan_payments_list
