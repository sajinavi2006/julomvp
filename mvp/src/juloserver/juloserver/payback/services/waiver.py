from builtins import str
import logging

from argparse import Namespace
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction

from juloserver.payback.models import WaiverTemp
from juloserver.payback.models import WaiverPaymentTemp
from juloserver.payback.constants import WaiverConst
from juloserver.julo.constants import PaymentEventConst

from juloserver.julo.models import (PaymentEvent,
                                    PaymentNote,
                                    Payment)
from juloserver.julo.utils import display_rupiah
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.loan_refinancing.models import WaiverPaymentRequest

logger = logging.getLogger(__name__)

# ==========================================
# Waive late fee section
# ==========================================
def get_remaining_late_fee(payment, is_unpaid=False, max_payment_number=0):
    """
    get remaining late fee by calculating waive_late_fee, waive_late_fee_void
    and payment_late_fee amount

    :param payment:
    :return total remaining late fee amount:
    """
    return payment.total_late_fee_by_loan(
        exclude_paid_late=is_unpaid,
        max_payment_number=max_payment_number
    )

def check_any_paid_payment(payment):
    paid_payment = payment.loan.payment_set.all().paid()
    if not paid_payment:
        logger.error({
            'action': 'waive_late_fee_paid',
            'error': 'no payment with status paid off for this loan',
            'payment_id': payment.id,
            'loan_id': payment.loan.id
        })
        message = "Tidak ada payment dengan status paid off untuk loan ini"
        return False, message
    return True, ''


def waive_late_fee_paid(payment, waive_late_fee_amount, note, from_unpaid=False):
    """
    this function for create payment event for waive_late_fee and implemented waiver
    :param payment:
    :param waive_late_fee_amount:
    :param note:
    :return status an message:
    """
    from juloserver.julo.services import process_received_payment, record_payment_transaction

    event_date = timezone.localtime(timezone.now()).date()
    due_amount_before = payment.due_amount
    payment_note = '[Add Event Waive Late Fee]\n\
                    amount: %s,\n\
                    date: %s,\n\
                    note: %s.' % (display_rupiah(waive_late_fee_amount),
                                  event_date.strftime('%d-%m-%Y'),
                                  note)
    logger.info({
        'action': 'waive_late_fee_paid',
        'payment_id': payment.id,
        'waive_late_fee_amount': waive_late_fee_amount,
        'event_date': event_date,
        'due_amount_before': due_amount_before
    })
    try:
        with transaction.atomic():
            payment.due_amount -= waive_late_fee_amount
            payment.paid_amount += waive_late_fee_amount
            payment.save(update_fields=['due_amount',
                                        'paid_amount',
                                        'udate'])

            payment_event = PaymentEvent.objects.create(payment=payment,
                                                        event_payment=waive_late_fee_amount,
                                                        event_due_amount=due_amount_before,
                                                        event_date=event_date,
                                                        event_type='waive_late_fee')

            PaymentNote.objects.create(
                note_text=payment_note,
                payment=payment,
                account_payment=payment.account_payment)

            record_payment_transaction(
                payment, waive_late_fee_amount, due_amount_before, event_date,
                'borrower_bank')

            payment_event.update_safely(can_reverse=False)
            # this code handle case when late fee waived after customer do payment
            payment.refresh_from_db()
            if payment.due_amount == 0:  # change payment status to paid
                payment.paid_date = event_date
                payment.save(update_fields=['paid_date', 'udate'])
                payment.refresh_from_db()
                process_received_payment(payment)


    except JuloException as e:
        logger.info({
            'action': 'waive_late_fee_paid_error',
            'payment_id': payment.id,
            'message': str(e)
        })
    message = "Payment event waive_late_fee success"
    return True, message


