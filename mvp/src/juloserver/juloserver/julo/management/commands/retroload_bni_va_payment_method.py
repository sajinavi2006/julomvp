import math
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import (
    PaymentMethod,
    BniVirtualAccountSuffix,
)
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import populate_bni_virtual_account_suffix
from juloserver.julo.statuses import JuloOneCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Customer
from django.db.models import Q
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.integapiv1.tasks import create_va_snap_bni_transaction_retroload


class Command(BaseCommand):
    help = 'Helps to retroload bni va payment method'

    def add_arguments(self, parser):
        parser.add_argument("--customer_ids", nargs="+", type=int)
        parser.add_argument("--suffix_numbers", nargs="+", type=int)

    def handle(self, *args, **options):
        if options["customer_ids"] is None:
            confirmation = input("You want to retroload all application. Are you sure? (Y/N): ")

            if confirmation.lower() == 'y':

                self.stdout.write(
                    self.style.SUCCESS("Retroloading payment method for all customers...")
                )
            else:
                self.stdout.write(self.style.WARNING("Command aborted."))
                return

        else:
            if options["suffix_numbers"] is None:
                confirmation = input(
                    "You want to retroload without --suffix_numbers for a specific customers. Are you sure? (Y/N): "
                )

                if confirmation.lower() == 'y':
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Retroloading payment method for specific customer without suffix number"
                        )
                    )
                else:
                    self.stdout.write(self.style.WARNING("Command aborted."))
                    return

        self.retoload_new_bni_payment_method(options['customer_ids'], options['suffix_numbers'])

    def retoload_new_bni_payment_method(self, customer_ids: list, suffix_numbers: list):

        julo_one_query = Q(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE) & Q(
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )
        julo_turbo_query = Q(
            account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
        ) & Q(application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)

        eligible_product_line_codes = [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]
        customers = Customer.objects.filter(
            (julo_one_query | julo_turbo_query) & Q(product_line__in=eligible_product_line_codes)
        )
        if customer_ids:
            customers = customers.filter(id__in=customer_ids)

        batch_size = 1000
        customer_size = customers.count()

        if suffix_numbers and customer_size > len(suffix_numbers):
            self.stdout.write(
                self.style.WARNING(
                    "Failed to process customers due to lack of suffix numbers. Got valid customers ({}) with suffix_numbers ({})".format(
                        customer_size, len(suffix_numbers)
                    )
                )
            )
            return

        batch_num = math.ceil(customer_size / batch_size)
        progress_count = 0
        try:

            self.stdout.write(self.style.SUCCESS("Starting Batch Process"))
            for i in range(batch_num):
                start_index = i * batch_size
                end_index = (i + 1) * batch_size
                customer_batch = customers[start_index:end_index]

                if not customer_batch.exists():
                    # stop creating
                    break

                payment_method_data_bni = []
                for customer in customer_batch:

                    account = customer.account_set.last()

                    if account.status_id >= JuloOneCodes.SUSPENDED:
                        continue

                    payment_method_bni = PaymentMethod.objects.filter(
                        payment_method_name='Bank BNI', customer_id=customer.id
                    )

                    if not payment_method_bni.exists():
                        populate_bni_virtual_account_suffix()
                        with transaction.atomic(using='repayment_db'):
                            bni_va_suffix_obj = (
                                BniVirtualAccountSuffix.objects.select_for_update()
                                .filter(account_id=None)
                            )

                            # select suffix
                            if suffix_numbers:
                                selected_suffix = str(suffix_numbers.pop(0))
                                bni_va_suffix_obj = bni_va_suffix_obj.filter(
                                    bni_virtual_account_suffix=selected_suffix
                                )

                            bni_va_suffix_obj = bni_va_suffix_obj.order_by('id').first()

                            if not bni_va_suffix_obj:
                                continue

                            bni_va_suffix_obj.account_id = account.id
                            bni_va_suffix_obj.save()
                            bni_va_suffix = bni_va_suffix_obj.bni_virtual_account_suffix

                            if bni_va_suffix is None:
                                continue

                            # GROUPING
                            range_group = 1000000
                            payment_code = PaymentMethodCodes.BNI
                            if int(bni_va_suffix) / range_group >= 1:
                                payment_code = PaymentMethodCodes.BNI_V2
                                bni_va_suffix = str(int(bni_va_suffix) % range_group).zfill(6)

                            virtual_account = "".join([payment_code, bni_va_suffix])

                            max_sequence = PaymentMethod.objects.filter(
                                customer_id=customer.id
                            ).aggregate(Max('sequence'))
                            sequence = 1

                            if max_sequence['sequence__max']:
                                sequence = max_sequence['sequence__max'] + 1

                            payment_method_data_bni.append(
                                PaymentMethod(
                                    bank_code=BankCodes.BNI,
                                    payment_method_code=payment_code,
                                    payment_method_name='Bank BNI',
                                    customer_id=customer.id,
                                    virtual_account=virtual_account,
                                    sequence=sequence,
                                    is_shown=False,
                                    is_primary=False,
                                    is_preferred=False,
                                )
                            )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    "Successfuly append customer_id: {}".format(customer.id)
                                )
                            )

                    progress_count = progress_count + 1

                PaymentMethod.objects.bulk_create(payment_method_data_bni, batch_size=500)
                self.stdout.write(
                    self.style.SUCCESS(
                        "===============Successfuly process {} out of {} customers===============".format(
                            progress_count, customer_size
                        )
                    )
                )

                for pm in payment_method_data_bni:
                    customer = pm.customer
                    if not customer:
                        continue

                    account = customer.account_set.last()
                    execute_after_transaction_safely(
                        lambda: create_va_snap_bni_transaction_retroload.delay(account.id, pm.id)
                    )

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(
                    "Failed to process customer {} due to {}".format(customer.id, str(e))
                )
            )
