from django.core.management.base import BaseCommand

from juloserver.julo.models import Application, ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.referral.services import generate_customer_level_referral_code


class Command(BaseCommand):
    help = "update customer referral code julover"

    def handle(self, *args, **options):
        applications = Application.objects.filter(
            product_line__product_line_code=ProductLineCodes.JULOVER,
            customer__self_referral_code__isnull=True,
            application_status__status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        for application in applications.iterator():
            generate_customer_level_referral_code(application)
