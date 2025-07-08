import logging
import os
import sys
import tempfile
import json
import shutil

from django.core.management.base import BaseCommand
from django.conf import settings
from juloserver.utilities.models import DisbursementTrafficControl
from juloserver.utilities.constants import CommonVariables

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load disbursement traffic setting into django admin'

    def handle(self, *args, **options):
        disbursement_traffic = DisbursementTrafficControl.objects.filter(
            rule_type=CommonVariables.RULE_DISBURSEMENT_TRAFFIC).last()
        if not disbursement_traffic:
            rules = [
                {"key": "application_id", "condition": "#nth:-2:6,7,8",
                    "success_value": "xfers", "is_active": True},
                {"key": "application_id", "condition": "#nth:-2:1,2,3,4,5",
                    "success_value": "instamoney", "is_active": True},
                {"key": "application_id", "condition": "#nth:-2:0",
                    "success_value": "bca", "is_active": True},
            ]
            for rule in rules:
                DisbursementTrafficControl.objects.create(
                    rule_type=CommonVariables.RULE_DISBURSEMENT_TRAFFIC,
                    is_active=rule['is_active'],
                    key=rule['key'],
                    condition=rule['condition'],
                    success_value=rule['success_value'])
            self.stdout.write(self.style.SUCCESS('Success'))
        else:
            self.stdout.write("Nothing to apply")
