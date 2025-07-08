from __future__ import division
from builtins import str
import logging
import sys
import pandas as pd
import os
from django.core.management.base import BaseCommand
from juloserver.minisquad.tasks2.notifications import send_wl_blast_for_b5
from juloserver.julo.constants import EmailDeliveryAddress

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    """
    Arg examples:
    path = '/path/csv_file.csv'
    api_key = 'SG.*****'
    send_from = 'collections@julofinance.com'
    queue = 'retrofix_normal'
    """

    def add_arguments(self, parser):
        parser.add_argument('-f', '--path', type=str, help='Define CSV path')
        parser.add_argument('-f', '--api_key', type=str, help='API key sendgrid')
        parser.add_argument('-f', '--send_from', type=str, help='Email sender from')
        parser.add_argument('-f', '--queue', type=str, help='To which queue')

    def handle(self, **options):
        csv_path = options.get('path')
        sendgrid_api_key = options.get('api_key')
        client_email_from = options.get('send_from', EmailDeliveryAddress.COLLECTIONS_JTF)
        queue = options.get('queue', 'retrofix_normal')

        self.stdout.write('Start')

        df = pd.read_csv(csv_path)
        self.stdout.write(str(df.head()))

        if df.empty:
            self.stdout.write(self.style.ERROR('CSV file is empty'))
            return

        for index, row in df.iterrows():
            customer_id = row['customer_id']
            fullname_raw = row['customer_full_name']
            due_amount_raw = row['all_due_amount']
            all_skrtp_number = row['all_skrtp_number']
            if not all_skrtp_number:
                logger.error(
                    {
                        'error': 'skipped due to skrpt not found',
                        'julo_email_client': julo_email_client,
                        'index': index,
                    }
                )

            send_wl_blast_for_b5.apply_async(
                kwargs={
                    'customer_id': customer_id,
                    'fullname_raw': fullname_raw,
                    'due_amount_raw': due_amount_raw,
                    'all_skrtp_number': all_skrtp_number,
                    'sendgrid_api_key': sendgrid_api_key,
                    'client_email_from': client_email_from,
                    'index': index,
                },
                queue=queue,
            )

        self.stdout.write('Finish')
