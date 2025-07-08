from builtins import str
import logging
import json
import sys

from django.core.management.base import BaseCommand
from datetime import datetime

from juloserver.julo.clients import get_julo_centerix_client
# from juloserver.minisquad.tasks import agent_productiviy_details_from_centerix

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('-d1', '--start_date', type=str, help='Define start date')
        parser.add_argument('-d2', '--end_date', type=str, help='Define end date')

    def handle(self, **options):
        """
        command to fetch agent productivity details based on each day
        """
        try:
            centerix_client = get_julo_centerix_client()
            starting_date = options['start_date']
            ending_date = options['end_date']
            start_date = datetime.strptime(starting_date, "%d/%m/%Y").date()
            end_date = datetime.strptime(ending_date, "%d/%m/%Y").date()
            results = centerix_client.get_agent_productiviy_details_from_centerix(start_date, end_date)
            for result in results:
                # agent_productiviy_details_from_centerix(result)
                pass

        except Exception as e:
            response = 'Failed to retrieve data from centerix for agent productivity'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
