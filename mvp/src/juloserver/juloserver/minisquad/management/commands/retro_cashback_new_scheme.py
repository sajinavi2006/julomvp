import sys
import logging
from typing import Any
from django.core.management.base import BaseCommand
from juloserver.minisquad.tasks import populate_account_id_for_new_cashback_experiment

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    """
    command to populate eligible account id for new cashback new scheme
    integrate with growthbook for determine control/experiment group
    and store the result to our experiment_group table
    """
    def handle(self, *args: Any, **options: Any):
        try:
            self.stdout.write(self.style.WARNING(
                'Start retroloading data for cashback new scheme'))
            populate_account_id_for_new_cashback_experiment.delay()
            self.stdout.write(self.style.WARNING(
                'Processed by async task'))
        except Exception as err:
            error_msg = 'Something went wrong -{}'.format(str(err))
            self.stdout.write(self.style.ERROR(error_msg))
            raise err
