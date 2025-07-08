from django.core.management.base import BaseCommand
from juloserver.julo.models import CootekRobocall
from juloserver.sdk.services import xls_to_dict
import datetime
import pytz
import time
import logging
from django.conf import settings
import os
import os.path
logger = logging.getLogger(__name__)



class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        if os.path.isfile(path) is None:
            logger.info({
                "action": "insert_old_cootek_data",
                "message": "file is not exists"
            })
        else:
            delimiter = '|'
            excel_data = xls_to_dict(path, delimiter)


        cootek_data = []
        for idx_sheet, sheet in enumerate(excel_data):
            for idx_rpw, row in enumerate(excel_data[sheet]):
                cootek = CootekRobocall()
                cootek_event_date = datetime.datetime.strptime(row['cootek_event_date'], "%Y/%m/%d %H:%M:%S")
                cootek.task_id = row['cootek_event_id']
                cootek.cootek_event_date = cootek_event_date
                cootek.campaign_or_strategy = row['campaign_or_strategy']
                cootek.cootek_event_type = row['cootek_event_type']
                cootek.call_to = row['call_to']
                cootek.ring_type = row['ring_type']
                cootek.robot_type = row['robot_type']
                cootek.intention = row['intention']
                cootek.duration = row['duration']
                cootek.hang_type = row['hang_type']
                cootek.round = row['round']

                cootek_data.append(cootek)

        CootekRobocall.objects.bulk_create(cootek_data)

        self.stdout.write(self.style.SUCCESS('Retroload data successfully'))