def waive_late_fee_unpaid(
        payment, waive_late_fee_amount, note, max_payment_number, waive_validity_date):
    """
    this function for create waiver temporary record which will executed by function
    waive_late_fee_paid when customer do payment
    :param payment:
    :param waive_late_fee_amount:
    :param note:
    :param max_payment_number:
    :param waive_validity_date:
    :return status and message:
    """
    existing_waiver_temp = get_existing_waiver_temp(payment)
    event_date = timezone.localtime(timezone.now()).date()
    total_due_amount = payment.due_amount
    if existing_waiver_temp:
        total_due_amount = existing_waiver_temp.waiver_payment_temp.aggregate(
            Sum('payment__due_amount'))['payment__due_amount__sum'] or 0

    waive_late_fee = waive_late_fee_amount
    if existing_waiver_temp:
        waive_late_fee = existing_waiver_temp.get_waiver_amount(
            "late_fee_waiver_amount", dict(payment=payment)) + waive_late_fee

    waive_interest = 0
    if existing_waiver_temp and existing_waiver_temp.interest_waiver_amt:
        waive_interest = existing_waiver_temp.interest_waiver_amt

    waive_principal = 0
    if existing_waiver_temp and existing_waiver_temp.principal_waiver_amt:
        waive_principal = existing_waiver_temp.principal_waiver_amt

    need_to_pay = total_due_amount - (waive_late_fee + waive_interest + waive_principal)

    data_to_save = dict(
        late_fee_waiver_amt=waive_late_fee_amount,
        need_to_pay=need_to_pay,
        late_fee_waiver_note=note,
        waiver_date=event_date,
        valid_until=waive_validity_date)

    payment_to_save = dict(
        payment=payment,
        late_fee_waiver_amount=waive_late_fee_amount)

    if existing_waiver_temp:
        existing_waiver_temp.update_safely(**data_to_save)
        existing_waiver_temp.waiver_payment_temp_by_payment(payment).update_safely(
            **payment_to_save)
        message = "Payment event waive_late_fee berhasil diubah"
    else:
        waiver_temp = WaiverTemp.objects.create(loan=payment.loan, **data_to_save)
        WaiverPaymentTemp.objects.create(waiver_temp=waiver_temp, **payment_to_save)
        message = "Payment event waive_late_fee berhasil dibuat"
    update_loan_refinancing(payment)
    return True, message
# ==========================================
# End of Waive late fee section
# ==========================================

# ==========================================
# Waive interest section
# ==========================================
def get_remaining_interest(payment, is_unpaid=False, max_payment_number=0):
    """
    get remaining interest by calculating waive_interest, waive_interest_void
    and payment_interest amount

    :param payment:
    :return total remaining interest amount:
    """
    return payment.total_interest_by_loan(
        exclude_paid_late=is_unpaid,
        max_payment_number=max_payment_number
    )

def waive_interest_paid(payment, waive_interest_amount, note, from_unpaid=False):
    """
    this function for create payment event for waive_interest and implemented waiver
    :param payment:
    :param waive_interest_amount:
    :param note:
    :return status an message:
    """
    from juloserver.julo.services import process_received_payment, record_payment_transaction

    event_date = timezone.localtime(timezone.now()).date()
    due_amount_before = payment.due_amount
    payment_note = '[Add Event Waive Interest]\n\
                    amount: %s,\n\
                    date: %s,\n\
                    note: %s.' % (display_rupiah(waive_interest_amount),
                                  event_date.strftime('%d-%m-%Y'),
                                  note)
    logger.info({
        'action': 'waive_interest_paid',
        'payment_id': payment.id,
        'waive_late_fee_amount': waive_interest_amount,
        'event_date': event_date,
        'due_amount_before': due_amount_before
    })
    try:
        with transaction.atomic():
            # change payment
            payment.due_amount -= waive_interest_amount
            payment.paid_amount += waive_interest_amount
            payment.save(update_fields=['due_amount',
                                        'paid_amount',
                                        'udate'])

            # create payment event
            payment_event = PaymentEvent.objects.create(payment=payment,
                                                        event_payment=waive_interest_amount,
                                                        event_due_amount=due_amount_before,
                                                        event_date=event_date,
                                                        event_type='waive_interest')
            # create payment note
            PaymentNote.objects.create(
                note_text=payment_note,
                payment=payment,
                account_payment=payment.account_payment)

            record_payment_transaction(
                payment, waive_interest_amount, due_amount_before, event_date,
                'borrower_bank')

            payment_event.update_safely(can_reverse=False)
            # this code handle case when late fee waived after customer do payment
            payment.refresh_from_db()
            if payment.due_amount == 0:  # change payment status to paid
                payment.paid_date = event_date
                payment.save(update_fields=['paid_date', 'udate'])
                payment.refresh_from_db()
                process_received_payment(payment)
    except JuloException as e:
        logger.info({
            'action': 'waive_interest_paid_error',
            'payment_id': payment.id,
            'message': str(e)
        })
    message = "Payment event waive_interest success"
    return True, message


