from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand
from datetime import datetime
from juloserver.minisquad.tasks2.dialer_system_task import process_retroload_call_results

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')
        parser.add_argument(
            '-d3', '--csv_file_path', type=str, help='Define system level file path')

    def handle(self, **options):
        """
        command to fetch agent productivity details based on each day
        """
        try:
            starting_date = options['start_date']
            ending_date = options['end_date']
            csv_file_path = options['csv_file_path']
            start_date = datetime.strptime(starting_date, "%d/%m/%Y/%H:%M:%S")
            end_date = datetime.strptime(ending_date, "%d/%m/%Y/%H:%M:%S")
            self.stdout.write(self.style.WARNING(
                'Start Retroloading {} - {}'.format(start_date, end_date)))
            process_retroload_call_results.delay(
                start_time=start_date, end_time=end_date, not_connected_csv_path=csv_file_path)
            self.stdout.write(self.style.WARNING(
                'Sended to Async server {} - {}'.format(start_date, end_date)))

        except Exception as e:
            response = 'Failed to retrieve data from AI rudder for call results'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
