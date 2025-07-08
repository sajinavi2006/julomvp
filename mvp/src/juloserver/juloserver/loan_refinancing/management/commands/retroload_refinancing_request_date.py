import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load request_date'

    def handle(self, *args, **options):
        loan_refinancing_requests = LoanRefinancingRequest.objects.all()
        if loan_refinancing_requests:
            for loan_refinancing_request in loan_refinancing_requests:
                loan_refinancing_request.request_date = timezone.localtime(loan_refinancing_request.cdate).date()
                loan_refinancing_request.save()
