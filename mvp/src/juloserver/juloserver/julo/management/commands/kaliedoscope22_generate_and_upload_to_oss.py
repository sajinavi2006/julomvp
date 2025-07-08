from __future__ import print_function
import logging
import sys
import csv

from django.core.management.base import BaseCommand

from juloserver.streamlined_communication.tasks import kaliedoscope22_generate_and_upload_to_oss

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                for row in csv_rows:
                    try:
                        kaliedoscope22_generate_and_upload_to_oss.delay(row)
                    except Exception as e:
                        logger.exception({
                            'method': 'kaliedoscope22_generate_and_upload_to_oss',
                            'exception': str(e)})
                        self.stdout(str(e))
        except Exception as e:
            logger.exception({
            'method': 'kaliedoscope22_generate_and_upload_to_oss',
            'exception': str(e)})
            self.stdout(str(e))
