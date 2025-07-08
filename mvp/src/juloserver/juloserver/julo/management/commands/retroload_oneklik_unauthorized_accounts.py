from django.db.models import Q
from django.core.management.base import BaseCommand
from juloserver.julo.models import PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodCodes


class Command(BaseCommand):
    help = 'Helps to retroload Oneklik is_primary and showing payment methods payment method'

    def handle(self, *args, **options):
        impacted_pm = PaymentMethod.objects.filter(
            (Q(is_primary=True) | Q(bank_code='014'))
            & Q(payment_method_code=PaymentMethodCodes.ONEKLIK_BCA)
        )
        impacted_count = impacted_pm.count()
        self.stdout.write(self.style.SUCCESS(f'Total accounts to update: {impacted_count}'))

        updated_count = impacted_pm.update(
            bank_code=PaymentMethodCodes.ONEKLIK_BCA,
            is_primary=False,
        )

        self.stdout.write(self.style.SUCCESS(f'Success update {impacted_count} accounts'))
