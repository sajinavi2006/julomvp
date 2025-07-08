from __future__ import print_function
import logging
import sys
import csv
from django.conf import settings
from django.core.management.base import BaseCommand

from juloserver.streamlined_communication.tasks import (
    blast_emails_for_kaliedoscope22_customers)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')
        parser.add_argument('-ev', '--environment', type=str, help='Choose Environment from the following four : prod, staging, uat, dev')

    def handle(self, **options):
        path = options['file']
        environment = options.get('environment')
        if environment and environment not in ['prod', 'staging', 'uat', 'dev']:
            print('Wrong environemnt selected, see help for more information')
            return
        if not environment:
            environment = str(settings.ENVIRONMENT)
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                for row in csv_rows:
                    try:
                        blast_emails_for_kaliedoscope22_customers.delay(row, environment)
                    except Exception as e:
                        logger.exception({
                            'method': 'kaliedoscope_blast_emails_22',
                            'exception': str(e),
                            'row_data': row})
                        self.stdout(str(e))
        except Exception as e:
            logger.exception({
                'method': 'kaliedoscope_blast_emails_22',
                'exception': str(e)})
            self.stdout(str(e))
