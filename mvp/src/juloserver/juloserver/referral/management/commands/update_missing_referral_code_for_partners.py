import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.customer_module.services.customer_related import get_or_create_cashback_balance
from juloserver.julo.models import (
    Application,
    ProductLineCodes,
    Customer,
    RefereeMapping,
    Loan,
    ReferralSystem,
    Partner,
)
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_self_referral_code_change,
)
from juloserver.referral.services import (
    generate_customer_level_referral_code,
    check_referral_cashback_v2,
    get_referral_benefit_logic_fs,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.partners import PartnerConstant

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class Command(BaseCommand):
    help = "update customer referral code missing with partners"

    def handle(self, *args, **options):
        referral_logic_fs = get_referral_benefit_logic_fs()

        partner_name_list = [PartnerConstant.KLOP_PARTNER, PartnerConstant.LINKAJA_PARTNER]
        partner_ids = Partner.objects.filter(name__in=partner_name_list).values_list(
            'id', flat=True
        )
        referral_system = ReferralSystem.objects.get(name='PromoReferral', is_active=True)
        if partner_ids:
            account_ids = Account.objects.filter(
                Q(customer__self_referral_code__isnull=True)
                | Q(customer__self_referral_code__exact=''),
                status_id=AccountConstant.STATUS_CODE.active,
            ).values_list('id', flat=True)

            applications = Application.objects.filter(
                account_id__in=account_ids,
                product_line__product_line_code=ProductLineCodes.J1,
                application_status__status_code=ApplicationStatusCodes.LOC_APPROVED,
                partner_id__in=partner_ids,
            ).order_by('id')

            for application in applications.iterator():
                try:
                    with transaction.atomic():
                        first_loan = Loan.objects.filter(
                            account_id=application.account_id,
                            loan_status_id__gte=LoanStatusCodes.CURRENT,
                        ).first()
                        if first_loan:
                            self.generate_referral_code_and_process_benefit(
                                application,
                                referral_system.activate_referee_benefit,
                                first_loan.loan_amount,
                                referral_logic_fs
                            )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            'customer_id: {}, error: {}'.format(application.customer_id, str(e))
                        )
                    )
                    sentry_client.capture_exceptions()

            self.stdout.write(
                '===================== Finished running ================================'
            )
        else:
            self.stdout.write("Listed partners not found")

    def generate_referral_code_and_process_benefit(
        self, application, activate_referee_benefit, loan_amount, referral_logic_fs
    ):
        customer = application.customer
        # generate referral code
        generate_customer_level_referral_code(application)
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_self_referral_code_change.delay(
                application.customer_id
            )
        )

        customer.refresh_from_db()
        if customer.self_referral_code:
            self.stdout.write(
                self.style.SUCCESS(
                    'success generate_customer_level_referral_code for customer_id: {}'.format(
                        application.customer_id
                    )
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    'Failed to  generate_customer_level_referral_code for customer_id: {}'.format(
                        application.customer_id
                    )
                )
            )

        if not application.referral_code:
            self.stdout.write('===================== No Referrer ================================')
            return

        customer_referred = Customer.objects.filter(
            self_referral_code=application.referral_code.upper()
        ).last()

        # check if already processed benefit
        if RefereeMapping.objects.filter(referrer=customer_referred, referee=customer).exists():
            return

        # process benefit
        if (
            customer_referred
            and customer_referred.account.status_id == AccountConstant.STATUS_CODE.active
        ):
            get_or_create_cashback_balance(customer)
            get_or_create_cashback_balance(customer_referred)
            check_referral_cashback_v2(
                application, customer_referred, activate_referee_benefit, loan_amount,
                referral_logic_fs
            )
            self.stdout.write(
                self.style.SUCCESS(
                    'success process benefit for customer_id: {}'.format(application.customer_id)
                )
            )
        self.stdout.write('=============================================================')