def waive_interest_unpaid(
        payment, waive_interest_amount, note, max_payment_number, waive_validity_date):
    """
    this function for create waiver temporary record which will executed by function
    waive_interest_paid when customer do payment
    :param payment:
    :param waive_interest_amount:
    :param note:
    :param max_payment_number:
    :param waive_validity_date:
    :return status and message:
    """
    existing_waiver_temp = get_existing_waiver_temp(payment)
    event_date = timezone.localtime(timezone.now()).date()
    total_due_amount = payment.due_amount
    if existing_waiver_temp:
        total_due_amount = existing_waiver_temp.waiver_payment_temp.aggregate(
            Sum('payment__due_amount'))['payment__due_amount__sum'] or 0

    waive_late_fee = 0
    if existing_waiver_temp and existing_waiver_temp.late_fee_waiver_amt:
        waive_late_fee = existing_waiver_temp.late_fee_waiver_amt

    waive_interest = waive_interest_amount
    if existing_waiver_temp:
        waive_interest = existing_waiver_temp.get_waiver_amount(
            "interest_waiver_amount", dict(payment=payment)) + waive_interest

    waive_principal = 0
    if existing_waiver_temp and existing_waiver_temp.principal_waiver_amt:
        waive_principal = existing_waiver_temp.principal_waiver_amt

    need_to_pay = total_due_amount - (waive_late_fee + waive_interest + waive_principal)

    data_to_save = dict(
        interest_waiver_amt=waive_interest_amount,
        need_to_pay=need_to_pay,
        interest_waiver_note=note,
        waiver_date=event_date,
        valid_until=waive_validity_date)

    payment_to_save = dict(
        payment=payment,
        interest_waiver_amount=waive_interest_amount)

    if existing_waiver_temp:
        existing_waiver_temp.update_safely(**data_to_save)
        existing_waiver_temp.waiver_payment_temp_by_payment(payment).update_safely(
            **payment_to_save)
        message = "Payment event waive_interest berhasil diubah"
    else:
        waiver_temp = WaiverTemp.objects.create(loan=payment.loan, **data_to_save)
        WaiverPaymentTemp.objects.create(waiver_temp=waiver_temp, **payment_to_save)
        message = "Payment event waive_interest berhasil dibuat"
    update_loan_refinancing(payment)
    return True, message
# ==========================================
#  end of Waive interest section
# ==========================================

