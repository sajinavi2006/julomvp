from builtins import str
from builtins import range
import random
import time

from django.core.management.base import BaseCommand
from django.conf import settings

from ...models import BankVirtualAccount
from ...models import PaymentMethodLookup
from ...banks import BankCodes


def load_dummy_virtual_accounts():

    if BankVirtualAccount.objects.filter(loan=None).count() > 100:
        return

    payment_methods = [
        PaymentMethodLookup.objects.get(code=BankCodes.BCA),
        PaymentMethodLookup.objects.get(code=BankCodes.CIMB_NIAGA)
    ]

    for i in range(1000):
        random_payment_method = random.choice(payment_methods)
        random_va_number = str(int(time.time() * 1000)) + str(random.randint(1000, 9999))
        bva_data = {
            'virtual_account_number': random_va_number,
            'bank_code': random_payment_method
        }
        bva = BankVirtualAccount(**bva_data)
        bva.save()


class Command(BaseCommand):
    help = 'load_dummy_virtual_accounts'

    def handle(self, *args, **options):
        if settings.ENVIRONMENT == 'prod':
            self.stdout.write(self.style.ERROR("Not allowed in prod"))
            return
        load_dummy_virtual_accounts()
        self.stdout.write(self.style.SUCCESS("Successfully loaded VAs to database"))
