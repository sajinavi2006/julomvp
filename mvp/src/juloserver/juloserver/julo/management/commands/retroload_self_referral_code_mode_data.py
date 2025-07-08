import logging
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_self_referral_code_change)

from django.core.management.base import BaseCommand

from juloserver.julo.models import Customer


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'retroload moe account available limit julo'

    def handle(self, *args, **options):
        self.stdout.write('Start to retroload data for self referral code')
        customers = Customer.objects.filter(
            self_referral_code__isnull=False).iterator()
        count = 0
        for customer in customers:
            send_user_attributes_to_moengage_for_self_referral_code_change(
                customer
            )
            count += 1
        self.stdout.write('=============================================================')
        self.stdout.write('finished retroload data for self referral code, '
                          'total count: {}'.format(count))
