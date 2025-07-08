import csv
import logging
from time import sleep
from juloserver.julo.models import Loan, EmailHistory
from juloserver.julo.clients import get_voice_client
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'blast robocall covid campaign'

    def handle(self, *args, **options):
        csv_file_name = '../../email_blast/robocall_covid_19/loan_app_data.csv'
        with open(csv_file_name, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            rows = [r for r in csv_rows]
            headers = csv_rows.fieldnames

        voice_client = get_voice_client()
        for idx, row in enumerate(rows):
            # pass for skip and done status
            if row['result'] in ['skip', 'done']:
                continue

            row['result'] = 'skip'
            loan = Loan.objects.get_or_none(pk=row['loan_id'])
            if loan and loan.is_active:
                # check email status
                read_email_already = EmailHistory.objects.filter(application_id=loan.application_id,
                                                                 template_code='email_OSP_Recovery_Apr2020',
                                                                 status__in=['open', 'click']).exists()
                if not read_email_already:
                    # send robocall request
                    result = voice_client.covid_19_campaign(loan.application.mobile_phone_1, loan.id)
                    if result:
                        row['result'] = 'done'
                    else:
                        row['result'] = 'error'

            rows[idx] = row
            with open(csv_file_name, 'w') as csvfile:
                csv_writer = csv.DictWriter(csvfile, fieldnames=headers)
                csv_writer.writeheader()
                csv_writer.writerows(rows)
            sleep(1)
        self.stdout.write(self.style.SUCCESS(
            'Successfully load data')
        )
