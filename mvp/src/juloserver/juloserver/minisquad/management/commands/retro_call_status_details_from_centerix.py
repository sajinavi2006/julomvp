from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand
from datetime import datetime

from juloserver.julo.clients import get_julo_centerix_client

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')

    def handle(self, **options):
        """
        command to fetch call status details like abandon by user, abandon by system ,
        null etc. to skiptrace tables and centrix log table based on each day
        """
        try:
            centerix_client = get_julo_centerix_client()
            starting_date = options['start_date']
            ending_date = options['end_date']
            start_date = datetime.strptime(starting_date, "%d/%m/%Y").date()
            end_date = datetime.strptime(ending_date, "%d/%m/%Y").date()
            centerix_client.get_call_status_details_from_centerix(start_date, end_date)
        except Exception as e:
            response = 'Failed to retrieve data from centerix'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
