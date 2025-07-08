import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.services.offer_related import reorder_recommendation_by_status

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load request_date'

    def handle(self, *args, **options):
        reorder_recommendation_by_status(CovidRefinancingConst.GRAVEYARD_STATUS)
