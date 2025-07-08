import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from juloserver.qris.constants import QrisTransactionStatus
from juloserver.qris.tasks import bulk_process_callback_transaction_status_from_amar_task


class Command(BaseCommand):
    help = 'Manually update amar transaction status from loans provided'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv_path',
            type=str,
            help='Path to the CSV file containing loan ids and statuses',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Start updating transaction status"))

        csv_path = options['csv_path']

        if not csv_path:
            self.stdout.write(self.style.ERROR("Csv path not provided"))
            return

        # Read loan IDs from the CSV file
        loan_status_map = {}
        try:
            data = pd.read_csv(csv_path)
        except Exception as e:
            raise CommandError(f"Error reading CSV file: {e}")

        # Validate required columns
        if not {'loan_id', 'status'}.issubset(data.columns):
            raise CommandError("CSV file must contain 'loan_id' and 'status' columns.")

        # Validate status values
        valid_statuses = {QrisTransactionStatus.FAILED, QrisTransactionStatus.SUCCESS}
        invalid_status_rows = data[~data['status'].isin(valid_statuses)]
        if not invalid_status_rows.empty:
            raise CommandError(
                (
                    f"Invalid status values found for the following loan_ids: "
                    f"{invalid_status_rows[['loan_id', 'status']].to_dict(orient='records')}"
                )
            )

        # Group by loan_id and check for conflicting statuses
        conflicts = data.groupby('loan_id')['status'].nunique()
        conflicting_loan_ids = conflicts[conflicts > 1].index.tolist()

        if conflicting_loan_ids:
            raise CommandError(f"Conflicting statuses found for loan_ids: {conflicting_loan_ids}")

        loan_status_map = (
            data.drop_duplicates(subset=['loan_id']).set_index('loan_id')['status'].to_dict()
        )

        bulk_process_callback_transaction_status_from_amar_task.delay(
            loan_status_map=loan_status_map,
        )

        self.stdout.write(
            self.style.SUCCESS("Finished trigger async task for updating qris loan statuses")
        )
        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Please check any issue on sentry: "
                    "bulk_process_callback_transaction_status_from_amar_task()"
                )
            )
        )
