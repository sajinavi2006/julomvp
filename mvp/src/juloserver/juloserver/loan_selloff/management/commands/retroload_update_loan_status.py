from django.core.management.base import BaseCommand

from juloserver.julo.models import Application, Loan, StatusLookup, PaymentEvent
from django.utils import timezone


class Command(BaseCommand):
    help = 'retroload_update_loan_status'

    def handle(self, *args, **options):

        application_xids = [
            3373943595, 3483219316, 1708924721, 7568518791, 2675858272, 9957622287,
            3503426603, 1441132160, 8561240379, 4897402531, 8371046472, 3137380148,
            4803303675, 6781696129, 1646357583, 3126851030, 7353586220, 1028412937,
            2634455413, 5812361026, 3753072636, 2053385896, 4251282861, 1545653617
        ]

        loan_status = StatusLookup.objects.get(status_code=StatusLookup.PAID_OFF_CODE)

        payment_status = StatusLookup.objects.get(status_code=StatusLookup.PAID_LATE_CODE)

        for app_xid in application_xids:

            app = Application.objects.get(application_xid=app_xid)
            loan = app.loan
            loan.update_safely(loan_status=loan_status)

            payments = loan.payment_set.filter(payment_status__lt=StatusLookup.PAID_ON_TIME_CODE)

            for payment in payments:
                payment.payment_status = payment_status
                payment.paid_amount += payment.due_amount
                if payment.due_amount:

                    late_fee_amount = payment.due_amount
                    check_next_step = False

                    if payment.due_amount > payment.late_fee_amount:
                        late_fee_amount = payment.late_fee_amount
                        check_next_step = True
                        remaining_due_amount = payment.due_amount - payment.late_fee_amount

                    PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=late_fee_amount,
                        event_due_amount=payment.due_amount,
                        event_date=timezone.localtime(timezone.now()).date(),
                        event_type='waive_late_fee'
                    )

                    if check_next_step and payment.installment_interest:
                        check_next_step = False
                        instalment_interest_amount = remaining_due_amount
                        if remaining_due_amount > payment.installment_interest:
                            instalment_interest_amount = payment.installment_interest
                            check_next_step = True
                            remaining_due_amount = payment.due_amount - payment.installment_interest

                        PaymentEvent.objects.create(
                            payment=payment,
                            event_payment=instalment_interest_amount,
                            event_due_amount=payment.due_amount - late_fee_amount,
                            event_date=timezone.localtime(timezone.now()).date(),
                            event_type='waive_interest'
                        )

                    if check_next_step:
                        PaymentEvent.objects.create(
                            payment=payment,
                            event_payment=remaining_due_amount,
                            event_due_amount=payment.due_amount - (late_fee_amount + instalment_interest_amount),
                            event_date=timezone.localtime(timezone.now()).date(),
                            event_type='payment'
                        )

                    payment.due_amount = 0

                if payment.paid_interest != payment.installment_interest:
                    payment.paid_interest = payment.installment_interest

                if payment.paid_late_fee != payment.late_fee_amount:
                    payment.paid_late_fee = payment.late_fee_amount

                if payment.paid_principal != payment.installment_principal:
                    payment.paid_principal = payment.installment_principal

                payment.paid_date = timezone.localtime(timezone.now()).date()

                payment.save()

        self.stdout.write(self.style.SUCCESS('Successfully updated the loan status'))
