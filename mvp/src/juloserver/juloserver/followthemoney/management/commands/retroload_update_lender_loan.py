from django.db.models import Q

from django.core.management.base import BaseCommand

from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.models import Loan, Partner, LenderDisburseCounter
from juloserver.julo.partners import PartnerConstant

class Command(BaseCommand):
    help = 'retroload_update_lender_loan'


    def handle(self, *args, **options):
        partner_list = (PartnerConstant.GRAB_PARTNER, PartnerConstant.JTP_PARTNER, PartnerConstant.BRI_PARTNER)

        for partner_name in partner_list:
            partner = Partner.objects.get(name=partner_name)
            data = LenderCurrent.objects.update_or_create(user=partner.user,
                                                          lender_name=partner.name,
                                                          poc_name=partner.poc_name or 'change it later',
                                                          poc_email=partner.poc_email or 'change it later',
                                                          poc_phone=partner.poc_phone or '085555555555',
                                                          lender_address=partner.company_address or 'change it later',
                                                          business_type=partner.business_type,
                                                          pks_number=partner.agreement_letter_number or 'change it later',
                                                          service_fee=0, #confirmed by Yogi
                                                          source_of_fund=partner.source_of_fund or 'change it later')

            lender = LenderCurrent.objects.get(lender_name=partner_name)
            Loan.objects.filter(application__loan__partner = partner).update(lender=lender)
            LenderDisburseCounter.objects.filter(partner=partner).update(lender=lender)
            self.stdout.write(self.style.SUCCESS('Successfully updated the lender in loan'))
