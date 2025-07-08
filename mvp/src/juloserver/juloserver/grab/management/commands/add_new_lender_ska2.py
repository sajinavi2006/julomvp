
import secrets
import string

from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.forms.models import model_to_dict

from juloserver.followthemoney.models import (
    LenderApproval,
    LenderBalanceCurrent,
    LenderBankAccount,
    LenderCurrent,
    LoanAgreementTemplate,
)
from juloserver.julo.models import (
    LenderCustomerCriteria,
    LenderDisburseCounter,
    LenderProductCriteria,
    Partner,
    ProductProfile,
)
from juloserver.julo.product_lines import ProductLineCodes


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                ska2_name = 'ska2'
                ska2_email = "amrita.vir@grab.com"

                jtp = LenderCurrent.objects.filter(lender_name="jtp").last()
                if not jtp:
                    raise Exception("jtp lender not found")
                jtp_partner = jtp.user.partner

                ska_lender = LenderCurrent.objects.filter(lender_name="ska").last()
                if not ska_lender:
                    raise Exception("ska lender not found")
                ska_partner = ska_lender.user.partner

                ska2_user = User.objects.filter(username=ska2_name).first()
                if not ska2_user:
                    chars = string.ascii_letters + string.digits
                    password = ''.join(secrets.choice(chars) for _ in range(8))
                    ska2_user = User.objects.create_user(
                        username=ska2_name,
                        email=ska2_email,
                        password=password,
                    )

                partner = Partner.objects.get_or_none(user=ska2_user)
                if not partner:
                    partner_dict = model_to_dict(ska_partner)
                    del partner_dict["id"]
                    partner_dict["name"] = ska2_name
                    partner_dict["user"] = ska2_user
                    partner = Partner.objects.create(**partner_dict)
                    self.stdout.write("Ska2's ops.partner created.")

                    lender_dict = model_to_dict(ska_lender)
                    del lender_dict["id"]
                    lender_dict["lender_name"] = ska2_name
                    lender_dict["user"] = ska2_user
                    lender_dict["lender_status"] = "inactive"
                    lender = LenderCurrent.objects.create(**lender_dict)
                    self.stdout.write("Ska2's ops.lender created.")

                    LenderDisburseCounter.objects.create(lender=lender, partner=partner)
                    LenderBalanceCurrent.objects.create(lender=lender)
                    LenderCustomerCriteria.objects.create(lender=lender, partner=partner)
                    product_profiles = ProductProfile.objects.filter(
                        code__in=ProductLineCodes.grab()).values_list('id', flat=True)
                    LenderProductCriteria.objects.create(
                        lender=lender,
                        partner=partner,
                        type='Product List',
                        product_profile_list=list(product_profiles),
                    )

                    jtp_bank_accounts = jtp.lenderbankaccount_set.filter(
                        bank_account_status="active")
                    banks = []
                    for bank_account in jtp_bank_accounts:
                        bank_account.pk = None
                        bank_account.lender = lender
                        bank_account.name_bank_validation = None
                        banks.append(bank_account)
                    LenderBankAccount.objects.bulk_create(banks)

                    agreement_templates = []
                    for agreement_template in jtp.loanagreementtemplate_set.all():
                        is_agreement_exists = LoanAgreementTemplate.objects.filter(
                            lender=lender, agreement_type=agreement_template.agreement_type
                        ).exists()
                        if not is_agreement_exists:
                            agreement_template.pk = None
                            agreement_template.lender = lender
                            agreement_templates.append(agreement_template)
                    LoanAgreementTemplate.objects.bulk_create(agreement_templates)

                    if not LenderApproval.objects.filter(partner=partner).exists():
                        LenderApproval.objects.create(
                            partner=partner,
                            is_auto=jtp_partner.lenderapproval.is_auto,
                            start_date=timezone.localtime(timezone.now()),
                            end_date=None,
                            delay=jtp_partner.lenderapproval.delay,
                            expired_in=jtp_partner.lenderapproval.expired_in,
                            is_endless=jtp_partner.lenderapproval.is_endless,
                        )

        except Exception as e:
            self.stdout.write(self.style.ERROR('Something is wrong: {}'.format(str(e))))
            self.stdout.write(self.style.ERROR('Rolling back...'))
            return

        self.stdout.write(self.style.SUCCESS('Successfully added lender SKA2'))
