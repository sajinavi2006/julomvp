import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingMainReason

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load New reason for refinancing reason'

    def handle(self, *args, **options):
        for new_reason in CovidRefinancingConst.NEW_REASON:
            LoanRefinancingMainReason.objects.update_or_create(
                reason=new_reason,
                is_active=True
            )
