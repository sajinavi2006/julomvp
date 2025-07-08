from django.core.management.base import BaseCommand
import csv
import logging
import sys

from juloserver.minisquad.tasks2 import bulk_create_collection_bucket_inhouse_vendor_async
from juloserver.minisquad.utils import batch_list

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-f', '--path_file', type=str, help='Define file name')
        parser.add_argument(
            '-f', '--data_per_looping', type=int, help='Define limit process per looping'
        )
        parser.add_argument('-f', '--queue', type=str, help='define queue')

    def handle(self, **options):
        fname = 'RETROLOAD_DATA_CBIV_VENDOR'
        path = options['path_file']
        data_per_looping = options['data_per_looping']
        retro_queue = options.get('queue', 'collection_dialer_high')
        with open(path, 'r') as csvfile:
            csv_rows = csv.DictReader(csvfile, delimiter=',')
            rows = [r for r in csv_rows]

        logger.info(
            {
                'fn_name': fname,
                'action': 'retroload_CBIV',
                'status': 'start retroload_CBIV',
            }
        )
        for account_payment_ids in batch_list(rows, int(data_per_looping)):
            bulk_create_collection_bucket_inhouse_vendor_async.apply_async(
                (account_payment_ids,), queue=retro_queue
            )

        logger.info(
            {
                'fn_name': fname,
                'action': 'retroload_CBIV',
                'status': 'finish retroload_CBIV',
            }
        )
