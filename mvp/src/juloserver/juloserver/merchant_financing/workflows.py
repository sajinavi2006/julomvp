import datetime
import logging
from django.db import transaction
from django.utils import timezone

from juloserver.account.services.account_related import process_change_account_status
from juloserver.julo.constants import Affordability
from juloserver.julo.models import AffordabilityHistory
from juloserver.account.services.credit_limit import (
    store_related_data_for_generate_credit_limit,
    update_related_data_for_generate_credit_limit
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.workflows import WorkflowAction
from juloserver.merchant_financing.services import (
    sum_merchant_transaction,
    get_credit_limit
)
from juloserver.account.models import Account, AccountLimit
from juloserver.account.constants import AccountConstant
from juloserver.merchant_financing.models import MerchantApplicationReapplyInterval
from juloserver.merchant_financing.tasks import send_email_sign_sphp_merchant_financing

from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one
from juloserver.merchant_financing.services import store_account_property_merchant_financing

logger = logging.getLogger(__name__)


class MerchantFinancingWorkflowAction(WorkflowAction):

    def process_credit_limit_generation(self):
        if not self.application.is_merchant_flow():
            raise JuloException("Application workflow must be merchant financing")
        elif not self.application.merchant:
            raise JuloException("Application does not have merchant")
        merchant = self.application.merchant
        partner = self.application.partner
        total_amount_transaction = sum_merchant_transaction(merchant, partner)
        # hpa is equal to historical_partner_affordability
        credit_limit_data = get_credit_limit(merchant, total_amount_transaction)
        AffordabilityHistory.objects.create(
            application_id=self.application.id,
            application_status=self.application.application_status,
            affordability_value=credit_limit_data['affordability_value'],
            affordability_type=Affordability.AFFORDABILITY_TYPE,
            reason="Limit Generation"
        )
        if not credit_limit_data['is_qualified']:
            change_reason = 'Affordability not reached'
            next_status_code_135 = ApplicationStatusCodes.APPLICATION_DENIED
            process_application_status_change(
                self.application.id, next_status_code_135, change_reason
            )
        else:
            credit_limit = credit_limit_data['credit_limit']
            set_limit = credit_limit
            account = self.application.customer.account_set.last()
            if account:
                update_related_data_for_generate_credit_limit(
                    self.application, credit_limit, set_limit
                )
            else:
                store_related_data_for_generate_credit_limit(
                    self.application, credit_limit, set_limit
                )
                self.application.refresh_from_db()

                # generate account_property and history
                store_account_property_merchant_financing(self.application, set_limit)
            with transaction.atomic():
                merchant.historical_partner_affordability_threshold = credit_limit_data['hpa']
                merchant.limit = credit_limit
                merchant.save()
                next_status_code_160 = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
                change_reason = "Credit limit generated"
                process_application_status_change(
                    self.application.id, next_status_code_160, change_reason
                )
            self.application.refresh_from_db()

    def send_email_sign_sphp_general(self):
        send_email_sign_sphp_merchant_financing.delay(self.application.id)

    def process_activate_account(self):
        account = Account.objects.select_related('customer').filter(customer=self.application.customer).last()
        if not account:
            logger.info({
                'action': 'merchant financing update account to active at 190',
                'application_id': self.application.id,
                'message': 'Account Not Found'
            })
            return

        with transaction.atomic():
            process_change_account_status(
                account,
                AccountConstant.STATUS_CODE.active,
                change_reason="Merchant Financing application approved",
            )
            account_limit = AccountLimit.objects.filter(account=account).last()
            if not account_limit:
                logger.info({
                    'action': 'merchant financing update account limit available limit',
                    'application_id': self.application.id,
                    'message': 'Account Limit Not Found'
                })
                return
            account_limit.update_safely(available_limit=account_limit.set_limit)

    def populate_payment_method(self):
        generate_customer_va_for_julo_one(self.application)

    def process_reapply_merchant_application(self):
        application = self.application
        customer = application.customer
        reapply_interval_partner_rules = MerchantApplicationReapplyInterval.objects.filter(
            partner=application.partner,
            application_status=application.application_status.status_code
        )

        if not reapply_interval_partner_rules:
            reapply_interval_generic_rule = MerchantApplicationReapplyInterval.objects.filter(
                application_status=application.application_status.status_code,
                partner__isnull=True
            ).first()
            if reapply_interval_generic_rule:
                reapply_interval_day = reapply_interval_generic_rule.interval_day
            else:
                reapply_interval_day = 14  # if there is no rule, use the default 14 days
        else:
            reapply_interval_partner_rule = reapply_interval_partner_rules.first()
            reapply_interval_day = reapply_interval_partner_rule.interval_day

        today_date = timezone.localtime(timezone.now())
        next_reapply_date = today_date + datetime.timedelta(reapply_interval_day)
        customer.can_reapply = False
        customer.can_reapply_date = next_reapply_date
        customer.save()
