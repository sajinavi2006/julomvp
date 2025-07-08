import ast
import logging
import sys
from datetime import datetime

from django_bulk_update.helper import bulk_update
from django.core.management.base import BaseCommand

from juloserver.account_payment.models import AccountPaymentNote
from juloserver.julo.models import SkiptraceHistory, Payment
from juloserver.julo.utils import masking_phone_number_value
from juloserver.minisquad.models import CollectionRiskSkiptraceHistory
from juloserver.pii_vault.collection.services import mask_phone_number_sync

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--end_datetime', type=str, help='Define end date dd/mm/yyyy H')

    def handle(self, **options):
        try:
            end_time = options['end_datetime']
            if not end_time:
                self.stdout.write(self.style.ERROR('End date must be provided'))
                return

            end_time = datetime.strptime(end_time, '%m/%d/%Y %H')
            self.stdout.write(self.style.WARNING('End date is {}'.format(end_time)))
            self.stdout.write(self.style.WARNING('START BACKFILL PII'))
            table_tobe_update = [
                'collection_risk_skiptrace_history',
                'skiptrace_history',
                'account_payment_note',
                'payment',
            ]
            for update_item in table_tobe_update:
                if update_item == 'collection_risk_skiptrace_history':
                    data = CollectionRiskSkiptraceHistory.objects.filter(cdate__lte=end_time)
                elif update_item == 'skiptrace_history':
                    data = SkiptraceHistory.objects.filter(cdate__lte=end_time)
                elif update_item == 'account_payment_note':
                    data = AccountPaymentNote.objects.filter(cdate__lte=end_time)
                else:
                    data = Payment.objects.filter(cdate__lte=end_time)

                updated_records = []
                batch_size = 5000
                counter = 0
                processed_data = 0
                total_data = data.count()
                for record in data:
                    if update_item in ['collection_risk_skiptrace_history', 'skiptrace_history']:
                        record.notes = mask_phone_number_sync(record.notes)
                        update_fields = ['notes']
                    elif update_item == 'account_payment_note':
                        update_fields = ['note_text']
                        record.note_text = mask_phone_number_sync(record.note_text)
                        if record.extra_data:
                            masked_json = mask_phone_number_sync(record.extra_data, True)
                            record.extra_data = ast.literal_eval(masked_json)
                            update_fields.append('extra_data')
                    else:
                        record.ptp_robocall_phone_number = masking_phone_number_value(
                            record.ptp_robocall_phone_number
                        )
                        update_fields = ['ptp_robocall_phone_number']

                    updated_records.append(record)
                    counter += 1
                    if counter >= batch_size:
                        bulk_update(updated_records, update_fields=update_fields)
                        processed_data += counter

                        counter = 0
                        updated_records = []
                        self.stdout.write(
                            self.style.SUCCESS(
                                "BACKFILL PII {} processed {}/{}".format(
                                    update_item, processed_data, total_data
                                )
                            )
                        )
                if updated_records:
                    processed_data += counter
                    bulk_update(updated_records, update_fields=update_fields)
                    self.stdout.write(
                        self.style.SUCCESS(
                            "BACKFILL PII {} processed {}/{}".format(
                                update_item, processed_data, total_data
                            )
                        )
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        "BACKFILL PII {} SUCCESS {}/{}".format(
                            update_item, processed_data, total_data
                        )
                    )
                )
            self.stdout.write(self.style.SUCCESS('SUCCESS BACKFILL PII'))

        except Exception as e:
            response = 'failed to backfill calllogpoc and risk'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({'status': response, 'reason': error_msg})
            raise e