def process_waiver_after_payment(payment, paid_amount, paid_date):
    # This function need to be called inside transaction atomic, since it using select_for_update
    # and will be called when customer do payment

    waiver_temp = WaiverTemp.objects.select_for_update().filter(
        loan=payment.loan, status=WaiverConst.ACTIVE_STATUS).last()
    if not waiver_temp:
        return

    # date validity
    if paid_date > waiver_temp.valid_until:
        return

    payment_need_waive = payment

    all_payments_in_waive_period = PaymentEvent.objects.filter(
        event_type__in=PaymentEventConst.PARTIAL_PAYMENT_TYPES,
        cdate__gte=waiver_temp.cdate,
        event_date__gte=waiver_temp.waiver_date,
        event_date__lte=waiver_temp.valid_until,
        payment__in=payment.loan.payment_set.normal()
    ).aggregate(
        total=Sum('event_payment')
    ).get('total')

    total_paid_amount = all_payments_in_waive_period if all_payments_in_waive_period \
        and all_payments_in_waive_period > 0 else paid_amount

    waive_late_fee_amount = waiver_temp.late_fee_waiver_amt
    waive_interest_amount = waiver_temp.interest_waiver_amt
    waive_principal_amount = waiver_temp.principal_waiver_amt
    total_waive_amount = waive_late_fee_amount + waive_interest_amount + waive_principal_amount

    total_waive_and_pay = total_waive_amount + waiver_temp.need_to_pay
    if total_paid_amount >= total_waive_and_pay:
        waiver_temp.update_safely(status=WaiverConst.EXPIRED_STATUS)
        return

    if total_paid_amount >= waiver_temp.need_to_pay:
        overpaid = total_paid_amount - waiver_temp.need_to_pay
        if overpaid:
            waive_principal_amount = waive_principal_amount - overpaid
            if waive_principal_amount < 0:
                interest_overpaid = abs(waive_principal_amount)
                waive_principal_amount = 0

                waive_interest_amount = waive_interest_amount - interest_overpaid
                if waive_interest_amount < 0:
                    late_fee_overpaid = abs(waive_interest_amount)
                    waive_interest_amount = 0

                    waive_late_fee_amount = waive_late_fee_amount - late_fee_overpaid
                    if waive_late_fee_amount < 0:
                        waive_late_fee_amount = 0

        total_waive_amount = waive_late_fee_amount + waive_interest_amount + waive_principal_amount
        while total_waive_amount > 0:
            # waive late_fee
            payment_need_waive.refresh_from_db()
            if waive_late_fee_amount and payment_need_waive.due_amount > 0:
                if waive_late_fee_amount > payment_need_waive.late_fee_amount:
                    new_waive_late_fee_amount = payment_need_waive.late_fee_amount
                else:
                    new_waive_late_fee_amount = waive_late_fee_amount

                if new_waive_late_fee_amount > payment_need_waive.due_amount:
                    new_waive_late_fee_amount = payment_need_waive.due_amount

                status, message  = waive_late_fee_paid(payment_need_waive,
                                        new_waive_late_fee_amount,
                                        waiver_temp.late_fee_waiver_note,
                                        from_unpaid=True)
                if not status:
                    logger.error({
                        'function': 'process_waiver_after_payment',
                        'action': 'waive_late_fee_amount',
                        'error': message,
                        'payment_id': payment.id,
                        'payment_waive_id': payment_need_waive.id,
                        'total_paid_amount': total_paid_amount,
                        'paid_amount': paid_amount
                    })
                else:
                    waiver_temp.update_safely(status=WaiverConst.IMPLEMENTED_STATUS)
                    waive_late_fee_amount = waive_late_fee_amount - new_waive_late_fee_amount

            # waive interest
            payment_need_waive.refresh_from_db()
            if waive_interest_amount and payment_need_waive.due_amount > 0:
                if waive_interest_amount > payment_need_waive.installment_interest:
                    new_waive_interest_amount = payment_need_waive.installment_interest
                else:
                    new_waive_interest_amount = waive_interest_amount

                if new_waive_interest_amount > payment_need_waive.due_amount:
                    new_waive_interest_amount = payment_need_waive.due_amount

                status, message  = waive_interest_paid(payment_need_waive,
                                        new_waive_interest_amount,
                                        waiver_temp.late_fee_waiver_note,
                                        from_unpaid=True)
                if not status:
                    logger.error({
                        'function': 'process_waiver_after_payment',
                        'action': 'waive_interest_amount',
                        'error': message,
                        'payment_id': payment.id,
                        'payment_waive_id': payment_need_waive.id,
                        'total_paid_amount': total_paid_amount,
                        'paid_amount': paid_amount
                    })
                else:
                    waiver_temp.update_safely(status=WaiverConst.IMPLEMENTED_STATUS)
                    waive_interest_amount = waive_interest_amount - new_waive_interest_amount

            # waive principal
            payment_need_waive.refresh_from_db()
            if waive_principal_amount and payment_need_waive.due_amount > 0:
                if waive_principal_amount > payment_need_waive.installment_principal:
                    new_waive_principal_amount = payment_need_waive.installment_principal
                else:
                    new_waive_principal_amount = waive_principal_amount

                if new_waive_principal_amount > payment_need_waive.due_amount:
                    new_waive_principal_amount = payment_need_waive.due_amount

                status, message  = waive_principal_paid(payment_need_waive,
                                        new_waive_principal_amount,
                                        waiver_temp.late_fee_waiver_note,
                                        from_unpaid=True,
                                        paid_date=paid_date)
                if not status:
                    logger.error({
                        'function': 'process_waiver_after_payment',
                        'action': 'waive_principal_amount',
                        'error': message,
                        'payment_id': payment.id,
                        'payment_waive_id': payment_need_waive.id,
                        'total_paid_amount': total_paid_amount,
                        'paid_amount': paid_amount
                    })
                else:
                    waiver_temp.update_safely(status=WaiverConst.IMPLEMENTED_STATUS)
                    waive_principal_amount = waive_principal_amount - new_waive_principal_amount

            new_payment = Payment.objects.filter(loan=payment.loan).not_paid_active().first()
            if new_payment:
                total_waive_amount = \
                    waive_late_fee_amount + waive_interest_amount + waive_principal_amount
                if new_payment.id != payment_need_waive.id:
                    payment_need_waive = new_payment
                elif new_payment.id == payment_need_waive.id and total_waive_amount > 0:
                    waive_principal_amount = total_waive_amount
                    waive_late_fee_amount = 0
                    waive_interest_amount = 0
            else:
                total_waive_amount = 0


