import csv
import logging
from django.core.management.base import BaseCommand
from datetime import datetime
from juloserver.julo.models import Loan, SkiptraceHistory, Skiptrace
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.account.models import Account

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']

        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter='\t')
                rows = [r for r in csv_rows]

            for row in rows:
                start_ts = None if not row['START_TS'] else datetime.strptime(
                    row['START_TS'], '%Y-%m-%d %H:%M:%S')
                account_id = None if not row['ACCOUNT_ID'] else int(row['ACCOUNT_ID'])
                loan_id = None if not row['LOAN_ID'] else int(row['LOAN_ID'])
                phone_number = row['PHONE_NUMBER']

                print(start_ts, loan_id, account_id)

                if loan_id:
                    loan = Loan.objects.get_or_none(pk=loan_id)
                    if not loan:
                        print("loan id is not found {}".format(loan_id))
                        continue
                    application = loan.application

                    skiptrace_history = SkiptraceHistory.objects.filter(
                        loan=loan,
                        start_ts=start_ts
                    ).last()

                    if not skiptrace_history:
                        print("call result not found for loan_id {} and start_ts {}".format(
                            loan_id, start_ts))
                        continue

                    skiptrace = Skiptrace.objects.filter(
                        phone_number=format_e164_indo_phone_number(phone_number),
                        customer=application.customer).last()

                    if not skiptrace:
                        skiptrace = Skiptrace.objects.create(
                            phone_number=format_e164_indo_phone_number(phone_number),
                            customer=application.customer,
                            application=application)

                    skiptrace_history.skiptrace = skiptrace
                    skiptrace_history.save()

                if account_id:
                    account = Account.objects.get_or_none(pk=account_id)
                    if not account:
                        print("account_id id is not found {}".format(account_id))
                        continue

                    application = account.customer.application_set.last()

                    skiptrace_history = SkiptraceHistory.objects.filter(
                        account=account,
                        start_ts=start_ts
                    ).last()

                    if not skiptrace_history:
                        print("call result not found for account_id {} and start_ts {}".format(
                            loan_id, start_ts))
                        continue

                    skiptrace = Skiptrace.objects.filter(
                        phone_number=format_e164_indo_phone_number(phone_number),
                        customer=application.customer).last()

                    if not skiptrace:
                        skiptrace = Skiptrace.objects.create(
                            phone_number=format_e164_indo_phone_number(phone_number),
                            customer=application.customer,
                            application=application)

                    skiptrace_history.skiptrace = skiptrace
                    skiptrace_history.save()

        except IOError:
            logger.error("could not open given file " + path)
            return
