from __future__ import print_function
from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import Loan, VirtualAccountSuffix, PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import LoanStatusCodes


class Command(BaseCommand):
    help = 'retroactively va permata for all customer'
    CHUNK_SIZE = 2000

    def handle(self, *args, **options):
        payment_methods = PaymentMethod.objects.filter(
            payment_method_code=PaymentMethodCodes.PERMATA1)
        chunk_count_1 = 0
        chunk_count_2 = 0
        chunk_count_3 = 0
        total_count = 0
        old_payment_method_ids_1 = []  # case: 877 is_shown = true and is_primary = true
        old_payment_method_ids_2 = []  # case: 877 is_shown = true and is_primary = false
        old_payment_method_ids_3 = []  # case: customer has only 877, 851 is not exist
        new_payment_method_update_ids_1 = []  # case: 877 is_shown = true and is_primary = true
        new_payment_method_update_ids_2 = []  # case: 877 is_shown = true and is_primary = false
        new_payment_methods = []  # case: customer has only 877, 851 is not exist

        for old_payment_method in payment_methods.iterator():
            customer = old_payment_method.customer
            new_payment_method = PaymentMethod.objects.filter(
                customer=customer,
                payment_method_code=PaymentMethodCodes.PERMATA).last()

            if new_payment_method:
                if old_payment_method.is_shown and old_payment_method.is_primary:
                    old_payment_method_ids_1.append(old_payment_method.id)
                    new_payment_method_update_ids_1.append(new_payment_method.id)
                    chunk_count_1 += 1
                    if chunk_count_1 >= self.CHUNK_SIZE:
                        with transaction.atomic():
                            PaymentMethod.objects.filter(
                                id__in=old_payment_method_ids_1).update(
                                is_shown=False, is_primary=False)
                            PaymentMethod.objects.filter(
                                id__in=new_payment_method_update_ids_1).update(
                                is_shown=True, is_primary=True)
                            total_count += chunk_count_1
                            chunk_count_1 = 0
                            old_payment_method_ids_1 = []
                            new_payment_method_update_ids_1 = []
                elif old_payment_method.is_shown and not old_payment_method.is_primary:
                    old_payment_method_ids_2.append(old_payment_method.id)
                    new_payment_method_update_ids_2.append(new_payment_method.id)
                    chunk_count_2 += 1
                    if chunk_count_2 >= self.CHUNK_SIZE:
                        with transaction.atomic():
                            PaymentMethod.objects.filter(
                                id__in=old_payment_method_ids_2).update(
                                is_shown=False, is_primary=False)
                            PaymentMethod.objects.filter(
                                id__in=new_payment_method_update_ids_2).update(
                                is_shown=True, is_primary=False)
                            total_count += chunk_count_2
                            chunk_count_2 = 0
                            old_payment_method_ids_2 = []
                            new_payment_method_update_ids_2 = []
            else:
                sequences = PaymentMethod.objects.filter(
                    customer=customer,sequence__isnull=False).order_by('-sequence').values('sequence')
                last_sequence = sequences[0]['sequence'] if sequences else None

                permata = PaymentMethodManager.get_or_none(BankCodes.PERMATA)
                old_payment_method_code = PaymentMethodCodes.PERMATA1
                if old_payment_method.virtual_account[0:6] != old_payment_method_code:
                    self.stdout.write(self.style.ERROR(
                        'Old payment method incorrect payment method '
                        'code|old_payment_id={}'.format(old_payment_method.id)))
                    continue
                new_virtual_account = permata.faspay_payment_code + old_payment_method.virtual_account[6::]
                is_primary = old_payment_method.is_primary

                payment_method_data = {
                    'payment_method_code': permata.faspay_payment_code,
                    'payment_method_name': permata.name,
                    'bank_code': BankCodes.PERMATA,
                    'loan': old_payment_method.loan,
                    'is_shown': old_payment_method.is_shown,
                    'is_primary': is_primary,
                    'virtual_account': new_virtual_account,
                    'customer_id': old_payment_method.customer.id if old_payment_method.customer else None,
                    'sequence': last_sequence + 1 if last_sequence else None
                }
                new_payment_method = PaymentMethod(**payment_method_data)
                new_payment_methods.append(new_payment_method)
                old_payment_method_ids_3.append(old_payment_method.id)

                chunk_count_3 += 1
                if chunk_count_3 >= self.CHUNK_SIZE:
                    with transaction.atomic():
                        PaymentMethod.objects.bulk_create(new_payment_methods)
                        PaymentMethod.objects.filter(
                            id__in=old_payment_method_ids_3).update(
                            is_shown=False, is_primary=False)
                        total_count += chunk_count_3
                        chunk_count_3 = 0
                        new_payment_methods = []
                        old_payment_method_ids_3 = []

        # update and create all remain payment_methods
        if new_payment_method_update_ids_1 or old_payment_method_ids_1:
            with transaction.atomic():
                PaymentMethod.objects.filter(
                    id__in=old_payment_method_ids_1).update(
                    is_shown=False, is_primary=False)
                PaymentMethod.objects.filter(
                    id__in=new_payment_method_update_ids_1).update(
                    is_shown=True, is_primary=True)
                total_count += chunk_count_1

        if new_payment_method_update_ids_2 or old_payment_method_ids_2:
            with transaction.atomic():
                PaymentMethod.objects.filter(
                    id__in=old_payment_method_ids_2).update(
                    is_shown=False, is_primary=False)
                PaymentMethod.objects.filter(
                    id__in=new_payment_method_update_ids_2).update(
                    is_shown=True, is_primary=False)
                total_count += chunk_count_2

        if new_payment_methods or old_payment_method_ids_3:
            with transaction.atomic():
                PaymentMethod.objects.bulk_create(new_payment_methods)
                PaymentMethod.objects.filter(
                    id__in=old_payment_method_ids_3).update(
                    is_shown=False, is_primary=False)
                total_count += chunk_count_3
        self.stdout.write(self.style.SUCCESS(
            'success load VA PERMATA as payment method, total count {}'.format(total_count)))

        self.stdout.write(self.style.SUCCESS('Assign VA Done'))
