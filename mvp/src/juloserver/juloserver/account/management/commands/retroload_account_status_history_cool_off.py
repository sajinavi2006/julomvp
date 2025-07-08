from django.core.management.base import BaseCommand
from django.db import transaction
from juloserver.account.constants import AccountConstant
from django.utils import timezone

from datetime import timedelta

from juloserver.account.models import (
    AccountStatusHistory,
)


class Command(BaseCommand):
    help = "Retroload account status history cool off"

    def handle(self, *args, **options):

        post_cool_off_threshold = timezone.localtime(timezone.now()).date() - timedelta(days=90)
        query_filter = {
            'status_new': AccountConstant.STATUS_CODE.suspended,
            'change_reason__in': ["R4 cool off period", "refinancing cool off period"],
            'cdate__date__gte': post_cool_off_threshold,
            'account__status__status_code': AccountConstant.STATUS_CODE.suspended,
        }

        account_status_histories = AccountStatusHistory.objects.filter(**query_filter)

        with transaction.atomic():
            for account_status_history in account_status_histories:
                account_status_history.update_safely(is_reactivable=True)
