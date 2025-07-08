from __future__ import division
import logging
import os
import sys
import csv
from builtins import input

from django.conf import settings
from django.utils import timezone
from past.utils import old_div
from datetime import datetime
from django.core.management.base import BaseCommand

from juloserver.account.models import Account
from juloserver.fdc.files import TempDir
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan_selloff.constants import SelloffBatchConst
from juloserver.loan_selloff.models import (
    LoanSelloffBatch,
    LoanSelloff,
)
from juloserver.monitors.notifications import (
    send_message_normal_format,
    slack_notify_and_send_csv_files,
)
from django.db import transaction

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def handle(self, **options):
        # Preparation Process
        current_time = timezone.localtime(timezone.now())
        vendor_name = input("enter vendor name (max 200 character): ")
        if not vendor_name:
            self.stdout.write(self.style.ERROR('vendor name is mandatory'))
            return
        csv_is_correct = False
        file_path = 'null'
        total_data = 0
        while not csv_is_correct:
            #get csv file path
            file_path = input("file must be in csv format\n"
                                  "csv file header must be 'loan_id'\n"
                                  "file only contain loan_id\n"
                                  "enter file path :")
            try:
                with open(file_path, 'r') as csvfile:
                    csv_rows = csv.DictReader(csvfile, delimiter=',')
                    list_reader = list(csv_rows)
                    dict_from_csv = dict(list_reader[0])
                    total_data = len(list_reader)
                    required_columns = [
                        'product', 'account_id', 'loan_id', 'os_total_amount',
                        'os_principal_amount', 'os_interest_amount', 'os_latefee_amount']
                    list_of_column_names = list(dict_from_csv.keys())
                    missing_columns = [col for col in required_columns if
                                       col not in list_of_column_names]

                if missing_columns:
                    self.stdout.write(self.style.ERROR(f"Missing required columns: {missing_columns}"))
                else:
                    self.stdout.write(self.style.SUCCESS('csv file OK'))
                    csv_is_correct = True
            except IOError:
                self.stdout.write(
                    self.style.ERROR("could not open given file  %s please recheck" % file_path))

        parameter = SelloffBatchConst.PRINCIPAL_AND_INTEREST
        pct_of_parameter = float(100)
        execution_schedule_str = str(
            input("enter execution schedule with this format Y-m-d H:M:S : "))
        execution_schedule = datetime.strptime(execution_schedule_str, '%Y-%m-%d %H:%M:%S')
        batch_size = int(input("enter batch size per page : "))
        message_decision = input("if you need update to slack please fill it with y/n : ")
        include_paid_off_decision = input("include paid off y/n : ")
        # Preparation Finish
        self.stdout.write(self.style.SUCCESS('creating Loan Selloff Batch data'))
        decision = input(
            "please review your choices below\n"
            "--------------------------------\n"
            "parameter: %s\n"
            "pct_of_parameter: %s\n"
            "vendor: %s\n"
            "file_path: %s\n"
            "number of loans: %s\n"
            "batch size: %s\n"
            "slack notification update ?: %s\n"
            "execution scheduler: %s\n"
            "include paid off ? : %s\n\n"
            "all good? (y/n): "
            % (
                parameter,
                pct_of_parameter,
                vendor_name,
                file_path,
                total_data,
                batch_size,
                message_decision,
                execution_schedule_str,
                include_paid_off_decision,
            )
        )

        if decision.lower() == 'n':
            self.stdout.write(self.style.ERROR('Please re-run from beginning'))
            return
        with transaction.atomic():
            loan_selloff_batch = LoanSelloffBatch.objects.filter(
                vendor=vendor_name,
                csv_file=file_path, parameter=parameter,
                pct_of_parameter=old_div(pct_of_parameter, 100),
                execution_schedule=execution_schedule
            ).last()
            if not loan_selloff_batch:
                loan_selloff_batch = LoanSelloffBatch.objects.create(
                    parameter=parameter,
                    pct_of_parameter=old_div(pct_of_parameter, 100),
                    vendor=vendor_name,
                    csv_file=file_path, execution_schedule=execution_schedule)

            if not loan_selloff_batch.id:
                self.stdout.write(self.style.ERROR('Error Creating Loan Selloff Batch data'))
                return

            self.stdout.write(self.style.SUCCESS('Success Loan Selloff Batch data'))
            formatted_loan_sell_off = []
            failed_processed = []
            processed_count = 0
            counter = 0
            while list_reader:
                row = list_reader.pop(0)
                data = dict(row)
                account_id = data.get('account_id', None)
                loan_id = data.get('loan_id', None)
                try:
                    total_remaining_principal = int(float(data.get('os_principal_amount', 0)))
                    total_remaining_interest = int(float(data.get('os_interest_amount', 0)))
                    total_remaining_late_fee = int(float(data.get('os_latefee_amount', 0)))
                    total_selloff_amount = int(float(data.get('os_total_amount', 0)))
                    product = data.get('product', '')
                    account = Account.objects.filter(pk=account_id).last()
                    if not account:
                        failed_processed.append([loan_id, account_id, 'Account not Found'])

                    loan = account.loan_set.filter(pk=loan_id).last()
                    if not loan:
                        failed_processed.append([loan_id, account_id, 'Loan not Found'])
                        continue
                    if (
                        loan.status == LoanStatusCodes.PAID_OFF
                        and include_paid_off_decision.lower() == 'n'
                    ):
                        failed_processed.append([loan_id, account_id, 'Loan already Paid off'])
                        continue
                    exist_loan_selloff = LoanSelloff.objects.filter(
                        loan=loan, account=account).last()
                    if exist_loan_selloff:
                        failed_processed.append(
                            [loan_id, account_id, 'loan already exists in loanselloff'])
                        continue

                    formatted_loan_sell_off.append(
                        LoanSelloff(
                            loan_selloff_batch=loan_selloff_batch,
                            loan=loan,
                            account=account,
                            principal_at_selloff=total_remaining_principal,
                            interest_at_selloff=total_remaining_interest,
                            late_fee_at_selloff=total_remaining_late_fee,
                            loan_selloff_proceeds_value=total_selloff_amount,
                            product=product
                        )
                    )
                    counter += 1
                    # Check if the batch size is reached, then perform the bulk_create
                    if counter >= batch_size:
                        LoanSelloff.objects.bulk_create(formatted_loan_sell_off)
                        processed_count += counter
                        self.stdout.write(
                            self.style.SUCCESS("processed {} data".format(batch_size)))
                        # Reset the counter and the list for the next batch
                        counter = 0
                        formatted_loan_sell_off = []
                except Exception as e:
                    failed_processed.append([loan_id, account_id, str(e)])

            if formatted_loan_sell_off:
                processed_count += counter
                LoanSelloff.objects.bulk_create(formatted_loan_sell_off)

            self.stdout.write(
                self.style.SUCCESS("Finish Process data {}".format(processed_count)))

            if not processed_count:
                raise Exception("dont have data to process for {}".format(file_path))

        if message_decision.lower() == 'n':
            self.stdout.write(self.style.ERROR('Finish without update to slack'))
            return

        message = "Finish Uploading {} with loan sell off batching id {}".format(
                    file_path, loan_selloff_batch.id)
        if settings.ENVIRONMENT != 'prod':
            header = "Testing Purpose from {} \n".format(settings.ENVIRONMENT)
            message = header + message
        channels = '#loan-selloff-uploading-status'
        if failed_processed:
            with TempDir() as tempdir:
                file_name = 'failed_processed_selloff_{}.csv'.format(
                    str(current_time.strftime("%Y-%m-%d-%H:%M")))
                failed_processed_csv_file = os.path.join(tempdir.path, file_name)
                with open(failed_processed_csv_file, 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(
                        ['loan_id', 'account_id', 'message'])  # Write the header row
                    writer.writerows(failed_processed)  # Write the data rows
                message = message + ' with some failure please check'
                slack_notify_and_send_csv_files(
                    message=message,
                    csv_path=failed_processed_csv_file, channel=channels,
                    file_name=file_name)
            send_message_normal_format(
                message="Finish Uploading {} with loan sell off batching id {}".format(
                    file_path, loan_selloff_batch.id),
                channel=channels
            )
