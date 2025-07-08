
from django.core.management.base import BaseCommand
from django.db.models import Q
from ...models import Loan, PaymentMethod
from ...banks import  BankCodes
class Command(BaseCommand):
    help = 'set payment methods'

    def handle(self, *args, **options):
        loans = Loan.objects.filter(Q(loan_status__gte=210) | Q(loan_status__lt=250))

        for loan in loans:
            if "BCA" not in loan.application.bank_name:
                for payment in PaymentMethod.objects.filter(loan=loan,bank_code=BankCodes.PERMATA):
                    payment.is_preferred = True
                    payment.save(update_fields=['is_preferred',
                                                'udate'])