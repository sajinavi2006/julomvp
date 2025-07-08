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
    help = 'fix_va_indomaret'


    def handle(self, *args, **options):
        indomarets = PaymentMethod.objects.filter(payment_method_code='319237')

        self.stdout.write(self.style.WARNING(
            '===== Fix VA Indomaret BEGIN : %s va' % (len(indomarets))))

        for indomaret in indomarets:
            old_method_code = indomaret.payment_method_code
            new_method_code = PaymentMethodCodes.INDOMARET
            indomaret.payment_method_code = PaymentMethodCodes.INDOMARET
            old_va_number = indomaret.virtual_account
            va_suffix = old_va_number[6:len(old_va_number)]
            new_va_number = '{}{}'.format(PaymentMethodCodes.INDOMARET, va_suffix)
            indomaret.virtual_account = new_va_number
            indomaret.save()

            print('successfully change va indomaret with suffix {} from {} to {}'.format(
                va_suffix, old_va_number, new_va_number))

        self.stdout.write(self.style.SUCCESS(
            'Successfully fix all va INDOMARET'))