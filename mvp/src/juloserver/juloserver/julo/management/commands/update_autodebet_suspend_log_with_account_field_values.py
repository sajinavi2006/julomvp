from django.core.management.base import BaseCommand

from juloserver.autodebet.models import AutodebetSuspendLog


class Command(BaseCommand):
    help = 'Helps to update the autodebet suspend log table with account field value'

    def handle(self, *args, **options):
        autodebet_suspend_logs = AutodebetSuspendLog.objects.filter(
            account__isnull=True
        ).select_related('autodebet_account')
        for autodebet_suspend_log in autodebet_suspend_logs.iterator():
            autodebet_suspend_log.update_safely(
                account=autodebet_suspend_log.autodebet_account.account
            )
