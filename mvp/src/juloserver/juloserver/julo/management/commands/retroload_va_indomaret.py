from django.core.management.base import BaseCommand

from juloserver.julo.banks import BankCodes
from juloserver.julo.models import Loan, VirtualAccountSuffix, PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodCodes, PaymentMethodManager
from juloserver.julo.statuses import LoanStatusCodes


class Command(BaseCommand):
    help = 'retroactively va permata for exist loan'

    def handle(self, *args, **options):
        loans = Loan.objects.filter(loan_status__status_code__lt=LoanStatusCodes.PAID_OFF)
        for loan in loans:
            has_payment_method_indomaret = loan.paymentmethod_set.filter(
                payment_method_code=PaymentMethodCodes.INDOMARET).exists()
            if not has_payment_method_indomaret:
                va_suffix = VirtualAccountSuffix.objects.filter(loan__id=loan.id).first()
                if va_suffix:
                    indomaret = PaymentMethodManager.get_or_none(PaymentMethodCodes.INDOMARET)
                    virtual_account = "".join([
                        indomaret.faspay_payment_code,
                        va_suffix.virtual_account_suffix
                    ])
                    payment_method_data = {
                        'payment_method_code': indomaret.faspay_payment_code,
                        'payment_method_name': indomaret.name,
                        'bank_code': None,
                        'loan': loan,
                        'is_shown': True,
                        'virtual_account': virtual_account
                    }
                    payment_method_indomaret = PaymentMethod(**payment_method_data)
                    payment_method_indomaret.save()

                    self.stdout.write(self.style.SUCCESS(
                        'success load VA INDOMARET as payment method {} to Loan {}'.format(
                        payment_method_permata.id, loan.id)))

        self.stdout.write(self.style.SUCCESS('Assign VA Done'))
