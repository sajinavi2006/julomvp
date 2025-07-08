from django.utils import timezone
from bulk_update.helper import bulk_update
from django.core.management.base import BaseCommand
from juloserver.cfs.constants import CfsActionId, CfsProgressStatus
from juloserver.cfs.models import CfsActionAssignment


class Command(BaseCommand):
    help = "update failed mission"

    def handle(self, *args, **options):
        now = timezone.localtime(timezone.now())
        cfs_action_assignments = CfsActionAssignment.objects.filter(
            action_id=CfsActionId.VERIFY_ADDRESS,
            progress_status=CfsProgressStatus.START
        )
        for action_assignment in cfs_action_assignments:
            action_assignment.progress_status = CfsProgressStatus.FAILED
            action_assignment.udate = now
        bulk_update(
            cfs_action_assignments, update_fields=['progress_status', 'udate'], batch_size=500
        )
