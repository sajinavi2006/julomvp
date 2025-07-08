from django.core.management.base import BaseCommand
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import Application
from juloserver.julo.models import PaymentMethod
from juloserver.ovo.constants import OvoConst


class Command(BaseCommand):
    help = 'Helps to retroload ovo payment method'

    def handle(self, *args, **options):
        payment_method = PaymentMethod.objects.filter(
            payment_method_name='Ovo'
        ).update(
            payment_method_name='OVO',
            payment_method_code=OvoConst.PAYMENT_METHOD_CODE,
            is_shown=True,
            is_primary=False,
            is_preferred=False
        )

        application_data_141 = Application.objects.filter(
            account_id__account_lookup_id=1,
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
            ).distinct('customer_id').values_list('customer_id', flat=True)

        for customer_id in application_data_141:
            payment_method = PaymentMethod.objects.filter(
                payment_method_name='OVO',
                customer_id=customer_id
            )

            if not payment_method:
                PaymentMethod.objects.create(
                    payment_method_code=OvoConst.PAYMENT_METHOD_CODE,
                    payment_method_name='OVO',
                    customer_id=customer_id,
                    is_shown=True,
                    is_primary=False,
                    is_preferred=False
                )
