from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.dana.models import DanaCustomerData
from juloserver.pusdafil.tasks import (
    bunch_of_loan_creation_tasks,
    task_report_new_loan_payment_creation,
)


def retry_send_data_to_pusdafil() -> None:
    dana_customer_list = DanaCustomerData.objects.select_related('customer').values_list(
        'customer__user__id',
        'customer_id',
        'application_id',
        'customer__application__application_status',
        'customer__loan__id',
        'customer__loan__loan_status',
        'customer__loan__payment__id',
        'customer__loan__payment__payment_status',
        'customer__loan__payment__due_amount',
    )

    counter = 0

    for dana_customer_tuple in dana_customer_list.iterator():
        (
            user_id,
            customer_id,
            application_id,
            application_status,
            loan_id,
            loan_status,
            payment_id,
            payment_status,
            payment_due_amount,
        ) = dana_customer_tuple

        if not loan_status:
            continue
        if loan_status < LoanStatusCodes.CURRENT:
            continue

        if not application_status:
            continue

        if application_status not in {
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            ApplicationStatusCodes.LOC_APPROVED,
        }:
            continue

        if not payment_id:
            continue

        if (
            payment_status < PaymentStatusCodes.PAID_ON_TIME
            or payment_status > PaymentStatusCodes.PAID_LATE
            or payment_due_amount > 0
        ):
            continue

        counter += 1
        print(
            "{} - Starting process of sending Customer {} data to pusdafil".format(
                counter, customer_id
            )
        )
        bunch_of_loan_creation_tasks.delay(
            user_id=user_id,
            customer_id=customer_id,
            application_id=application_id,
            loan_id=loan_id,
        )

        task_report_new_loan_payment_creation.delay(payment_id=payment_id)
        print("{} - Customer {} successfuly sent to pusdafil".format(counter, customer_id))
