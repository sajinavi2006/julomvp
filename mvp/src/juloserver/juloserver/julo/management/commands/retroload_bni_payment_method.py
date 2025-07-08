from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import (
    Application,
    PaymentMethod,
    BniVirtualAccountSuffix,
)
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import populate_bni_virtual_account_suffix

class Command(BaseCommand):
    help = 'Helps to retroload bni payment method'

    def handle(self, *args, **options):
        eligible_product_line_codes = [ProductLineCodes.J1, ProductLineCodes.JULO_STARTER]
        query_filter = {
            'application_status__gte': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'product_line__in': eligible_product_line_codes,
            'bank_name__contains': 'BNI'
        }
        application_data_141_bni = Application.objects.filter(**query_filter).distinct('customer_id')
        payment_method_data_bni = []

        for application in application_data_141_bni.iterator():
            payment_method_bni = PaymentMethod.objects.filter(
                payment_method_name='Bank BNI',
                customer_id=application.customer_id
            ).last()

            if payment_method_bni:
                if not payment_method_bni.is_primary:
                    payment_method_primary = PaymentMethod.objects.filter(
                        customer_id=application.customer_id,
                        is_primary=True).last()
                    if payment_method_primary:
                        payment_method_primary.update_safely(is_primary=False)

                    payment_method_bni.update_safely(
                        is_primary=True,
                        is_shown=True,
                    )
            else:
                populate_bni_virtual_account_suffix()
                with transaction.atomic(using='repayment_db'):
                    if not application.customer.account:
                        continue
                    bni_va_suffix_obj = (
                        BniVirtualAccountSuffix.objects.select_for_update()
                        .filter(account_id=None)
                        .order_by('id')
                        .first()
                    )
                    if not bni_va_suffix_obj:
                        continue
                    bni_va_suffix_obj.account = application.customer.account
                    bni_va_suffix_obj.save()
                    bni_va_suffix = bni_va_suffix_obj.bni_virtual_account_suffix

                    if bni_va_suffix is None:
                        continue
                    virtual_account = "".join([PaymentMethodCodes.BNI,
                                               bni_va_suffix])

                    max_sequence = PaymentMethod.objects.filter(
                        customer_id=application.customer_id).aggregate(Max('sequence'))
                    sequence=1
                    if max_sequence['sequence__max']:
                        sequence = max_sequence['sequence__max'] + 1

                    payment_method_primary = PaymentMethod.objects.filter(
                        customer_id=application.customer_id,
                        is_primary=True).last()
                    if payment_method_primary:
                        payment_method_primary.update_safely(is_primary=False)

                    payment_method_data_bni.append(
                        PaymentMethod(
                            bank_code=BankCodes.BNI,
                            payment_method_code=PaymentMethodCodes.BNI,
                            payment_method_name='Bank BNI',
                            customer_id=application.customer_id,
                            virtual_account=virtual_account,
                            sequence=sequence,
                            is_shown=True,
                            is_primary=True,
                            is_preferred=False
                        )
                    )

        PaymentMethod.objects.bulk_create(payment_method_data_bni, batch_size=50)
