from django.core.management.base import BaseCommand

from juloserver.julo.models import CustomerCampaignParameter, EmailHistory, EarlyPaybackOffer
from juloserver.julo.constants import WaiveCampaignConst
from juloserver.julo.statuses import LoanStatusCodes
from datetime import datetime, time, timedelta


class Command(BaseCommand):
    help = 'retroload early payback offer'

    def handle(self, *args, **options):
        customers_campaign_parameters = CustomerCampaignParameter.objects.filter(
            campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
        )
        if customers_campaign_parameters:
            for customer_campaign_parameters in customers_campaign_parameters:
                date = customer_campaign_parameters.effective_date
                start_of_day = datetime.combine(date, time(0, 0, 0))
                end_of_day = start_of_day + timedelta(days=1)
                email_history = EmailHistory.objects.filter(
                    customer=customer_campaign_parameters.customer,
                    template_code='email_early_payback_1',
                    cdate__gte=start_of_day,
                    cdate__lt=end_of_day,
                ).last()
                if email_history:
                    paid_off_indicator = False
                    if email_history.application.loan.status == LoanStatusCodes.PAID_OFF:
                        paid_off_indicator = True
                    cycle_number = 1
                    early_payback_offers = EarlyPaybackOffer.objects.filter(
                        loan=email_history.application.loan
                    )
                    if early_payback_offers:
                        cycle_number += len(early_payback_offers)
                    EarlyPaybackOffer.objects.create(
                        application=email_history.application,
                        loan=email_history.application.loan,
                        is_fdc_risky=True,
                        promo_date=customer_campaign_parameters.effective_date,
                        email_status=email_history.status,
                        cycle_number=cycle_number,
                        paid_off_indicator=paid_off_indicator,
                    )
