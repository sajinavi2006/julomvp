from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db import transaction

from juloserver.julo.models import (
    PaymentMethod,
)
from juloserver.account.constants import AccountConstant
from juloserver.julo.services2.payment_method import get_application_primary_phone
from juloserver.julo.models import VirtualAccountSuffix
from juloserver.julo.utils import format_mobile_phone

OLD_BCA_PAYMENT_METHOD_CODE = '188880'
OLD_PERMATA_PAYMENT_METHOD_CODE = '877332'
NEW_BCA_PAYMENT_METHOD_CODE = '10994'
NEW_PERMATA_PAYMENT_METHOD_CODE = '851598'

MAPPING_PAYMENT_METHOD_CODE = {
    OLD_BCA_PAYMENT_METHOD_CODE: NEW_BCA_PAYMENT_METHOD_CODE,
    OLD_PERMATA_PAYMENT_METHOD_CODE: NEW_PERMATA_PAYMENT_METHOD_CODE,
}


def get_customer_id_from_payment_method(payment_method_code):
    return PaymentMethod.objects.filter(
        payment_method_code=payment_method_code, customer__isnull=False
    ).values_list('customer_id', flat=True)


class Command(BaseCommand):
    help = "Retroloads old va faspay bca and permata"

    def handle(self, *args, **options):
        combined_query = PaymentMethod.objects.filter(customer__isnull=False).filter(
            (Q(payment_method_code=OLD_PERMATA_PAYMENT_METHOD_CODE) &
             ~Q(customer_id__in=get_customer_id_from_payment_method(
                 NEW_PERMATA_PAYMENT_METHOD_CODE))) |
            (Q(payment_method_code=OLD_BCA_PAYMENT_METHOD_CODE) &
             ~Q(customer_id__in=get_customer_id_from_payment_method(NEW_BCA_PAYMENT_METHOD_CODE))),
        ).exclude(customer__account__status__in={
            AccountConstant.STATUS_CODE.inactive,
            AccountConstant.STATUS_CODE.deactivated,
            AccountConstant.STATUS_CODE.terminated,
        })
        data_new_payment_method = []
        update_payment_method = []
        update_primary_payment_method = []
        for old_payment_method in combined_query.iterator():
            account = old_payment_method.customer.account
            customer = old_payment_method.customer
            new_payment_method_code = MAPPING_PAYMENT_METHOD_CODE[
                old_payment_method.payment_method_code
            ]
            va_suffix = None
            if new_payment_method_code == NEW_BCA_PAYMENT_METHOD_CODE:
                va_suffix = get_application_primary_phone(customer.application_set.last())
                if va_suffix:
                    va_suffix = format_mobile_phone(va_suffix)
            if new_payment_method_code == NEW_PERMATA_PAYMENT_METHOD_CODE or not va_suffix:
                with transaction.atomic():
                    va_suffix_obj = VirtualAccountSuffix.objects.select_for_update().filter(
                        loan=None, line_of_credit=None, account=None).order_by('id').first()
                    if not va_suffix_obj:
                        raise Exception('no va suffix available')
                    va_suffix_obj.account = account
                    if not account:
                        loan = customer.loan_set.last()
                        if not loan:
                            self.stdout.write(
                                self.style.ERROR(
                                    'va suffix not available for payment method id {}'.format(
                                        old_payment_method.id
                                    )
                                )
                            )
                            continue
                        va_suffix_obj.loan = loan
                    va_suffix_obj.save(update_fields=['loan', 'account'])
                    va_suffix = va_suffix_obj.virtual_account_suffix
            if not va_suffix:
                self.stdout.write(
                    self.style.ERROR(
                        'va suffix not available for payment method id {}'.format(
                            old_payment_method.id
                        )
                    )
                )
                continue
            va = (
                    new_payment_method_code
                    + va_suffix
            )
            if va in {
                NEW_BCA_PAYMENT_METHOD_CODE + 'None',
                NEW_PERMATA_PAYMENT_METHOD_CODE + 'None',
            }:
                self.stdout.write(
                    self.style.ERROR(
                        'va suffix invalid format for payment method id {}'.format(
                            old_payment_method.id
                        )
                    )
                )
                continue
            data_new_payment_method.append(
                PaymentMethod(
                    customer=old_payment_method.customer,
                    payment_method_code=new_payment_method_code,
                    virtual_account=va,
                    payment_method_name=old_payment_method.payment_method_name,
                    bank_code=old_payment_method.bank_code,
                    sequence=old_payment_method.sequence,
                    is_primary=old_payment_method.is_primary,
                    is_latest_payment_method=old_payment_method.is_latest_payment_method,
                )
            )
            if old_payment_method.is_shown:
                update_payment_method.append(old_payment_method.id)
            if old_payment_method.is_primary:
                update_primary_payment_method.append(old_payment_method.id)
            if old_payment_method.is_latest_payment_method:
                old_payment_method.update_safely(is_latest_payment_method=False)

        PaymentMethod.objects.bulk_create(data_new_payment_method, batch_size=500)
        for index in range(0, len(update_payment_method), 500):
            PaymentMethod.objects.filter(
                pk__in=update_payment_method[index: index + 500]
            ).update(is_shown=False)
        for index in range(0, len(update_primary_payment_method), 500):
            PaymentMethod.objects.filter(
                pk__in=update_primary_payment_method[index: index + 500]
            ).update(is_primary=False)
        old_payment_methods_shown = PaymentMethod.objects.filter(customer__isnull=False).filter(
            (
                Q(payment_method_code=OLD_BCA_PAYMENT_METHOD_CODE)
                | Q(payment_method_code=OLD_PERMATA_PAYMENT_METHOD_CODE)
            )
            & Q(is_shown=True),
        )
        customer_id_old_payment_methods_shown = old_payment_methods_shown.values_list(
            "customer_id", flat=True
        )
        old_bca_payment_methods_primary = old_payment_methods_shown.filter(
            is_primary=True,
            payment_method_code=OLD_BCA_PAYMENT_METHOD_CODE,
        )
        old_permata_payment_methods_primary = old_payment_methods_shown.filter(
            is_primary=True,
            payment_method_code=OLD_PERMATA_PAYMENT_METHOD_CODE,
        )
        old_bca_payment_methods_latest = old_payment_methods_shown.filter(
            is_latest_payment_method=True,
            payment_method_code=OLD_BCA_PAYMENT_METHOD_CODE,
        )
        old_permata_payment_methods_latest = old_payment_methods_shown.filter(
            is_latest_payment_method=True,
            payment_method_code=OLD_PERMATA_PAYMENT_METHOD_CODE,
        )
        customer_id_old_bca_payment_methods_primary = old_bca_payment_methods_primary.values_list(
            "customer_id", flat=True
        )
        customer_id_old_permata_payment_methods_primary = (
            old_permata_payment_methods_primary.values_list("customer_id", flat=True)
        )
        customer_id_old_bca_payment_methods_latest = old_bca_payment_methods_latest.values_list(
            "customer_id", flat=True
        )
        customer_id_old_permata_payment_methods_latest = (
            old_permata_payment_methods_latest.values_list("customer_id", flat=True)
        )
        PaymentMethod.objects.filter(customer_id__in=customer_id_old_payment_methods_shown).filter(
            (
                Q(payment_method_code=NEW_BCA_PAYMENT_METHOD_CODE)
                | Q(payment_method_code=NEW_PERMATA_PAYMENT_METHOD_CODE)
            )
            & Q(is_shown=False),
        ).update(is_shown=True)
        PaymentMethod.objects.filter(
            customer_id__in=customer_id_old_permata_payment_methods_primary,
            payment_method_code=NEW_PERMATA_PAYMENT_METHOD_CODE,
        ).update(is_primary=True)
        PaymentMethod.objects.filter(
            customer_id__in=customer_id_old_bca_payment_methods_primary,
            payment_method_code=NEW_BCA_PAYMENT_METHOD_CODE,
        ).update(is_primary=True)
        PaymentMethod.objects.filter(
            customer_id__in=customer_id_old_permata_payment_methods_latest,
            payment_method_code=NEW_PERMATA_PAYMENT_METHOD_CODE,
        ).update(is_latest_payment_method=True)
        PaymentMethod.objects.filter(
            customer_id__in=customer_id_old_bca_payment_methods_latest,
            payment_method_code=NEW_BCA_PAYMENT_METHOD_CODE,
        ).update(is_latest_payment_method=True)
        old_bca_payment_methods_primary.update(is_primary=False)
        old_permata_payment_methods_primary.update(is_primary=False)
        old_bca_payment_methods_latest.update(is_latest_payment_method=False)
        old_permata_payment_methods_latest.update(is_latest_payment_method=False)
        old_payment_methods_shown.update(is_shown=False)
        self.stdout.write(
            self.style.SUCCESS('Successfully retroload old va faspay bca and permata')
        )