def get_existing_waiver_temp(payment, status=WaiverConst.ACTIVE_STATUS):
    waiver_payment_temp_dict = dict(
        waiver_temp__loan=payment.loan,
        payment=payment,
    )
    if status:
        waiver_payment_temp_dict["waiver_temp__status"] = status

    waiver_payment_temp = WaiverPaymentTemp.objects.filter(**waiver_payment_temp_dict).last()

    if waiver_payment_temp:
        return waiver_payment_temp.waiver_temp

    return None


def update_loan_refinancing(payment):
    from juloserver.loan_refinancing.services.loan_related import \
        loan_refinancing_request_update_waiver
    loan_refinancing_request_update_waiver(payment)


def process_waiver_before_payment(payment, paid_amount, paid_date):
    from juloserver.julo.services2.payment_event import PaymentEventServices
    # This function need to be called inside transaction atomic, since it using select_for_update
    # and will be called when customer do payment
    do_reversal = False
    waiver_temp = WaiverTemp.objects.select_for_update().filter(
        loan=payment.loan, status=WaiverConst.ACTIVE_STATUS).last()
    if not waiver_temp:
        return

    # date validity
    if paid_date > waiver_temp.valid_until:
        return

    # process multiple payment ptp
    process_multiple_payment_ptp(waiver_temp.waiver_request, paid_amount, paid_date)

    # get partial payments
    payments_in_waive_period = get_partial_payments(
        payment.loan.payment_set.normal(), waiver_temp.cdate,
        waiver_temp.waiver_date, waiver_temp.valid_until)

    total_paid_amount = paid_amount
    if payments_in_waive_period > 0:
        total_paid_amount = payments_in_waive_period + paid_amount

    if total_paid_amount < waiver_temp.need_to_pay:
        return

    # handle for need_to_pay amount from partial payments
    if total_paid_amount != paid_amount:
        do_reversal = True
        payment_events = PaymentEvent.objects.filter(
            event_type="payment",
            cdate__gte=waiver_temp.cdate,
            event_date__gte=waiver_temp.waiver_date,
            event_date__lte=waiver_temp.valid_until,
            payment__in=payment.loan.payment_set.normal()
        ).order_by('-id')

        payment_event_service = PaymentEventServices()
        note = "partial payment waiver"
        payment_event_voids = dict()
        max_cdate = timezone.localtime(timezone.now())
        for payment_event in payment_events:
            payment_void = PaymentEvent.objects.filter(
                event_type="payment_void",
                cdate__gte=payment_event.cdate,
                cdate__lte=max_cdate,
                payment=payment_event.payment,
                event_payment=(payment_event.event_payment * -1)
            ).first()
            if not payment_void:
                result, payment_event_void = payment_event_service\
                    .process_reversal_event_type_payment(payment_event, note)
                payment_event_voids[payment_event.id] = payment_event_void

    # allocate waiver amount
    waiver_payments = waiver_temp.waiverpaymenttemp_set.order_by("payment__payment_number")
    for waiver_payment in waiver_payments:
        waiver_types = ("late_fee", "interest", "principal")
        waiver_dict = {
            'late_fee': Namespace(**{
                'amount': waiver_payment.late_fee_waiver_amount,
                'note': waiver_temp.late_fee_waiver_note,
                'action': waive_late_fee_paid,
            }),
            'interest': Namespace(**{
                'amount': waiver_payment.interest_waiver_amount,
                'note': waiver_temp.interest_waiver_note,
                'action': waive_interest_paid,
            }),
            'principal': Namespace(**{
                'amount': waiver_payment.principal_waiver_amount,
                'note': waiver_temp.principal_waiver_note,
                'action': waive_principal_paid,
            }),
        }
        for waiver_type in waiver_types:
            with transaction.atomic():
                waiver_amount = waiver_dict[waiver_type].amount
                if waiver_amount and waiver_amount > 0:
                    waiver_dict[waiver_type].action(
                        waiver_payment.payment, waiver_amount,
                        waiver_dict[waiver_type].note, from_unpaid=True)

    # bring back payment_event that reversed
    if do_reversal:
        with transaction.atomic():
            for payment_event in payment_events.order_by('id'):
                if payment_event.id not in payment_event_voids:
                    continue

                data = dict(
                    paid_date=str(payment_event.event_date.strftime("%d-%m-%Y")),
                    notes="waiver payment event",
                    payment_method_id=payment_event.payment_method_id,
                    payment_receipt=payment_event.payment_receipt,
                    use_credits='false',
                    partial_payment=str(payment_event.event_payment),
                )
                reversal_payment_event_id = payment_event_voids[payment_event.id].id
                payment_event_service.process_event_type_payment(
                    payment_event.payment, data,
                    reversal_payment_event_id=reversal_payment_event_id, with_waiver=False)

    waiver_temp.update_safely(status=WaiverConst.IMPLEMENTED_STATUS)


