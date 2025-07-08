from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.minisquad.services2.airudder import retro_agent_productivity

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-d1',
            '--csv_filepath',
            type=str,
            help='Define system level file path',
        )
        parser.add_argument(
            '-d2',
            '--batch_size',
            type=int,
            help='Define bulk batch size',
        )
        parser.add_argument(
            '-d3',
            '--chunk_size',
            type=int,
            help='Define bulk chunk size',
        )

    def handle(self, **options):
        """
        command to fetch agent productivity details based on each day
        """
        try:
            csv_filepath = options['csv_filepath']
            batch_size = options['batch_size']
            chunk_size = options['chunk_size']
            self.stdout.write(self.style.WARNING('start running retroload agent log'))
            retro_agent_productivity(csv_filepath, batch_size, chunk_size)
            self.stdout.write(self.style.WARNING('finish process retroload agent log'))
        except Exception as e:
            response = 'failed to retroload agent log'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
