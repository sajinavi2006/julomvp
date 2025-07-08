import logging
import sys

from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.constants import NEW_WAIVER_APPROVER_GROUPS
from django.contrib.auth.models import Group

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load New reason for refinancing reason'

    def handle(self, *args, **options):
        groups = NEW_WAIVER_APPROVER_GROUPS
        for role_name in groups:
            Group.objects.get_or_create(
                name=role_name
            )