def get_partial_payments(payments, create_date, event_date_start, event_date_end):
    return PaymentEvent.objects.filter(
        event_type__in=PaymentEventConst.PARTIAL_PAYMENT_TYPES,
        cdate__gte=create_date,
        event_date__gte=event_date_start,
        event_date__lte=event_date_end,
        payment__in=payments
    ).aggregate(
        total=Sum('event_payment')
    ).get('total') or 0


def get_existing_waiver_request(payment):
    waiver_payment_request = WaiverPaymentRequest.objects.filter(
        waiver_request__loan=payment.loan,
        waiver_request__waiver_validity_date__gte=timezone.localtime(timezone.now()).date(),
        payment=payment,
    ).last()

    if waiver_payment_request:
        return waiver_payment_request.waiver_request

    return None


def automate_late_fee_waiver(payment, late_fee_amount, event_date):
    waiver_temp = get_existing_waiver_temp(payment)
    if waiver_temp:
        waiver_request = waiver_temp.waiver_request
        if not waiver_request:
            return

    else:
        waiver_request = get_existing_waiver_request(payment)
        if not waiver_request:
            return

    waiver_approval = waiver_request.waiverapproval_set.last()
    if not waiver_approval:
        waiver_approval = waiver_request

    if not waiver_temp and waiver_approval != waiver_request:
        waiver_approval.approved_waiver_amount += late_fee_amount
        waiver_approval.save()

        waiver_request.outstanding_amount += late_fee_amount
        waiver_request.unpaid_late_fee += late_fee_amount
        waiver_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_request.requested_waiver_amount += late_fee_amount
        if waiver_request.final_approved_waiver_amount:
            waiver_request.final_approved_waiver_amount += late_fee_amount
        waiver_request.save()

        waiver_payment_approval = waiver_approval.waiver_payment_approval.filter(
            payment=payment, account_payment=None).last()
        waiver_payment_approval.approved_late_fee_waiver_amount += late_fee_amount
        waiver_payment_approval.total_approved_waiver_amount += late_fee_amount
        waiver_payment_approval.save()
        return

    if not waiver_temp:
        waiver_request.outstanding_amount += late_fee_amount
        waiver_request.unpaid_late_fee += late_fee_amount
        waiver_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_request.requested_waiver_amount += late_fee_amount
        if waiver_request.final_approved_waiver_amount:
            waiver_request.final_approved_waiver_amount += late_fee_amount
        waiver_request.save()

        waiver_payment_request = waiver_request.waiver_payment_request.filter(
            payment=payment, account_payment=None).last()
        waiver_payment_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_payment_request.total_requested_waiver_amount += late_fee_amount
        waiver_payment_request.save()
        return

    if waiver_temp.status == WaiverConst.ACTIVE_STATUS:
        note = ("Original Late Fee Waiver Amount: {}; "\
                "New Accrued Late Fee Waiver Amount After Request: {}").format(
                    waiver_approval.total_approved_late_fee_waiver,
                    waiver_temp.late_fee_waiver_amt + late_fee_amount,
                )
        new_waived_amount = waiver_temp.waiver_payment_temp_by_payment(
            payment).late_fee_waiver_amount + late_fee_amount
        waive_late_fee_unpaid(
            payment, new_waived_amount, note, None, waiver_temp.valid_until)
        return

    if waiver_temp.status == WaiverConst.IMPLEMENTED_STATUS and \
            event_date <= waiver_temp.valid_until:
        waive_late_fee_paid(
            payment, late_fee_amount,
            "Automated waive_late_fee due to implemented waiver",
            from_unpaid=False
        )
        return


