from builtins import str
from juloserver.account.constants import AccountConstant
import logging
import sys
import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.account.models import Account, AccountStatusHistory
from juloserver.account_payment.services.account_payment_related import get_unpaid_account_payment
from juloserver.cfs.constants import CfsActionPointsActivity
from juloserver.cfs.services.core_services import (
    bulk_update_total_points_and_create_history,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'bulk update account status for suspicious account ids from csv'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/suspected_fraud_account_ids.csv'
        self.stdout.write(self.style.WARNING(
            'Start read csv')
        )
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                file_rows = [r for r in csv_rows]
            account_ids = [row.get('suspected_account_id') for row in file_rows]
            accounts = Account.objects.filter(id__in=account_ids)
            self.stdout.write(self.style.WARNING(
                "Total Accounts found from csv - " + str(len(accounts))))
            account_status_histories = []
            action_points_data = []
            for account in accounts:
                account_status_histories.append(
                    AccountStatusHistory(
                        account=account,
                        status_old_id=account.status_id,
                        status_new_id=AccountConstant.STATUS_CODE.application_or_friendly_fraud,
                        change_reason="suspected fraud pulsa/e-wallet"))

                # preapre for processing action points - cfs stuff
                application = account.application_set.last()
                if application and application.eligible_for_cfs:
                    unpaid_account_payments = get_unpaid_account_payment(account.id)
                    amount = 0
                    for account_payment in unpaid_account_payments:
                        amount += account_payment.due_amount
                    data = {
                        'customer_id': account.customer_id,
                        'amount': amount
                    }
                    action_points_data.append(data)
            with transaction.atomic():
                accounts_updated = accounts.update(
                    status_id=AccountConstant.STATUS_CODE.application_or_friendly_fraud)
                histories_created = AccountStatusHistory.objects.bulk_create(
                    account_status_histories)

                bulk_update_total_points_and_create_history(
                    action_points_data, CfsActionPointsActivity.FRAUDSTER)

            self.stdout.write(self.style.SUCCESS("Accounts Updated - " + str(accounts_updated)))
            self.stdout.write(self.style.SUCCESS(
                "Account Histories Created - " + str(len(histories_created))))

            # Action points stuff
            self.stdout.write(self.style.WARNING(
                "Begin processing action points for these fraud accounts..."
            ))
            self.stdout.write(self.style.SUCCESS("Finished processing their action points"))

        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
