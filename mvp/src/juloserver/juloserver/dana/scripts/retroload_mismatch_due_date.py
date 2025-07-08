from juloserver.dana.models import DanaPaymentBill
from juloserver.dana.repayment.services import (
    update_payment_paid_off_status,
    update_account_payment_paid_off_status,
)
from bulk_update.helper import bulk_update
from collections import defaultdict
from juloserver.account_payment.models import AccountPayment
from django.db import transaction
from juloserver.pre.services.pre_logger import create_log
from juloserver.julo.models import Payment, PaymentEvent
from django.db.models import Sum
from datetime import datetime, date
from django.contrib.auth.models import User
from juloserver.pre.models import DjangoShellLog
from juloserver.dana.repayment.services import update_late_fee_amount


def recalculate_account_payment_from_payment(account_payment_ids):
    auth_user = User.objects.filter(email="albert.christian@julofinance.com").last()
    result_id_user = auth_user.id
    updated_django_shell = []

    payments = Payment.objects.filter(account_payment__id__in=account_payment_ids).order_by(
        'account_payment_id'
    )
    current_date_time = datetime.now()
    print('recalculating account_payment_ids from payment')
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
    print('recalculating account_payment_ids to account_payment')
    recalculate_account_payment_update = []

    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids).order_by('id')
    for account_payment in account_payments.iterator():
        payments_calculation = mapping_account_payment_amount[account_payment.id]

        old_due_amount = account_payment.due_amount
        account_payment.udate = current_date_time
        account_payment.due_amount = payments_calculation['total_due_amount']
        account_payment.principal_amount = payments_calculation['total_principal_amount']
        account_payment.interest_amount = payments_calculation['total_interest_amount']
        account_payment.late_fee_amount = payments_calculation['total_late_fee_amount']
        account_payment.paid_amount = payments_calculation['total_paid_amount']
        account_payment.paid_principal = payments_calculation['total_paid_principal']
        account_payment.paid_interest = payments_calculation['total_paid_interest']
        account_payment.paid_late_fee = payments_calculation['total_paid_late_fee']

        history_data = {
            'status_old': account_payment.status,
            'change_reason': 'account payment recalculated',
        }

        if account_payment.due_amount == 0 and account_payment.status_id < 330:
            update_account_payment_paid_off_status(account_payment)
        elif account_payment.due_amount != 0:
            account_payment.get_status_based_on_due_date()

        account_payment.create_account_payment_status_history(history_data)
        recalculate_account_payment_update.append(account_payment)

        djs = DjangoShellLog(
            description="dana_recalculate_account_payment",
            old_data={
                "account_id": account_payment.account_id,
                "account_payment_id": account_payment.id,
                "old_due_amount": old_due_amount,
                "old_status": history_data['status_old'].status_code,
            },
            new_data={
                "account_id": account_payment.account_id,
                "account_payment_id": account_payment.id,
                "new_due_amount": account_payment.due_amount,
                "new_status": account_payment.status.status_code,
            },
            execute_by=result_id_user,
        )
        updated_django_shell.append(djs)

    fields_to_update = [
        'due_amount',
        'principal_amount',
        'interest_amount',
        'late_fee_amount',
        'paid_amount',
        'paid_principal',
        'paid_interest',
        'paid_late_fee',
        'status',
        'udate',
    ]
    bulk_update(recalculate_account_payment_update, update_fields=fields_to_update, batch_size=300)
    DjangoShellLog.objects.bulk_create(updated_django_shell, batch_size=100)
    print('finish recalculating account_payment_ids')


