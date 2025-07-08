from builtins import str
from django.core.management.base import BaseCommand

from juloserver.julo.models import Loan


class Command(BaseCommand):
    help = 'udate_lender_in_loan'

    def handle(self, *args, **options):
        file_data = '../../ojk_retroload_data/loan_transaction.csv'

        self.stdout.write(self.style.SUCCESS("======================update lender in loan begin======================"))
        failed_count = 0
        failed_data = {}
        success_count = 0
        skip_count = 0
        skip_data = {}

        with open(file_data, 'r') as opened_file:
            list_data = opened_file.readlines()

        for index, row in enumerate(list_data):
            row = row.replace("\n", "")
            row_splited = row.split(",")

            if row_splited[0].strip() == 'loan_id':
                continue

            loan_id = row_splited[0].strip()
            lender_id = row_splited[1].strip()

            try:
                loan = Loan.objects.get_or_none(pk=loan_id)
                if loan.lender and loan.lender.id == int(lender_id):
                    skip_count += 1
                    skip_data[loan_id] = "Loan id has been skiped"
                    continue

                if not loan:
                    failed_count += 1
                    failed_data[loan_id] = "loan id not exist"
                    continue

                loan.update_safely(lender_id=lender_id)
                self.stdout.write(self.style.SUCCESS("loan id {} has been success updated".format(loan_id)))
                success_count += 1
            except Exception as e:
                failed_count += 1
                failed_data[loan_id] = str(e)

        self.stdout.write(self.style.SUCCESS("=====================update lender in loan finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(success_count) + " success update lender in loan ]"))
        self.stdout.write(self.style.SUCCESS("[ " + str(skip_count) + " skip update lender in loan ]"))
        self.stdout.write(self.style.SUCCESS("[ " + str(skip_data) + " ]"))
        self.stdout.write(self.style.ERROR("[ " + str(failed_count) + " failed update lender in loan ]"))
        self.stdout.write(self.style.ERROR("[ " + str(failed_data) + " ]"))
