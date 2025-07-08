from django.core.management.base import BaseCommand
from juloserver.paylater.constants import PaylaterConst
from juloserver.paylater.models import AccountCreditLimit
from juloserver.julo.models import Partner
from juloserver.julo.statuses import JuloOneCodes


class Command(BaseCommand):

    help = "Suspend customer bukalapak"

    def handle(self, *args, **options):

        partner = Partner.objects.filter(name=PaylaterConst.PARTNER_NAME).last()
        AccountCreditLimit.objects.filter(partner=partner).update(account_credit_status=JuloOneCodes.SUSPENDED)
