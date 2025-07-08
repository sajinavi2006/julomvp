from django.core.management.base import BaseCommand
from django.db import transaction
from juloserver.autodebet.services.authorization_services import (
process_account_revocation,
process_bri_account_revocation,
gopay_autodebet_revocation,
)
from juloserver.autodebet.constants import VendorConst
from juloserver.account.models import Account
from juloserver.account.constants import AccountConstant

class Command(BaseCommand):
    help = 'script to revoke all autodebet for sold off accounts'

    def handle(self, *args, **options):
        accounts=Account.objects.filter(status_id=AccountConstant.STATUS_CODE.sold_off)
        revoke_account_func={
            VendorConst.BCA:process_account_revocation,
            VendorConst.BRI:process_bri_account_revocation,
            VendorConst.GOPAY:gopay_autodebet_revocation,
        }
        for account in accounts:
            with transaction.atomic():
                try:
                    autodebet_accounts=account.autodebetaccount_set.filter(
                        is_use_autodebet=True, vendor__in=VendorConst.LIST
                    )
                    for autodebet_account in autodebet_accounts:
                        revoke_account_func[autodebet_account.vendor](account)
                        self.stdout.write(self.style.SUCCESS(
                            'successfully revoke %s autodebet from account id %d' % (
                            autodebet_account.vendor, account.id
                        )))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(str(e)))
