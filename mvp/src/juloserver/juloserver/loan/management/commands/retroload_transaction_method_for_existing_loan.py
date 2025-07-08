from django.core.management.base import BaseCommand
from juloserver.julo.models import Loan, SepulsaTransaction

from juloserver.loan.services.loan_related import determine_transaction_method_by_transaction_type
from juloserver.payment_point.services.product_related import \
    determine_transaction_method_by_sepulsa_product


class Command(BaseCommand):
    help = "Retroloads transaction method for existing loan"

    def handle(self, *args, **options):
        j1_loans = Loan.objects.filter(
            transaction_method__isnull=True, account__isnull=False)
        for loan in j1_loans:
            sepulsa_trx = SepulsaTransaction.objects.filter(loan=loan).first()
            if sepulsa_trx:
                transaction_method = determine_transaction_method_by_sepulsa_product(
                    sepulsa_trx.product)
            else:
                bank_account_destination = loan.bank_account_destination
                if bank_account_destination:
                    transaction_type = bank_account_destination.bank_account_category.category
                    transaction_method = determine_transaction_method_by_transaction_type(
                        transaction_type)
            if sepulsa_trx or loan.bank_account_destination:
                loan.update_safely(transaction_method=transaction_method)
                self.stdout.write(self.style.SUCCESS("===============loan_id===================="))
                self.stdout.write(self.style.SUCCESS("%s" % loan.id))
                self.stdout.write(self.style.SUCCESS("=========================================="))
