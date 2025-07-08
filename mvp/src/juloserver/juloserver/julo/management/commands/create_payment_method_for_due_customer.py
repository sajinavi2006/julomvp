from django.core.management.base import BaseCommand

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.models import Payment
from juloserver.julo.models import BankVirtualAccount
from juloserver.julo.models import Loan

class Command(BaseCommand):
    help = 'create payment method offline bank for customer due in 1-3 desember'

    def handle(self, *args, **options):
        now = '2017-12-01'
        then = '2017-12-03'
        payment_due = Payment.objects.filter(due_date__gte=now,due_date__lte=then)\
            .filter(payment_number=1)\
            .filter(payment_status_id__lte=330)

        for payment in payment_due:
            loan = Loan.objects.get(pk=payment.loan.id)
            if loan.julo_bank_name in ['Bank MANDIRI', 'PERMATA Bank']:
                if 'BANK CENTRAL ASIA' in loan.application.bank_name:
                    va = BankVirtualAccount.objects.filter(bank_code='014',loan_id=None).first()
                    va.loan = loan
                    va.save()
                    loan.julo_bank_name = va.bank_code.name
                    loan.julo_bank_account_number = va.virtual_account_number
                    loan.save()
                    PaymentMethod.objects.create(
                            payment_method_code=va.bank_code_id,
                            payment_method_name=va.bank_code.name,
                            bank_code=va.bank_code_id,
                            loan=loan,
                            virtual_account=va.virtual_account_number
                            )
                else:
                    va = BankVirtualAccount.objects.filter(bank_code='022',loan_id=None).first()
                    va.loan = loan
                    va.save()
                    loan.julo_bank_name = va.bank_code.name
                    loan.julo_bank_account_number = va.virtual_account_number
                    loan.save()
                    PaymentMethod.objects.create(
                            payment_method_code=va.bank_code_id,
                            payment_method_name=va.bank_code.name,
                            bank_code=va.bank_code_id,
                            loan=loan,
                            virtual_account=va.virtual_account_number
                            )

        self.stdout.write(self.style.SUCCESS('Successfully create va'))