def switch_payment_dana_payment_bill(temp_payment, payment1, payment2, dana_bill1, dana_bill2, djs):
    old_bill1_payment_id = dana_bill1.payment_id
    old_bill2_payment_id = dana_bill2.payment_id
    dana_bill1.update_safely(payment=temp_payment)
    dana_bill2.update_safely(payment=payment1)
    dana_bill1.update_safely(payment=payment2)

    djs.old_data.update(
        {
            "switch_payment_dana_payment_bill": {
                "old_bill1_payment_id": old_bill1_payment_id,
                "old_bill2_payment_id": old_bill2_payment_id,
            }
        }
    )
    djs.new_data.update(
        {
            "switch_payment_dana_payment_bill": {
                "new_bill1_payment_id": dana_bill1.payment_id,
                "new_bill2_payment_id": dana_bill2.payment_id,
            }
        }
    )

    if (
        payment2.due_date == dana_bill1.due_date
        and payment2.late_fee_amount != dana_bill1.late_fee_amount
    ):
        dana_bill1.update_safely(late_fee_amount=payment2.late_fee_amount)
    if (
        payment1.due_date == dana_bill2.due_date
        and payment1.late_fee_amount != dana_bill2.late_fee_amount
    ):
        dana_bill2.update_safely(late_fee_amount=payment1.late_fee_amount)

    if (
        payment2.due_date == dana_bill1.due_date
        and payment2.due_date < date.today()
        and payment2.due_amount != 0
    ):

        count_days = payment2.due_date - date.today()
        count_late_fee = count_days.days
        for _ in range(count_late_fee):
            update_late_fee_amount(payment2.id)
    elif (
        payment1.due_date == dana_bill2.due_date
        and payment1.due_date < date.today()
        and payment1.due_amount != 0
    ):
        count_days = payment1.due_date - date.today()
        count_late_fee = count_days.days
        for _ in range(count_late_fee):
            update_late_fee_amount(payment1.id)
    elif (
        payment2.due_date == dana_bill1.due_date
        and payment2.due_date > date.today()
        and payment2.due_amount != 0
    ):
        payment2.late_fee_amount = 0
        payment2.late_fee_applied = 0
        payment2.paid_amount = (
            payment2.paid_principal + payment2.paid_interest + payment2.paid_late_fee
        )
        payment2.due_amount = (
            payment2.installment_principal
            + payment2.installment_interest
            + payment2.late_fee_amount
        )
        payment2.update_status_based_on_due_date()
        payment2.save(
            update_fields=[
                'payment_status',
                'paid_amount',
                'due_amount',
                'late_fee_amount',
                'late_fee_applied',
            ]
        )
        dana_bill1.update_safely(late_fee_amount=payment2.late_fee_amount)
    elif (
        payment1.due_date == dana_bill2.due_date
        and payment1.due_date > date.today()
        and payment1.due_amount != 0
    ):
        payment1.late_fee_amount = 0
        payment2.late_fee_applied = 0
        payment1.paid_amount = (
            payment1.paid_principal + payment1.paid_interest + payment1.paid_late_fee
        )
        payment1.due_amount = (
            payment1.installment_principal
            + payment1.installment_interest
            + payment1.late_fee_amount
        )
        payment1.update_status_based_on_due_date()
        payment1.save(
            update_fields=[
                'payment_status',
                'paid_amount',
                'due_amount',
                'late_fee_amount',
                'late_fee_applied',
            ]
        )
        dana_bill2.update_safely(late_fee_amount=payment1.late_fee_amount)


def update_and_void_repayment_to_correct_bill(payment2, payment1, lunas=False, djs=None):
    correct_paid_date = payment2.paid_date
    reversed_date = datetime.now()
    reversed_amount = payment2.paid_amount

    payment2.update_safely(
        due_amount=payment1.installment_principal
        + payment1.installment_interest
        + payment1.late_fee_amount,
        paid_amount=payment1.paid_amount,
        paid_principal=payment1.paid_principal,
        paid_interest=payment1.paid_interest,
        paid_late_fee=payment1.paid_late_fee,
        paid_date=payment1.paid_date,
    )

    payment2.update_status_based_on_due_date()
    payment2.save(update_fields=['payment_status'])

    PaymentEvent.objects.create(
        payment=payment2,
        event_payment=-reversed_amount,
        event_due_amount=payment2.due_amount,
        event_date=reversed_date,
        event_type="dana_manual_void_payment",
    )

    payment2.danarepaymentreference_set.all().update(payment=payment1)

    dana_repayment_reference = payment1.danarepaymentreference_set.last()
    drr = payment1.danarepaymentreference_set.filter(
        dana_repayment_status__status='success'
    ).aggregate(
        total_paid_principal=Sum('principal_amount'),
        total_paid_interest=Sum('interest_fee_amount'),
        total_late_fee_amount=Sum('late_fee_amount'),
    )

    old_paid_principal = payment1.paid_principal
    old_paid_interest = payment1.paid_interest
    old_paid_amount = payment1.paid_amount
    old_paid_late_fee = payment1.paid_late_fee
    old_late_fee_amount = payment1.late_fee_amount
    old_due_amount = payment1.due_amount

    payment1.paid_principal = drr.get('total_paid_principal', 0)
    payment1.paid_interest = drr.get('total_paid_interest', 0)
    payment1.paid_late_fee = drr.get('total_late_fee_amount', 0)
    payment1.paid_date = correct_paid_date

    # cek late fee generated
    if payment1.late_fee_amount != payment1.paid_late_fee and lunas:
        payment1.late_fee_amount = payment1.paid_late_fee

    payment1.paid_amount = payment1.paid_principal + payment1.paid_interest + payment1.paid_late_fee
    payment1.due_amount = (
        payment1.installment_principal
        + payment1.installment_interest
        + payment1.late_fee_amount
        - payment1.paid_amount
    )
    update_payment_paid_off_status(payment1)

    payment1.save(
        update_fields=[
            'paid_principal',
            'paid_interest',
            'paid_late_fee',
            'paid_date',
            'paid_amount',
            'due_amount',
            'late_fee_amount',
            'payment_status',
        ]
    )

    PaymentEvent.objects.create(
        payment=payment1,
        event_payment=payment1.paid_amount,
        event_due_amount=payment1.due_amount,
        event_date=payment1.paid_date,
        event_type="manual_payment",
        payment_receipt=dana_repayment_reference.partner_reference_no,
    )

    djs.old_data.update(
        {
            "update_repayment_to_correct_bill": {
                "payment_id": payment1.id,
                "old_late_fee_amount": old_late_fee_amount,
                "old_due_amount": old_due_amount,
                "old_paid_principal": old_paid_principal,
                "old_paid_interest": old_paid_interest,
                "old_paid_late_fee": old_paid_late_fee,
                "old_paid_amount": old_paid_amount,
            }
        }
    )
    djs.new_data.update(
        {
            "update_repayment_to_correct_bill": {
                "payment_id": payment1.id,
                "new_late_fee_amount": payment1.late_fee_amount,
                "new_due_amount": payment1.due_amount,
                "new_paid_principal": payment1.paid_principal,
                "new_paid_interest": payment1.paid_interest,
                "new_paid_late_fee": payment1.late_fee_amount,
                "new_paid_amount": payment1.paid_amount,
            }
        }
    )


