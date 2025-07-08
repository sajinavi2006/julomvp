from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.payment_flow import (
    update_account_payment_paid_off_status,
    update_payment_paid_off_status,
)
from juloserver.julo.constants import PaymentEventConst
from juloserver.julo.models import Payment, PaymentEvent


"""
This scripts is to void the existing payment
impacted:
- payment
- account_payment
- payment_event
- loan

how to call 
force_void_payment(payment_id)
"""


def force_void_payment(payment_id):
    payment = Payment.objects.select_related('loan').filter(id=payment_id).last()
    if not payment:
        print('payment id doesnt exists')
        return

    void_amount = PaymentEvent.objects.filter(
        payment_id=payment_id,
        event_type__in=[PaymentEventConst.PAYMENT, PaymentEventConst.PAYMENT_VOID],
    ).aggregate(amount=Sum('event_payment'))['amount']

    paid_amount = payment.paid_principal + payment.paid_interest + payment.paid_late_fee
    if (
        payment.paid_amount != void_amount
        or paid_amount != void_amount
        or paid_amount != payment.paid_amount
    ):
        print('payment paid amount doesnt match with the payment event amount please check')
        return

    today = timezone.localtime(timezone.now())
    due_amount_before = payment.due_amount
    with transaction.atomic():
        payment.due_amount = (
            payment.installment_principal + payment.installment_interest + payment.late_fee_amount
        )
        payment.paid_principal = 0
        payment.paid_interest = 0
        payment.paid_late_fee = 0
        payment.paid_amount = 0
        payment.udate = today

        if payment.due_amount == 0 and payment.status < 330:
            update_payment_paid_off_status(payment)
        elif payment.due_amount != 0:
            payment.update_status_based_on_due_date()

        payment.save(
            update_fields=[
                'due_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_amount',
                'udate',
                'payment_status_id',
            ]
        )

        PaymentEvent.objects.create(
            payment=payment,
            event_payment=-void_amount,
            event_due_amount=due_amount_before,
            event_date=today,
            event_type=PaymentEventConst.PAYMENT_VOID,
            payment_receipt='manual_by_scripts',
        )

        recalculate_account_payment_from_payment(payment.account_payment_id)

        loan = payment.loan
        loan.udate = today
        loan.update_status()
        loan.save(update_fields=['udate', 'loan_status_id'])


def recalculate_account_payment_from_payment(account_payment_id):
    account_payment = AccountPayment.objects.get(id=account_payment_id)
    payments = Payment.objects.filter(account_payment_id=account_payment_id, is_restructured=False)

    account_payment.due_amount = 0
    account_payment.principal_amount = 0
    account_payment.interest_amount = 0
    account_payment.late_fee_amount = 0
    account_payment.paid_amount = 0
    account_payment.paid_principal = 0
    account_payment.paid_interest = 0
    account_payment.paid_late_fee = 0
    for payment in payments.iterator():
        account_payment.due_amount += payment.due_amount
        account_payment.principal_amount += payment.installment_principal
        account_payment.interest_amount += payment.installment_interest
        account_payment.late_fee_amount += payment.late_fee_amount
        account_payment.paid_amount += payment.paid_amount
        account_payment.paid_principal += payment.paid_principal
        account_payment.paid_interest += payment.paid_interest
        account_payment.paid_late_fee += payment.paid_late_fee

    account_payment.udate = timezone.localtime(timezone.now())
    if account_payment.due_amount == 0 and account_payment.status_id < 330:
        update_account_payment_paid_off_status(account_payment)
    elif account_payment.due_amount != 0:
        new_status = account_payment.get_status_based_on_due_date()
        account_payment.status_id = new_status

    account_payment.save(
        update_fields=[
            'due_amount',
            'principal_amount',
            'interest_amount',
            'late_fee_amount',
            'paid_amount',
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
            'status_id',
            'udate',
        ]
    )
