from django.core.management.base import BaseCommand

from juloserver.julo.models import (
    Payment,
    Partner,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.promo.models import WaivePromo


class Command(BaseCommand):
    help = 'insert data h-1 before pede promo to waive promo table'

    def handle(self, *args, **options):
        partner = Partner.objects.get(name='pede')
        pede_payments = Payment.objects.filter(
            payment_status_id__gte=PaymentStatusCodes.PAYMENT_30DPD,
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            loan__application__partner=partner)

        payment_arr = []

        for payment in pede_payments:
            data = WaivePromo(
                loan_id=payment.loan_id,
                payment_id=payment.id,
                remaining_installment_principal=payment.remaining_principal,
                remaining_installment_interest=payment.remaining_interest,
                remaining_late_fee=payment.remaining_late_fee,
                promo_event_type='pede_oct')

            payment_arr.append(data)

        WaivePromo.objects.bulk_create(payment_arr)

        self.stdout.write(self.style.SUCCESS('Successfully load data to waive promo table'))
