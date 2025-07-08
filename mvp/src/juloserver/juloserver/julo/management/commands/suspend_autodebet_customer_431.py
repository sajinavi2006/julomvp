from django.core.management.base import BaseCommand

from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.constants import AutodebetStatuses
from juloserver.account.constants import AccountConstant


def suspend_autodebet_for_account_431():
    AutodebetAccount.objects.filter(
        status__in=[AutodebetStatuses.REGISTERED, AutodebetStatuses.PENDING_REGISTRATION],
        is_use_autodebet=True,
        is_suspended=False,
        account__status_id__gte=AccountConstant.STATUS_CODE.deactivated,
    ).update(
        is_suspended=True,
    )


class Command(BaseCommand):
    help = (
        'Helps to suspend all autodebet accounts that belongs to customer with status 431 and above'
    )

    def handle(self, *args, **options):
        suspend_autodebet_for_account_431()
