import math

from typing import Optional, Tuple
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.db import transaction
from bulk_update.helper import bulk_update

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import (
    Application,
    PaymentMethod,
    Customer,
)
from juloserver.payback.models import DokuVirtualAccountSuffix
from juloserver.julo.models import PaymentMethod
from juloserver.julo.banks import BankCodes
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.payment_methods import PaymentMethod as PaymentMethodConst
from juloserver.payback.tasks.doku_tasks import populate_doku_virtual_account_suffix


class Command(BaseCommand):
    help = 'Helps to retroload DOKU payment method'
    batch_size = 2000

    def add_arguments(self, parser):
        parser.add_argument("--application_ids", nargs="+", type=int)

    def handle(self, *args, **options):
        if options["application_ids"] is None:
            confirmation = input("You want to retroload all application. Are you sure? (Y/N): ")

            if confirmation.lower() == 'y':
                self.stdout.write(
                    self.style.SUCCESS("Retroloading payment method for all applications...")
                )
            else:
                self.stdout.write(self.style.WARNING("Command aborted."))
                return

        print("Please choose retroload:")
        print("1. Retroload new DOKU payment method")
        print("2. Retroload is_shown false for Faspay")

        choice = input("Enter your choice (1 or 2): ")
        if choice == "1":
            self.retoload_new_doku_payment_method(options['application_ids'])
        elif choice == "2":
            self.retoload_faspay_is_shown_false(options['application_ids'])
        else:
            self.stdout.write(self.style.ERROR("Invalid choice. Command aborted."))
            return

    def retoload_new_doku_payment_method(self, application_ids: list):
        application_ids = self.get_applications(application_ids)

        application_size = len(application_ids)
        batch_num = math.ceil(application_size / self.batch_size)
        self.stdout.write(
            self.style.SUCCESS(
                f'Total Application: {application_size}. Batch Number: {batch_num}. Batch Size: {self.batch_size}'
            )
        )

        payment_method_consts = self.get_payment_method_consts()
        for i in range(batch_num):
            start_index = i * self.batch_size
            end_index = (i + 1) * self.batch_size

            application_batch = Application.objects.filter(
                pk__in=(application_ids[start_index:end_index])
            )

            if not application_batch.exists():
                # stop creating
                break

            self.stdout.write(
                self.style.SUCCESS(
                    f'========================== START RETROLOAD DOKU PAYMENT METHOD BATCH {i+1} =========================='
                )
            )

            self.preassign_suffix_virtual_account(application_batch)

            with transaction.atomic():
                doku_payment_methods = []
                faspay_payment_methods = []
                for application in application_batch:
                    primary_bank_code = self.get_primary_bank_code(application.bank_name)
                    last_sequence = self.get_sequence_payment_method(application.customer)
                    va_suffix = self.get_suffix_virtual_account(application)
                    if not va_suffix:
                        self.stdout.write(
                            self.style.WARNING(
                                f'Application: {application.id} -> ' + f'Failed to get Suffix'
                            )
                        )
                        continue

                    is_booked_primary_from_other_payment_method = False
                    faspay_payment_method = PaymentMethod.objects.filter(
                        customer=application.customer,
                        is_primary=True,
                    ).first()
                    if (
                        faspay_payment_method
                        and faspay_payment_method.bank_code != primary_bank_code
                    ):
                        is_booked_primary_from_other_payment_method = True

                    for seq, payment_method_const in enumerate(payment_method_consts):
                        customer_has_va = PaymentMethod.objects.filter(
                            payment_method_code=payment_method_const.payment_code,
                            customer=application.customer,
                        ).first()

                        if customer_has_va:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Application: {application.id} -> '
                                    + f'Customer with {payment_method_const.name} has VA {customer_has_va.virtual_account}'
                                )
                            )
                            continue

                        virtual_account = "".join([payment_method_const.payment_code, va_suffix])

                        faspay_payment_method_datum = PaymentMethod.objects.filter(
                            payment_method_code=payment_method_const.faspay_payment_code,
                            customer=application.customer,
                            is_shown=True,
                        )
                        faspay_is_primary = False
                        faspay_is_latest_payment_method = None
                        for faspay_payment_method in faspay_payment_method_datum:
                            faspay_is_primary = faspay_payment_method.is_primary
                            faspay_is_latest_payment_method = (
                                faspay_payment_method.is_latest_payment_method
                            )

                            faspay_payment_method.is_shown = False
                            faspay_payment_method.is_primary = False
                            if faspay_payment_method.is_latest_payment_method is True:
                                faspay_payment_method.is_latest_payment_method = False
                            faspay_payment_methods.append(faspay_payment_method)

                        is_primary = faspay_is_primary
                        is_latest_payment_method = faspay_is_latest_payment_method
                        if (
                            payment_method_const.code == primary_bank_code
                            and not is_booked_primary_from_other_payment_method
                        ):
                            is_primary = True

                        doku_payment_method = PaymentMethod(
                            payment_method_code=payment_method_const.payment_code,
                            payment_method_name=payment_method_const.name,
                            bank_code=payment_method_const.code,
                            customer=application.customer,
                            is_shown=True,
                            is_primary=is_primary,
                            is_latest_payment_method=is_latest_payment_method,
                            virtual_account=virtual_account,
                            sequence=last_sequence + seq + 1,
                        )
                        doku_payment_methods.append(doku_payment_method)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Application: {application.id} -> '
                                + f'Creating payment method {payment_method_const.name} with VA {virtual_account}'
                            )
                        )

                PaymentMethod.objects.bulk_create(doku_payment_methods, batch_size=500)
                bulk_update(
                    faspay_payment_methods,
                    update_fields=['is_shown', 'is_primary', 'is_latest_payment_method'],
                    batch_size=500,
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f'========================== SUCCESS RETROLOAD DOKU PAYMENT METHOD BATCH {i+1} ==========================\n\n'
                )
            )

    def retoload_faspay_is_shown_false(self, application_ids: list):
        application_ids = self.get_application_with_faspay_shown_true(application_ids)

        application_size = len(application_ids)
        batch_num = math.ceil(application_size / self.batch_size)
        self.stdout.write(
            self.style.SUCCESS(
                f'Total Application: {application_size}. Batch Number: {batch_num}. Batch Size: {self.batch_size}'
            )
        )

        payment_method_consts = self.get_payment_method_consts()
        for i in range(batch_num):
            start_index = i * self.batch_size
            end_index = (i + 1) * self.batch_size

            application_batch = Application.objects.filter(
                pk__in=(application_ids[start_index:end_index])
            )

            if not application_batch.exists():
                # stop creating
                break

            self.stdout.write(
                self.style.SUCCESS(
                    f'========================== START RETROLOAD FASPAY SHOWN FALSE PAYMENT METHOD BATCH {i+1} =========================='
                )
            )

            with transaction.atomic():
                faspay_payment_methods = []
                for application in application_batch:
                    for _, payment_method_const in enumerate(payment_method_consts):
                        customer_has_va = PaymentMethod.objects.filter(
                            payment_method_code=payment_method_const.payment_code,
                            customer=application.customer,
                        ).first()

                        if not customer_has_va:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Application: {application.id} -> '
                                    + f'Customer with {payment_method_const.name} doesn`t have VA DOKU'
                                )
                            )
                            continue

                        faspay_payment_methods_shown_true = PaymentMethod.objects.filter(
                            payment_method_code=payment_method_const.faspay_payment_code,
                            customer=application.customer,
                            is_shown=True,
                        )

                        for faspay_payment_method in faspay_payment_methods_shown_true:
                            faspay_payment_method.is_shown = False
                            faspay_payment_method.is_primary = False

                            faspay_payment_methods.append(faspay_payment_method)

                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'Application: {application.id} -> '
                                    + f'Set shown False for faspay payment method {payment_method_const.name} with VA {faspay_payment_method.virtual_account}'
                                )
                            )

                bulk_update(
                    faspay_payment_methods,
                    update_fields=['is_shown', 'is_primary'],
                    batch_size=500,
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f'========================== SUCCESS RETROLOAD FASPAY SHOWN FALSE PAYMENT METHOD BATCH {i+1} ==========================\n\n'
                )
            )

    def preassign_suffix_virtual_account(self, application_batch):
        populate_doku_virtual_account_suffix()

        offset = 100000
        limit = offset + len(application_batch)
        doku_va_suffix_assigns = DokuVirtualAccountSuffix.objects.filter(account_id=None).order_by(
            'id'
        )[offset:limit]

        existing_suffix_accounts = set(
            DokuVirtualAccountSuffix.objects.filter(
                account_id__in=[app.account_id for app in application_batch]
            ).values_list('account_id', flat=True)
        )

        doku_va_suffix_assigned = []
        for idx, application in enumerate(application_batch):
            if application.account_id and application.account_id in existing_suffix_accounts:
                continue

            if idx >= len(doku_va_suffix_assigns):
                break

            doku_va_suffix_assign = doku_va_suffix_assigns[idx]
            doku_va_suffix_assign.account_id = application.account_id
            doku_va_suffix_assigned.append(doku_va_suffix_assign)

        bulk_update(
            doku_va_suffix_assigned,
            update_fields=['account_id'],
            batch_size=500,
            using='repayment_db',
        )

    def get_sequence_payment_method(
        self,
        customer: Customer,
    ) -> int:
        last_sequence = 0
        other_payment_method = (
            PaymentMethod.objects.filter(customer=customer, sequence__isnull=False)
            .order_by("sequence")
            .values("sequence")
            .last()
        )
        if other_payment_method:
            last_sequence = other_payment_method["sequence"]

        return last_sequence

    def get_suffix_virtual_account(self, application: Application) -> Optional[str]:
        doku_va_suffix_obj = (
            DokuVirtualAccountSuffix.objects.filter(account_id=application.account.id)
            .order_by('id')
            .first()
        )
        if not doku_va_suffix_obj:
            return None

        return doku_va_suffix_obj.virtual_account_suffix

    def get_primary_bank_code(self, bank_name: str) -> Optional[str]:
        bank_name = bank_name if bank_name is not None else ""
        primary_bank_code = None
        if "BRI" in bank_name:
            primary_bank_code = BankCodes.BRI
        elif "MANDIRI" in bank_name:
            primary_bank_code = BankCodes.MANDIRI
        elif "PERMATA" in bank_name:
            primary_bank_code = BankCodes.PERMATA

        return primary_bank_code

    def get_applications(self, application_ids: list) -> list:
        payment_method_const = self.get_payment_method_consts()
        faspay_payment_method_codes = self.get_payment_method_codes_faspay(payment_method_const)

        julo_one_query = Q(account_id__account_lookup__workflow__name=WorkflowConst.JULO_ONE) & Q(
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )
        julo_turbo_query = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
        ) & Q(application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)

        payment_method_faspay_query = Q(
            customer__paymentmethod__payment_method_code__in=faspay_payment_method_codes,
            customer__paymentmethod__is_shown=True,
        )

        application_queries = Application.objects.filter(
            (julo_one_query | julo_turbo_query)
            & payment_method_faspay_query
            & Q(product_line_id__in=[1, 2])
        )

        if application_ids:
            application_queries = application_queries.filter(id__in=application_ids)

        applications = application_queries.distinct('customer_id')

        application_ids = applications.values_list('id', flat=True)

        return application_ids

    def get_application_with_faspay_shown_true(self, application_ids: list) -> list:
        payment_method_const = self.get_payment_method_consts()
        faspay_payment_method_codes = self.get_payment_method_codes_faspay(payment_method_const)

        julo_one_query = Q(account_id__account_lookup__workflow__name=WorkflowConst.JULO_ONE) & Q(
            application_status__gte=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        )
        julo_turbo_query = Q(
            account_id__account_lookup__workflow__name=WorkflowConst.JULO_STARTER
        ) & Q(application_status__gte=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED)
        payment_method_faspay_query = Q(
            customer__paymentmethod__payment_method_code__in=faspay_payment_method_codes,
            customer__paymentmethod__is_shown=True,
        )

        application_queries = Application.objects.filter(
            (julo_one_query | julo_turbo_query)
            & payment_method_faspay_query
            & Q(product_line_id__in=[1, 2])
        )

        if application_ids:
            application_queries = application_queries.filter(id__in=application_ids)

        applications = application_queries.distinct('customer_id')

        application_ids = applications.values_list('id', flat=True)

        return application_ids

    def get_payment_method_consts(self) -> Tuple[PaymentMethodConst]:
        payment_method_consts = (
            PaymentMethodConst(
                code=BankCodes.MANDIRI,
                name="Bank MANDIRI",
                faspay_payment_code=PaymentMethodCodes.MANDIRI,
                payment_code=PaymentMethodCodes.MANDIRI_DOKU,
                type='bank',
            ),
            PaymentMethodConst(
                code=BankCodes.BRI,
                name="Bank BRI",
                faspay_payment_code=PaymentMethodCodes.BRI,
                payment_code=PaymentMethodCodes.BRI_DOKU,
                type='bank',
            ),
            PaymentMethodConst(
                code=BankCodes.PERMATA,
                name="PERMATA Bank",
                faspay_payment_code=PaymentMethodCodes.PERMATA,
                payment_code=PaymentMethodCodes.PERMATA_DOKU,
                type='bank',
            ),
        )

        return payment_method_consts

    def get_payment_method_codes_doku(
        self, payment_method_consts: Tuple[PaymentMethodConst]
    ) -> Tuple:
        payment_method_doku = []
        for payment_method_const in payment_method_consts:
            payment_method_doku.append(payment_method_const.faspay_payment_code)

        return tuple(payment_method_doku)

    def get_payment_method_codes_faspay(
        self, payment_method_consts: Tuple[PaymentMethodConst]
    ) -> Tuple:
        payment_method_faspay = []
        for payment_method_const in payment_method_consts:
            payment_method_faspay.append(payment_method_const.faspay_payment_code)

        return tuple(payment_method_faspay)
