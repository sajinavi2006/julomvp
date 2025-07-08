from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.db.models.query import QuerySet

from juloserver.julo.models import (
    Application,
    PaymentMethod,
    VirtualAccountSuffix,
    MandiriVirtualAccountSuffix
)
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.julo.utils import format_mobile_phone
from juloserver.julo.payment_methods import PaymentMethodManager
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

RETRO_PREFIX_PAYMENT_METHODS = {
    PaymentMethodCodes.BCA, PaymentMethodCodes.BRI, PaymentMethodCodes.MAYBANK,
    PaymentMethodCodes.PERMATA, PaymentMethodCodes.ALFAMART, PaymentMethodCodes.INDOMARET
}
ALL_AVAILABLE_PREFIX_PAYMENT_METHODS = RETRO_PREFIX_PAYMENT_METHODS.union({
    PaymentMethodCodes.GOPAY, PaymentMethodCodes.OVO
})
BANKS_PREFIX = {
    PaymentMethodCodes.BCA, PaymentMethodCodes.BRI,
    PaymentMethodCodes.MAYBANK, PaymentMethodCodes.PERMATA
}
PAYMENT_METHODS = {
    PaymentMethodCodes.BCA: "Bank BCA",
    PaymentMethodCodes.BRI: "Bank BRI",
    PaymentMethodCodes.MAYBANK: "Bank MAYBANK",
    PaymentMethodCodes.PERMATA: "PERMATA Bank",
    PaymentMethodCodes.ALFAMART: "ALFAMART",
    PaymentMethodCodes.INDOMARET: "INDOMARET",
}


