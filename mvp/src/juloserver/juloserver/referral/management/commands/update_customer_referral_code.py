import logging
import sys

from django.core.management.base import BaseCommand
from django.db import transaction

from juloserver.julo.models import Application, Customer
from juloserver.referral.services import generate_referral_code

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

BATCH_SIZE = 1


class Command(BaseCommand):
    help = "update customer referral code according to new rule: ENH-1351"

    def handle(self, *args, **options):
        customers = Customer.objects.all()
        for customer in customers.iterator():
            customer_self_referral_code = customer.self_referral_code
            if not customer_self_referral_code:
                continue
            referral_code = generate_referral_code(customer)
            if not referral_code:
                continue
            with transaction.atomic():
                Application.objects.filter(
                    referral_code__iexact=customer_self_referral_code.upper()
                ).update(referral_code=referral_code)
                customer.self_referral_code = referral_code
                customer.save()
            print("update_success_from_customer_id: %s, %s", customer.id, referral_code)
