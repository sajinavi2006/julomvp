from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.julo.models import Loan, PaymentMethod, VirtualAccountSuffix
from juloserver.julo.banks import  BankCodes
from juloserver.julo.payment_methods import PaymentMethodManager


class Command(BaseCommand):
    help = 'Add BCA to payment method list of ICARE customer'

    def handle(self, *args, **options):
        loans = Loan.objects.filter(application__partner__name='icare')\
                            .exclude(application__application_status=135)\
                            .exclude(loan_status=250)

        bca_method = PaymentMethodManager.get_or_none(BankCodes.BCA)
        if not bca_method:
            self.stdout.write(self.style.ERROR('BCA Method not found!'))

        for loan in loans:
            with transaction.atomic():
                virtual_account_obj = VirtualAccountSuffix.objects.filter(loan=loan).first()
                if virtual_account_obj:
                    has_bca_method = PaymentMethod.objects.filter(loan=loan, bank_code=bca_method.code)
                    if not has_bca_method:
                        virtual_account = bca_method.faspay_payment_code + virtual_account_obj.virtual_account_suffix
                        PaymentMethod.objects.create(
                            payment_method_code=bca_method.faspay_payment_code,
                            payment_method_name=bca_method.name,
                            bank_code=bca_method.code,
                            loan=loan,
                            is_shown=False,
                            virtual_account=virtual_account
                            )
                        self.stdout.write(self.style.SUCCESS('Done: %s' % loan.id))
                    else:
                        self.stdout.write(self.style.ERROR('BCA already existed!'))
                else:
                    self.stdout.write(self.style.ERROR('Virtual account not found !'))
