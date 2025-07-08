import logging
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_available_limit_created)

from django.core.management.base import BaseCommand

from juloserver.account.models import AccountLimit


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'retroload moe account available limit julo'

    def handle(self, *args, **options):
        self.stdout.write('Start to retroload data for account limit')
        account_limits = AccountLimit.objects.filter(
            available_limit__gte=0).iterator()
        count = 0
        for account_limit in account_limits:
            account = account_limit.account
            send_user_attributes_to_moengage_for_available_limit_created(
                account.customer, account, account_limit.available_limit
            )
            count += 1
        self.stdout.write('=============================================================')
        self.stdout.write('finished retroload data for account limit, '
                          'total count: {}'.format(count))
