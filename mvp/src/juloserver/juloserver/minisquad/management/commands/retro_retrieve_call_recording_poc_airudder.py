from builtins import str
import logging
import sys
from django.utils import timezone
from datetime import timedelta

from django.core.management.base import BaseCommand
from datetime import datetime
from juloserver.minisquad.tasks2.dialer_system_task import (
    process_retrieve_call_recording_data,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')

    def handle(self, **options):
        """
        command to fetch call recording result based on each day
        """
        try:
            starting_date = options['start_date']
            ending_date = options['end_date']
            start_date = datetime.strptime(starting_date, "%d/%m/%Y/%H:%M:%S")
            end_date = datetime.strptime(ending_date, "%d/%m/%Y/%H:%M:%S")

            self.stdout.write(self.style.WARNING(
                'Start Retroloading {} - {}'.format(start_date, end_date)))
            process_retrieve_call_recording_data.delay(
                start_date, end_date, from_retro=True)
            self.stdout.write(self.style.WARNING(
                'Sended to Async server {} - {}'.format(start_date, end_date)))

        except Exception as e:
            response = 'Failed to retrieve call recording result from AI rudder'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