def process_switch_dana_payment_bill(payment, dana_payment_bill, temp_payment=None):
    with transaction.atomic():
        if payment.due_date == dana_payment_bill.due_date:
            return None
        payment2 = Payment.objects.get(due_date=dana_payment_bill.due_date, loan_id=payment.loan_id)
        dpb2 = DanaPaymentBill.objects.get(payment_id=payment2.id)
        djs = create_log(
            "albert.christian@julofinance.com",
            "switch_dana_payment_bill",
            {
                "dana_payment_bill_id": dana_payment_bill.id,
                "payment_id": payment.id,
                "dana_payment_bill_id2": dpb2.id,
                "payment_id2": payment2.id,
            },
            {
                "dana_payment_bill_id": dana_payment_bill.id,
                "payment_id": payment.id,
                "dana_payment_bill_id2": dpb2.id,
                "payment_id2": payment2.id,
            },
        )

        if payment2.due_amount == 0 and payment.due_amount != 0:
            # update payment id repayment and add repayment to
            # the correct bill params1, params2 will update repayment to params1
            update_and_void_repayment_to_correct_bill(payment2, payment, lunas=True, djs=djs)
            """
            will switch payment id on dana payment bill
            (temp_payment,payment1,payment2,dana_bill1,dana_bill2)
            dana bill 1 will have payment 2
            dana bill 2 will have payment 1
            """
            switch_payment_dana_payment_bill(
                temp_payment, payment, payment2, dana_payment_bill, dpb2, djs
            )
        elif payment.due_amount == 0 and payment2.due_amount != 0:
            """
            update payment id repayment and add repayment to
            the correct bill input repayment to params2
            """
            update_and_void_repayment_to_correct_bill(payment, payment2, lunas=True, djs=djs)

            """
            will switch payment id on dana payment bill
            (temp_payment,payment1,payment2,dana_bill1,dana_bill2)
            dana bill 1 will have payment 2
            dana bill 2 will have payment 1
            """
            switch_payment_dana_payment_bill(
                temp_payment, payment, payment2, dana_payment_bill, dpb2, djs
            )
        # case when user already repaid both of the payment just need to switch it
        else:
            switch_payment_dana_payment_bill(
                temp_payment, payment, payment2, dana_payment_bill, dpb2, djs
            )

        return payment.account_payment


# call loan_ids in set so it wont be doubled
def retroload_mismatch_due_date(set_loan_ids):
    account_payment_ids = []
    payments = Payment.objects.filter(loan_id=set_loan_ids)
    payment_ids = payments.values_list('id', flat=True)

    dana_payment_bills = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))

    dana_payment_bill_map = {dpb.payment_id: dpb for dpb in dana_payment_bills}

    for payment in payments.iterator():
        dana_payment_bill = dana_payment_bill_map.get(payment.id)
        if dana_payment_bill:
            # case 1 by default will just switch payment
            account_payment = process_switch_dana_payment_bill(payment, dana_payment_bill)
            if account_payment:
                account_payment_ids.append(account_payment.id)

    recalculate_account_payment_from_payment(account_payment_ids)


"""
# define global variable to get unused j1 payment for temperory change
temp_payment = Payment.objects.filter(
    loan__loan_status=216,
    loan__account__application__application_status_id=190,
    loan__account__application__product_line_id=1,
).first()
# set_loan_ids = {3012668225}
"""
