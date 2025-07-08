from django.core.management.base import BaseCommand
from django.db import transaction
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import (
    Application,
    PaymentMethod,
    MandiriVirtualAccountSuffix,
)
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes, SecondaryMethodName
from juloserver.julo.tasks import populate_mandiri_virtual_account_suffix

class Command(BaseCommand):
    help = 'Helps to retroload mandiri payment method'

    def handle(self, *args, **options):

        application_data_141 = Application.objects.filter(
            account_id__account_lookup_id=1,
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
            ).distinct('customer_id')

        for application in application_data_141:
            payment_method = PaymentMethod.objects.filter(
                payment_method_name='Bank MANDIRI',
                customer_id=application.customer_id
            ).last()

            populate_mandiri_virtual_account_suffix()
            mandiri_va_suffix = None
            with transaction.atomic():
                mandiri_va_suffix_obj = MandiriVirtualAccountSuffix.objects.select_for_update().filter(
                    account=None).order_by('id').first()
                mandiri_va_suffix_obj.account = application.account
                mandiri_va_suffix_obj.save()
                mandiri_va_suffix = mandiri_va_suffix_obj.mandiri_virtual_account_suffix

            if mandiri_va_suffix is None:
                continue

            virtual_account = "".join([PaymentMethodCodes.MANDIRI,
                                       mandiri_va_suffix])
            if payment_method:
                if len(payment_method.virtual_account) == 16 and payment_method.virtual_account[:8] == PaymentMethodCodes.MANDIRI:
                    if payment_method.payment_method_code == PaymentMethodCodes.MANDIRI:
                        continue
                    else:
                        payment_method.update_safely(payment_method_code=PaymentMethodCodes.MANDIRI)
                else:
                    payment_method.update_safely(virtual_account=virtual_account, payment_method_code=PaymentMethodCodes.MANDIRI)
            else:
                PaymentMethod.objects.create(
                    bank_code=BankCodes.MANDIRI,
                    payment_method_code=PaymentMethodCodes.MANDIRI,
                    payment_method_name='Bank MANDIRI',
                    customer_id=application.customer_id,
                    virtual_account=virtual_account,
                    is_shown=True,
                    is_primary=False,
                    is_preferred=False
                )

                payment_method = PaymentMethod.objects.filter(customer_id=application.customer_id)
                payment_method_primary = payment_method.filter(is_primary=True).last()
                sequence = 1
                if payment_method_primary:
                    payment_method_primary.update_safely(sequence=sequence)
                    sequence+=1

                non_secondary_payment_methods = payment_method.exclude(payment_method_name__in=SecondaryMethodName)
                for payment in non_secondary_payment_methods:
                    if payment.is_primary == True:
                        continue
                    payment.update_safely(sequence=sequence)
                    sequence+=1

                secondary_payment_methods = payment_method.filter(payment_method_name__in=SecondaryMethodName)
                for payment in secondary_payment_methods:
                    if payment.is_primary == True:
                        continue
                    payment.update_safely(sequence=sequence)
                    sequence+=1
