from django.core.management.base import BaseCommand
from ...models import Disbursement

class Command(BaseCommand):

    help = 'retroactively external_id on disbursement table'

    def handle(self, *args, **options):
        disbursements = Disbursement.objects.all()
        for disbursement in disbursements:
            disbursement.external_id = disbursement.loan.application.application_xid
            disbursement.retry_time = 0
            disbursement.save()
        self.stdout.write(self.style.SUCCESS('Successfully retroload external_id'))
