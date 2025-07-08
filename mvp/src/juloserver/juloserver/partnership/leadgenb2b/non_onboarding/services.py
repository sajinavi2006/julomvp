from juloserver.julo.models import Payment
from juloserver.account_payment.services.account_payment_related import (
    get_payment_status,
)
from juloserver.payment_point.constants import (
    TransactionMethodCode,
)
from juloserver.partnership.utils import date_format_to_localtime
from juloserver.partnership.constants import DateFormatString
from juloserver.partnership.leadgenb2b.non_onboarding.utils import (
    mapping_status_payment,
)


def get_list_loan_by_account_payment(account_payment_id):
    payment_query_set = Payment.objects.filter(account_payment_id=account_payment_id)
    payment_query_set = payment_query_set.not_paid()
    loan_ids = payment_query_set.values_list('loan', flat=True).distinct('loan_id')
    payments = (
        Payment.objects.select_related('loan')
        .only(
            'id',
            'payment_number',
            'installment_principal',
            'installment_interest',
            'paid_amount',
            'late_fee_amount',
            'due_date',
            'paid_date',
            'payment_status_id',
            'account_payment_id',
            'due_amount',
            'loan_id',
            'loan__fund_transfer_ts',
            'loan__loan_xid',
            'loan__loan_amount',
            'loan__loan_status_id',
        )
        .filter(loan_id__in=loan_ids, account_payment_id=account_payment_id)
        .order_by('loan_id', 'payment_number')
    )

    loan_data = []
    for payment in payments.iterator():

        installment_number = '{}/{}'.format(payment.payment_number, payment.loan.loan_duration)

        installment_amount = (
            payment.installment_principal + payment.installment_interest + payment.late_fee_amount
        )
        if payment.loan.transaction_method.id == TransactionMethodCode.SELF.code:
            payment_status = get_payment_status(
                payment.payment_status_id,
                payment.due_date,
                payment.paid_date,
            )
            if payment_status == "Terlambat":
                payment_status = payment_status.upper()
            loan_data.append(
                {
                    "paymentId": payment.id,
                    "xid": payment.loan.loan_xid,
                    "transactionDate": date_format_to_localtime(
                        payment.loan.cdate, DateFormatString.DATE_WITH_TIME
                    ),
                    "installmentNumber": installment_number,
                    "installmentAmount": installment_amount,
                    "paidInstallmentAmount": payment.paid_amount,
                    "remainingInstallmentAmount": payment.due_amount,
                    "transactionStatus": mapping_status_payment(payment.status),
                }
            )

    return loan_data
