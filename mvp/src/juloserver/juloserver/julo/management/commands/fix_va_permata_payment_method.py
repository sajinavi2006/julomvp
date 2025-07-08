from __future__ import print_function
import base64
import csv
import os

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from ...banks import BankCodes
from ...payment_methods import PaymentMethodCodes, PaymentMethodManager
from ...models import PaymentMethod


class Command(BaseCommand):
    help = 'fix_va_permata_payment_method'


    def handle(self, *args, **options):
        permatas = PaymentMethod.objects.filter(bank_code=BankCodes.PERMATA)

        for permata in permatas:
            if permata.payment_method_code != PaymentMethodCodes.PERMATA:
                old_method_code = permata.payment_method_code
                new_method_code = PaymentMethodCodes.PERMATA
                permata.payment_method_code = PaymentMethodCodes.PERMATA
                permata.save()

                print('successfully change payment_method_code {} from {} to {}'.format(
                    permata.payment_method_name, old_method_code, new_method_code))

        self.stdout.write(self.style.SUCCESS(
            'Successfully fix all va PERMATA'))