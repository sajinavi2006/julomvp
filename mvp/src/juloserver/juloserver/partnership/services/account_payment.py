import logging
from typing import List, Union

from juloserver.julo.models import (
    Payment,
    StatusLookup,
)
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.statuses import PaymentStatusCodes

logger = logging.getLogger(__name__)


def create_or_update_account_payments(
    payments: Union[List[int], List[Payment]], account: Account
) -> List[AccountPayment]:
    is_payment_object = True
    for payment in payments:
        if not isinstance(payment, Payment):
            is_payment_object = False
            break

    account_payments = []
    account_payment_status = StatusLookup.objects.get(
        status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
    )
    payment_due_dates = []

    if not is_payment_object:
        payments = Payment.objects.filter(id__in=payments).order_by("payment_number")

    for payment in payments:
        payment_due_dates.append(payment.due_date)

    account_payment_qs = AccountPayment.objects.select_for_update().filter(
        account=account,
        due_date__in=payment_due_dates,
        is_restructured=False,
    )

    account_payment_dict = dict()
    for account_payment in account_payment_qs:
        account_payment_dict[account_payment.due_date] = account_payment

    for payment in payments:
        account_payment = account_payment_dict.get(payment.due_date)

        if not account_payment:
            account_payment = AccountPayment.objects.create(
                account=account,
                late_fee_amount=0,
                due_date=payment.due_date,
                status=account_payment_status,
            )
            account_payment_dict[account_payment.due_date] = account_payment
        else:
            status = account_payment.status.status_code
            if status >= PaymentStatusCodes.PAID_ON_TIME:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'New payment added',
                }
                account_payment.change_status(PaymentStatusCodes.PAYMENT_NOT_DUE)
                account_payment.save(update_fields=['status'])
                account_payment.create_account_payment_status_history(history_data)

        old_acc_payment_due_amount = account_payment.due_amount
        old_acc_payment_principal_amount = account_payment.principal_amount
        old_acc_payment_interest_amount = account_payment.interest_amount

        acc_payment_due_amount = account_payment.due_amount + payment.due_amount
        acc_payment_principal = account_payment.principal_amount + payment.installment_principal
        acc_payment_interest = account_payment.interest_amount + payment.installment_interest

        account_payment.update_safely(
            due_amount=acc_payment_due_amount,
            principal_amount=acc_payment_principal,
            interest_amount=acc_payment_interest,
            due_date=payment.due_date,
        )
        payment.update_safely(account_payment=account_payment)
        account_payments.append(account_payment)

        logger_data = {
            'method': 'dana_loan_create_or_update_account_payments',
            'loan_id': payment.loan_id,
            'account_payment': {
                'id': account_payment.id,
                'old_due_amount': old_acc_payment_due_amount,
                'old_principal_amount': old_acc_payment_principal_amount,
                'old_interest_amount': old_acc_payment_interest_amount,
                'new_due_amount': account_payment.due_amount,
                'new_principal_amount': account_payment.principal_amount,
                'new_interest_amount': account_payment.interest_amount,
            },
            'payment': {
                'id': payment.id,
                'installment_principal': payment.installment_principal,
                'installment_interest': payment.installment_interest,
                'due_date': payment.due_date,
            },
            'message': 'Success update amount to account payment',
        }
        logger.info(logger_data)

    return account_payments
