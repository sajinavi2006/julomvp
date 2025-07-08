from django.core.management.base import BaseCommand
from juloserver.julo.models import CustomerCampaignParameter
from juloserver.julo.constants import WaiveCampaignConst
from juloserver.julo.services2.payment_event import waiver_early_payoff_campaign_promo


class Command(BaseCommand):
    help = 'do waiver early payoff campaign'

    def handle(self, *args, **options):
        customers_campaign_parameters = CustomerCampaignParameter.objects.filter(
            campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
        )
        if customers_campaign_parameters:
            for customers_campaign_parameter in customers_campaign_parameters:
                loan = customers_campaign_parameter.customer.get_last_loan_active_mtl()
                if loan:
                    start_promo = customers_campaign_parameter.effective_date
                    waiver_early_payoff_campaign_promo(loan.id, start_promo)

            self.stdout.write(self.style.SUCCESS('Successfully waive'))
