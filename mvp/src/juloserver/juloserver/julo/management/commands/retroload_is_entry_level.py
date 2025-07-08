from juloserver.cfs.models import EntryGraduationList
from juloserver.account.models import AccountProperty
from juloserver.julo.models import Application
from django.core.management.base import BaseCommand
from juloserver.entry_limit.models import EntryLevelLimitHistory
from juloserver.account.models import Account
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Retroload for column ops.account_property.is_entry_level"

    def handle(self, *args, **options):
        """
        Find list of accounts/customers who have gratuated from sb.graduation_list
        Subtract that from ops.entry_level_limit_history => result accounts
        update result accounts: AccountProperty.is_entry_level=True

        """

        self.stdout.write('Start retroloading for column "account_property.is_entry_level"...')

        graduated_account_ids = EntryGraduationList.objects.all()\
            .values_list('account_id', flat=True)

        excluded_application_ids = Application.objects.filter(
            account_id__in=graduated_account_ids
        ).values_list('application_id', flat=True)

        entry_level_application_ids = EntryLevelLimitHistory.objects.exclude(
            application_id__in=excluded_application_ids
        ).values_list('application_id', flat=True)

        entry_level_account_ids = Application.objects.filter(
            application_id__in=entry_level_application_ids
        ).values_list('account_id', flat=True)

        now = timezone.localtime(timezone.now())

        AccountProperty.objects.filter(
            account_id__in=entry_level_account_ids
        ).update(is_entry_level=True, udate=now)

        self.stdout.write('Finished retroloading')
