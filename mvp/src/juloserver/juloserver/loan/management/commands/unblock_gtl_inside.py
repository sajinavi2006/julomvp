import pandas as pd
from django.core.management.base import BaseCommand
from juloserver.account.models import AccountGTL
from juloserver.loan.tasks.loan_related import update_gtl_status_bulk


class Command(BaseCommand):
    help = 'Unblocks GTL Inside accounts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--account_ids',
            type=str,
            help='Comma-separated list of account IDs to unblock GTL Inside',
        )
        parser.add_argument(
            '--csv_path',
            type=str,
            help='Path to the CSV file containing account IDs to unblock GTL Inside',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Start unblocking GTL Inside"))

        old_value = True
        new_value = False

        csv_path = options['csv_path']
        account_ids_str = options['account_ids']

        if not csv_path and not account_ids_str:
            self.stdout.write(
                self.style.ERROR("Either --account_ids or --csv_path must be provided")
            )
            return

        if csv_path:
            # Read account IDs from the CSV file
            try:
                data = pd.read_csv(csv_path)
                input_account_ids = data['account_id'].dropna().astype(int).tolist()
            except Exception as e:
                self.stdout.write(self.style.ERROR("Error reading CSV file: {}".format(e)))
                return
        elif account_ids_str:
            input_account_ids = [int(id_str) for id_str in account_ids_str.split(',')]

        print("account_ids to be unblocked inside: ", input_account_ids)

        # Filter account ids
        gtl_ids = AccountGTL.objects.filter(
            account_id__in=input_account_ids,
        ).values_list('id', flat=True)

        update_gtl_status_bulk(
            gtl_ids=gtl_ids,
            field_name='is_gtl_inside',
            old_value=old_value,
            new_value=new_value,
        )

        self.stdout.write(self.style.SUCCESS("Finished unblocking GTL Inside"))