def process_multiple_payment_ptp(waiver_request, paid_amount, paid_date):
    if not waiver_request:
        return

    if not waiver_request.multiple_payment_ptp:
        return

    for payment_ptp in waiver_request.unpaid_multiple_payment_ptp():
        if paid_amount <= 0:
            break

        if paid_amount >= payment_ptp.remaining_amount:
            payment_ptp.paid_amount = payment_ptp.promised_payment_amount
            payment_ptp.is_fully_paid = True
            paid_amount -= payment_ptp.remaining_amount

        else:
            payment_ptp.paid_amount += paid_amount
            paid_amount = 0

        payment_ptp.remaining_amount = payment_ptp.promised_payment_amount - payment_ptp.paid_amount
        payment_ptp.paid_date = paid_date
        payment_ptp.save()


# ==========================================
# Waive principal section
# ==========================================
def get_remaining_principal(payment, is_unpaid=False, max_payment_number=0):
    """
    get remaining interest by calculating waive_principal, waive_principal_void
    and payment_interest amount

    :param payment:
    :return total remaining interest amount:
    """
    return payment.total_principal_by_loan(
        exclude_paid_late=is_unpaid,
        max_payment_number=max_payment_number
    )

def waive_principal_paid(payment, waive_principal_amount, note, from_unpaid=False, paid_date=None):
    """
    this function for create payment event for waive_principal and implemented waiver
    :param payment:
    :param waive_principal_amount:
    :param note:
    :return status an message:
    """
    from juloserver.julo.services import process_received_payment, record_payment_transaction

    event_date = timezone.localtime(timezone.now()).date()
    due_amount_before = payment.due_amount
    payment_note = '[Add Event Waive Principal]\n\
                    amount: %s,\n\
                    date: %s,\n\
                    note: %s.' % (display_rupiah(waive_principal_amount),
                                  event_date.strftime('%d-%m-%Y'),
                                  note)
    logger.info({
        'action': 'waive_principal_paid',
        'payment_id': payment.id,
        'waive_late_fee_amount': waive_principal_amount,
        'event_date': event_date,
        'due_amount_before': due_amount_before
    })
    try:
        with transaction.atomic():
            # change payment
            payment.due_amount -= waive_principal_amount
            payment.paid_amount += waive_principal_amount
            payment.save(update_fields=['due_amount',
                                        'paid_amount',
                                        'udate'])

            # create payment event
            payment_event = PaymentEvent.objects.create(payment=payment,
                                                        event_payment=waive_principal_amount,
                                                        event_due_amount=due_amount_before,
                                                        event_date=event_date,
                                                        event_type='waive_principal')
            # create payment note
            PaymentNote.objects.create(
                note_text=payment_note,
                payment=payment,
                account_payment=payment.account_payment)

            record_payment_transaction(
                payment, waive_principal_amount, due_amount_before, event_date,
                'borrower_bank')

            payment_event.update_safely(can_reverse=False)
            # this code handle case when late fee waived after customer do payment
            payment.refresh_from_db()
            if payment.due_amount == 0:  # change payment status to paid
                if paid_date:
                    payment.paid_date = paid_date
                    payment.save(update_fields=['paid_date', 'udate'])
                    payment.refresh_from_db()
                process_received_payment(payment)
    except JuloException as e:
        logger.info({
            'action': 'waive_principal_paid_error',
            'payment_id': payment.id,
            'message': str(e)
        })
    message = "Payment event waive_interest success"
    return True, message


