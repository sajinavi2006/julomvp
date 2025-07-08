from django.core.management.base import BaseCommand

from juloserver.julo.models import Application, PaymentMethod
from juloserver.julo.statuses import ApplicationStatusCodes


class Command(BaseCommand):
    help = 'Helps to retroload ovo payment method'

    def handle(self, *args, **options):
        application_data_141 = Application.objects.filter(
            account_id__account_lookup_id=1,
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
            ).distinct('customer_id').values_list('customer_id', flat=True)

        for customer_id in application_data_141:
            payment_methods = PaymentMethod.objects.filter(
                payment_method_name='OVO',
                customer_id=customer_id,
                is_shown=True
            )

            if len(payment_methods) >= 1:
                for payment_method in payment_methods:
                    if payment_method == payment_methods[len(payment_methods)-1]:
                        continue
                    payment_method.is_shown=False
                    payment_method.save()
