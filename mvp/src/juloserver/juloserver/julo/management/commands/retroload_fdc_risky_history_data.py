from django.core.management.base import BaseCommand

from juloserver.julo.models import FDCRiskyHistory, EarlyPaybackOffer
from juloserver.julo.services2 import get_customer_service


class Command(BaseCommand):
    help = 'retroload fdc risky history'

    def handle(self, *args, **options):
        early_payback_offers = EarlyPaybackOffer.objects.distinct('application')

        if early_payback_offers:
            for early_payback_offer in early_payback_offers:
                is_risky = get_customer_service().check_risky_customer(
                    early_payback_offer.application.id)
                FDCRiskyHistory.objects.create(
                    application=early_payback_offer.application,
                    loan=early_payback_offer.loan,
                    is_fdc_risky=is_risky
                )