def waive_principal_unpaid(
        payment, waive_principal_amount, note, max_payment_number, waive_validity_date):
    """
    this function for create waiver temporary record which will executed by function
    waive_principal_paid when customer do payment
    :param payment:
    :param waive_principal_amount:
    :param note:
    :param max_payment_number:
    :param waive_validity_date:
    :return status and message:
    """
    existing_waiver_temp = get_existing_waiver_temp(payment)
    event_date = timezone.localtime(timezone.now()).date()
    total_due_amount = payment.due_amount
    if existing_waiver_temp:
        total_due_amount = existing_waiver_temp.waiver_payment_temp.aggregate(
            Sum('payment__due_amount'))['payment__due_amount__sum'] or 0

    waive_late_fee = 0
    if existing_waiver_temp and existing_waiver_temp.late_fee_waiver_amt:
        waive_late_fee = existing_waiver_temp.late_fee_waiver_amt

    waive_interest = 0
    if existing_waiver_temp and existing_waiver_temp.interest_waiver_amt:
        waive_interest = existing_waiver_temp.interest_waiver_amt

    waive_principal = waive_principal_amount
    if existing_waiver_temp:
        waive_principal = existing_waiver_temp.get_waiver_amount(
            "principal_waiver_amount", dict(payment=payment)) + waive_principal

    need_to_pay = total_due_amount - (waive_late_fee + waive_interest + waive_principal)

    data_to_save = dict(
        principal_waiver_amt=waive_principal_amount,
        need_to_pay=need_to_pay,
        principal_waiver_note=note,
        waiver_date=event_date,
        valid_until=waive_validity_date)

    payment_to_save = dict(
        payment=payment,
        principal_waiver_amount=waive_principal_amount)

    if existing_waiver_temp:
        existing_waiver_temp.update_safely(**data_to_save)
        existing_waiver_temp.waiver_payment_temp_by_payment(payment).update_safely(
            **payment_to_save)
        message = "Payment event waive_principal berhasil diubah"
    else:
        waiver_temp = WaiverTemp.objects.create(loan=payment.loan, **data_to_save)
        WaiverPaymentTemp.objects.create(waiver_temp=waiver_temp, **payment_to_save)
        message = "Payment event waive_principal berhasil dibuat"
    update_loan_refinancing(payment)
    return True, message
# ==========================================
#  end of Waive principal section
# ==========================================
