from __future__ import print_function
from pyexcel_xls import get_data

from django.core.management.base import BaseCommand

from ...models import BankVirtualAccount
from ...models import PaymentMethodLookup
from ...models import Loan
from ...banks import BankCodes


def upload_va_to_db(files):

    data = get_data(files)
    niaga_list = data['NIAGA']
    bca_list = data['BCA']

    va_niaga_collection = []
    va_bca_collection = []

    for niaga in niaga_list:
        if niaga_list.index(niaga) > 0:
            if len(niaga) >= 14 and 'move' in niaga[13]:
                pass
            else:
                payment_method_niaga = PaymentMethodLookup.objects.get(code=BankCodes.CIMB_NIAGA)
                va_niaga = niaga[0]
                loan1 = Loan.objects.get_or_none(julo_bank_account_number=va_niaga)

                data_va_niaga = {
                    'virtual_account_number': va_niaga,
                    'bank_code': payment_method_niaga,
                    'loan': loan1,
                }
                print(data_va_niaga)
                niaga_obj = BankVirtualAccount(**data_va_niaga)
                niaga_obj.save()

                va_niaga_collection.append(data_va_niaga)

    for bca in bca_list:
        if bca_list.index(bca) > 0:
            if len(bca) >= 14 and 'move' in bca[13]:
                pass
            else:
                payment_method_bca = PaymentMethodLookup.objects.get(code=BankCodes.BCA)
                va_bca = bca[0]
                loan2 = Loan.objects.get_or_none(julo_bank_account_number=va_bca)

                data_va_bca = { 
                    'virtual_account_number': va_bca,
                    'bank_code': payment_method_bca,
                    'loan': loan2
                }
                print(data_va_bca)
                bca_obj = BankVirtualAccount(**data_va_bca)
                bca_obj.save()

                va_bca_collection.append(data_va_bca)


class Command(BaseCommand):
    help = 'load_va <path/to/excel_file.xlxs'

    def add_arguments(self, parser):
        parser.add_argument('va_excel', nargs='+', type=str)

    def handle(self, *args, **options):
        path = None
        for option in options['va_excel']:
            path = option

        upload_va_to_db(path)

        self.stdout.write(self.style.SUCCESS('Successfully load va to database'))
