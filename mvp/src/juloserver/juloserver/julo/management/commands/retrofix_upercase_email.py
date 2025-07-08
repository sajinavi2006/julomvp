import logging, sys

from juloserver.julo.models import (Application,
                                    Customer)

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retrofix lowered case email on customer and application table '

    def handle(self, *args, **options):
        customers = Customer.objects.raw('select * from ops.customer where lower(email) != email')
        for customer in customers:
            customer.update_safely(email=customer.email.lower())
