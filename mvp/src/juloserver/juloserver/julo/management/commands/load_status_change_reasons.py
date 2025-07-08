import logging
import sys

from django.core.management.base import BaseCommand

from ...models import StatusLookup
from ...models import ChangeReason
from ...statuses import Statuses

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'load status change reason table'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("======================================"))
        self.stdout.write(self.style.SUCCESS("load change reason begin"))
        self.stdout.write(self.style.SUCCESS("======================================"))
        for status in Statuses:
            status_lookup = StatusLookup.objects.filter(status_code=status.code).first()
            self.stdout.write(self.style.SUCCESS("load reason for status %s" % status_lookup.status_code))
            self.stdout.write(self.style.SUCCESS("-------------------------------------"))
            if status_lookup:
                change_reasons = status.change_reasons
                for reason in change_reasons:
                    reason_exist = ChangeReason.objects.filter(reason=reason,
                                                               status=status)
                    if not reason_exist:
                        ChangeReason.objects.create(reason=reason, status=status_lookup)
                        self.stdout.write(self.style.SUCCESS("create %s" % reason))
