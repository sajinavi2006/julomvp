from django.core.management.base import BaseCommand
from juloserver.julo.models import ProductLineCodes, Application
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one

class Command(BaseCommand):
    help = "create a customer payment method for julovers"

    def handle(self, *args, **options):
        applications = Application.objects.filter(
            product_line__product_line_code=ProductLineCodes.JULOVER,
            application_status__status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        for application in applications.iterator():
            generate_customer_va_for_julo_one(application)

        self.stdout.write(self.style.SUCCESS('Payment method has been generated for Julovers.'))
