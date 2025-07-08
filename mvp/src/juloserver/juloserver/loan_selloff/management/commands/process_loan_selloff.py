from __future__ import division
from builtins import input
from past.utils import old_div
import logging
import sys
import csv

from django.utils import timezone
from django.db.models import Q

from django.core.management.base import BaseCommand
from juloserver.loan_selloff.models import LoanSelloffBatch
from juloserver.loan_selloff.services import process_loan_selloff_by_loan_id

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def handle(self, **options):
        choices = [x[0] for x in LoanSelloffBatch.PARAMETER_CHOICES]

        # get parameter
        parameter_id = input("1. %s\n2. %s\n3. %s\nEnter paramater type number: " % tuple(choices))
        try:
            parameter_id = int(parameter_id)
        except ValueError:
            self.stdout.write(self.style.ERROR('wrong parameter choices'))
            return
        if parameter_id < 1 or parameter_id > len(choices):
            self.stdout.write(self.style.ERROR('wrong parameter choices'))
            return

        #get pct_of_parameter
        pct_of_parameter = input("enter percentage of parameter without percent symbol e.g. 2.76 : ")
        try:
            pct_of_parameter = float(pct_of_parameter)
        except ValueError:
            self.stdout.write(self.style.ERROR('wrong pct_of_parameter'))
            return

        #get vendor_name
        vendor = input("enter vendor name (max 200 character): ")
        if not vendor:
            self.stdout.write(self.style.ERROR('vendor name is mandatory'))
            return
        csv_is_correct = False
        while not csv_is_correct:
            #get csv file path
            file_path = input("file must be in csv format\n"
                                  "csv file header must be 'loan_id'\n"
                                  "file only contain loan_id\n"
                                  "enter file path :")
            try:
                with open(file_path, 'r') as csvfile:
                    csv_rows = csv.DictReader(csvfile, delimiter=',')
                    rows = [r for r in csv_rows]
                if rows[0].get('loan_id'):
                    self.stdout.write(self.style.SUCCESS('csv file OK'))
                    csv_is_correct = True
                else:
                    self.stdout.write(self.style.ERROR("csv header must be 'loan_id'"))
            except IOError:
                self.stdout.write(
                    self.style.ERROR("could not open given file  %s please recheck" % file_path))

        parameter = choices[parameter_id-1]
        decision = input("please review your choices below\n"
                             "--------------------------------\n"
                             "parameter: %s\n"
                             "pct_of_parameter: %s\n"
                             "vendor: %s\n"
                             "file_path: %s\n"
                             "number of loans: %s\n\n"
                             "all good? (y/n): " % (parameter, pct_of_parameter, vendor, file_path, len(rows)))
        if decision.lower() == 'y':
            self.stdout.write(self.style.SUCCESS('creating Loan Selloff Batch data'))
            exist_loan_selloff_batchs = LoanSelloffBatch.objects.filter(
                (Q(parameter=parameter) & Q(pct_of_parameter=old_div(pct_of_parameter, 100))) | Q(csv_file=file_path)
            )
            if exist_loan_selloff_batchs:
                loan_selloff_batch_found = False
                while not loan_selloff_batch_found:
                    self.stdout.write(self.style.WARNING('exist Loan Selloff Batch data found with similar data'))
                    for num, obj in enumerate(exist_loan_selloff_batchs, start=1):
                        self.stdout.write(self.style.WARNING(
                            '%s. cdate:%s, vendor: %s, parameter : %s, pct_of_parameter : %s%%' % (
                                num,
                                timezone.localtime(obj.cdate),
                                obj.vendor,
                                obj.parameter,
                                obj.pct_of_parameter*100
                            )
                        ))
                    choice = input("please enter your choices number or enter 'c' to create new: ")
                    if choice.isdigit():
                        index = int(choice) - 1
                        if index < len(exist_loan_selloff_batchs):
                            loan_selloff_batch = exist_loan_selloff_batchs[index]
                            loan_selloff_batch_found = True
                    else:
                        if choice == 'c':
                            loan_selloff_batch = LoanSelloffBatch.objects.create(
                                parameter=parameter,
                                pct_of_parameter=old_div(pct_of_parameter, 100),
                                vendor=vendor,
                                csv_file=file_path
                            )
                            loan_selloff_batch_found = True
                        else:
                            self.stdout.write(self.style.ERROR('Please re-run from beginning'))
                            return
            else:
                loan_selloff_batch = LoanSelloffBatch.objects.create(
                    parameter=parameter,
                    pct_of_parameter=old_div(pct_of_parameter, 100),
                    vendor=vendor,
                    csv_file=file_path
                )
            if loan_selloff_batch.id:
                for row in rows:
                    status, msg = process_loan_selloff_by_loan_id(loan_selloff_batch, row['loan_id'])
                    if status:
                        self.stdout.write(self.style.SUCCESS(msg))
                    else:
                        self.stdout.write(self.style.ERROR(msg))
        else:
            self.stdout.write(self.style.ERROR('Please re-run from beginning'))