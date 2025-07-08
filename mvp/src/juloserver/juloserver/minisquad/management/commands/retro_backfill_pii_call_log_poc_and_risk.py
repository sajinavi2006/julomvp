from builtins import str
import logging
import sys
from datetime import datetime
from django_bulk_update.helper import bulk_update
from django.core.management.base import BaseCommand

from juloserver.julo.models import CallLogPocAiRudderPds
from juloserver.julo.utils import masking_phone_number_value
from juloserver.minisquad.models import RiskCallLogPocAiRudderPds

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--end_datetime', type=str, help='Define end date dd/mm/yyyy H')

    def handle(self, **options):
        """
        command to fetch agent productivity details based on each day
        example run :
        ./manage.py retro_backfill_pii_call_log_poc_and_risk --end_datetime='20/02/2024 10'
        """
        try:
            input_ending_time = options['end_datetime']
            if not input_ending_time:
                self.stdout.write(self.style.ERROR('end_datetime cannot be null'))
                return

            ending_time = datetime.strptime(input_ending_time, "%d/%m/%Y %H")
            self.stdout.write(self.style.WARNING(ending_time))
            self.stdout.write(self.style.WARNING('STARTING BACKFILL PII'))
            tobe_update_data = ["j1", "risk"]
            for update_item in tobe_update_data:
                self.stdout.write(self.style.WARNING("BACKFILL PII {}".format(update_item)))
                if update_item == "j1":
                    back_fill_data = CallLogPocAiRudderPds.objects.filter(cdate__lte=ending_time)
                else:
                    back_fill_data = RiskCallLogPocAiRudderPds.objects.filter(
                        cdate__lte=ending_time
                    )

                updated_records = []
                batch_size = 5000
                counter = 0
                processed_data_count = 0
                total_data = back_fill_data.count()
                for item in back_fill_data.iterator():
                    item.phone_number = masking_phone_number_value(item.phone_number)
                    item.main_number = masking_phone_number_value(item.main_number)
                    updated_records.append(item)
                    counter += 1
                    # Check if the batch size is reached, then perform the bulk_create
                    if counter >= batch_size:
                        bulk_update(updated_records, update_fields=['phone_number', 'main_number'])
                        processed_data_count += counter
                        # Reset the counter and the list for the next batch
                        counter = 0
                        updated_records = []
                        self.stdout.write(
                            self.style.SUCCESS(
                                "BACKFILL PII {} processed {}/{}".format(
                                    update_item, processed_data_count, total_data
                                )
                            )
                        )

                if updated_records:
                    processed_data_count += counter
                    bulk_update(updated_records, update_fields=['phone_number', 'main_number'])
                    self.stdout.write(
                        self.style.SUCCESS(
                            "BACKFILL PII {} processed {}/{}".format(
                                update_item, processed_data_count, total_data
                            )
                        )
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        "BACKFILL PII {} SUCCESS {}/{}".format(
                            update_item, processed_data_count, total_data
                        )
                    )
                )
            self.stdout.write(self.style.SUCCESS('SUCCESS BACKFILL PII'))

        except Exception as e:
            response = 'failed to backfill calllogpoc and risk'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({'status': response, 'reason': error_msg})
            raise e