class Command(BaseCommand):
    help = "Retroloads customer j1 payment method"

    def handle(self, *args, **options):
        query_filter = {
            'application_status_id__gte': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            'product_line_id': ProductLineCodes.J1,
        }
        if args[0]:
            query_filter['pk__in'] = args[0]
        applications = Application.objects.filter(**query_filter)

        with transaction.atomic():
            payment_method_data = []
            for application in applications.iterator():
                payment_methods = PaymentMethod.objects.filter(
                    customer_id=application.customer_id
                )
                if not payment_methods:
                    generate_customer_va_for_julo_one(application)
                    continue

                payment_method_code_list = list(
                    payment_methods.values_list('payment_method_code', flat=True)
                )
                payment_method_code_need_to_create = set(
                    filter(lambda item: item not in payment_method_code_list,
                           RETRO_PREFIX_PAYMENT_METHODS)
                )

                payment_methods.filter(
                    payment_method_code__in=RETRO_PREFIX_PAYMENT_METHODS
                ).update(
                    is_shown=True
                )
                is_mandiri_bank_account = application.bank_name == "BANK MANDIRI (PERSERO), Tbk"

                if not payment_method_code_need_to_create:
                    self._set_mandiri_payment_method_to_primary(payment_methods, application)
                    continue

                payment_method_name = [
                    PAYMENT_METHODS[code] for code in payment_method_code_need_to_create
                ]
                # hide old payment method
                payment_methods.filter(
                    payment_method_name__in=payment_method_name
                ).update(
                    is_shown=False
                )

                old_primary_payment_method = payment_methods.filter(
                    payment_method_name__in=payment_method_name,
                    is_primary=True,
                ).last()
                if old_primary_payment_method:
                    old_primary_payment_method.update_safely(is_primary=False)

                mobile_phone_1 = get_application_primary_phone(application)
                va_suffix = None

                if mobile_phone_1:
                    va_suffix = format_mobile_phone(mobile_phone_1)

                payment_methods_need_to_create = (
                    PaymentMethodManager.
                    filter_payment_methods_by_payment_code(payment_method_code_need_to_create)
                )
                last_sequence_number = payment_methods.order_by('sequence').values_list(
                    'sequence', flat=True
                ).last() or 0
                bank_payment_method_code_need_to_create = (
                    payment_method_code_need_to_create.intersection(BANKS_PREFIX)
                )
                if last_sequence_number > 0 and bank_payment_method_code_need_to_create:
                    last_bank_sequence_number = payment_methods.filter(
                        bank_code__isnull=False
                    ).order_by(
                        'sequence'
                    ).values_list(
                        'sequence', flat=True
                    ).last() or 0

                    non_bank_payment_methods = (
                        payment_methods.filter(bank_code__isnull=True)
                        .order_by('sequence')
                    )
                    non_bank_payment_methods.update(
                        sequence=F('sequence') + len(bank_payment_method_code_need_to_create)
                    )
                    last_sequence_number = payment_methods.order_by('sequence').values_list(
                        'sequence', flat=True
                    ).last()

                self._set_mandiri_payment_method_to_primary(payment_methods, application)

                va_suffix_random_number = None
                if PaymentMethodCodes.MAYBANK in payment_method_code_need_to_create or \
                        PaymentMethodCodes.PERMATA in payment_method_code_need_to_create or\
                        not va_suffix:
                    va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                        loan=None, line_of_credit=None, account=None).order_by('id').first()
                    if not va_suffix_obj:
                        raise Exception('no va suffix available')
                    va_suffix_obj.account = application.account
                    va_suffix_obj.save()
                    va_suffix_random_number = va_suffix_obj.virtual_account_suffix

                for payment_method in payment_methods_need_to_create:
                    virtual_account = ""
                    payment_code = payment_method.payment_code
                    is_primary = False

                    if payment_code:
                        if payment_code[-1] == '0':
                            virtual_account = "".join([
                                payment_code,
                                va_suffix[1:]
                            ])
                        else:
                            virtual_account = "".join([
                                payment_code,
                                va_suffix
                            ])

                    if payment_method.code == BankCodes.MAYBANK or \
                            payment_method.code == BankCodes.PERMATA:
                        if va_suffix_random_number is None:
                            continue

                        virtual_account = "".join([payment_code,
                                                   va_suffix_random_number])

                    if payment_method.code == BankCodes.MANDIRI:
                        mandiri_va_suffix_obj = (
                            MandiriVirtualAccountSuffix.objects.select_for_update()
                            .filter(account=None).order_by('id').first()
                        )
                        if not mandiri_va_suffix_obj:
                            raise Exception('no va suffix mandiri available')
                        mandiri_va_suffix_obj.account = application.account
                        mandiri_va_suffix_obj.save()
                        mandiri_va_suffix = mandiri_va_suffix_obj.mandiri_virtual_account_suffix

                        if mandiri_va_suffix is None:
                            continue
                        virtual_account = "".join([payment_code,
                                                   mandiri_va_suffix])

                    bank_code = None
                    if payment_method.type == 'bank':
                        bank_code = payment_method.code
                        sequence = last_bank_sequence_number + 1
                        last_bank_sequence_number = sequence
                    else:
                        sequence = last_sequence_number + 1
                        last_sequence_number = sequence

                    if old_primary_payment_method and \
                            old_primary_payment_method.payment_method_name == payment_method.name:
                        is_primary = True

                    if is_mandiri_bank_account:
                        is_primary = False

                    payment_method_data.append(
                        PaymentMethod(
                            payment_method_code=payment_code,
                            payment_method_name=payment_method.name,
                            bank_code=bank_code,
                            customer_id=application.customer_id,
                            is_shown=True,
                            is_primary=is_primary,
                            virtual_account=virtual_account,
                            sequence=sequence)
                    )

            PaymentMethod.objects.bulk_create(payment_method_data, batch_size=30)

    def _set_mandiri_payment_method_to_primary(
            self, payment_methods: QuerySet, application: Application
    ) -> None:
        is_mandiri_bank_account = application.bank_name == "BANK MANDIRI (PERSERO), Tbk"
        if not is_mandiri_bank_account:
            return
        mandiri_payment_method = payment_methods.filter(
            payment_method_code=PaymentMethodCodes.MANDIRI
        ).last()
        if mandiri_payment_method and not mandiri_payment_method.is_primary:
            payment_methods.update(is_primary=False)
            mandiri_payment_method.update_safely(is_primary=True)
