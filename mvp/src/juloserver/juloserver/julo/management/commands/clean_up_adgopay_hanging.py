from django.core.management.base import BaseCommand
from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.services.task_services import (
    get_active_autodebet_account,
)
from juloserver.payback.models import GopayAccountLinkStatus
from juloserver.payback.constants import GopayAccountStatusConst
from juloserver.autodebet.services.authorization_services import gopay_autodebet_revocation


class Command(BaseCommand):
    help = 'To clean up hanging autodebit gopay from unlinked from gopay app'

    def handle(self, *args, **options):
        gopay_autodebet_account = get_active_autodebet_account([AutodebetVendorConst.GOPAY])
        if not gopay_autodebet_account.exists():
            return

        account = gopay_autodebet_account.last().account

        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            account=account,
            status=GopayAccountStatusConst.ENABLED,
        )

        if not gopay_account_link.exists():
            gopay_autodebet_revocation(account)
