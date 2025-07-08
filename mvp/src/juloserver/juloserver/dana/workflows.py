import logging

from django.db import transaction
from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account, AccountLimit, AccountLookup
from juloserver.account.services.account_related import process_change_account_status
from juloserver.customer_module.models import CustomerLimit
from juloserver.dana.models import DanaCustomerData, DanaFDCResult, DanaApplicationReference
from juloserver.dana.onboarding.services import store_account_property_dana
from juloserver.dana.constants import (
    DanaFDCStatusSentRequest,
    MaxCreditorStatus,
    OnboardingApproveReason,
)
from juloserver.julo.models import CreditScore
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.workflows import WorkflowAction
from juloserver.partnership.models import PartnershipApplicationFlag

logger = logging.getLogger(__name__)


class DanaWorkflowAction(WorkflowAction):
    @transaction.atomic
    def generate_dana_credit_limit(self) -> None:
        """
        Dana flow from 105 to 130
        Create Credit Limit generation
        - Create Account
        - Create AccountLimit
        - Update DanaCustomerData Account
        - Update Application Account
        """
        account_lookup = AccountLookup.objects.filter(workflow=self.application.workflow).last()
        account = Account.objects.create(
            customer=self.application.customer,
            status_id=AccountConstant.STATUS_CODE.inactive,
            account_lookup=account_lookup,
            cycle_day=14,  # Not used but required, for Determine the cycle_day using dana formula
        )

        dana_customer_data = DanaCustomerData.objects.filter(
            customer=self.application.customer
        ).last()
        limit = dana_customer_data.proposed_credit_limit

        # Create Credit Limit
        AccountLimit.objects.create(account=account, max_limit=limit, set_limit=limit)

        # Update or create customer Limit to newest
        max_limit = {'max_limit': limit}
        CustomerLimit.objects.update_or_create(
            customer=self.application.customer, defaults=max_limit
        )

        # Set dana_customer_data & application with account
        dana_customer_data.account = account
        dana_customer_data.save(update_fields=['account'])
        self.application.update_safely(account=account)

        # generate account_property and history
        store_account_property_dana(self.application, limit)

        # Update Status to 190
        next_status_code = ApplicationStatusCodes.LOC_APPROVED

        application_id = int(self.application.id)
        is_bypass_phone_same_nik_exists = PartnershipApplicationFlag.objects.filter(
            application_id=application_id,
            name=OnboardingApproveReason.BYPASS_PHONE_SAME_NIK_NEW_RULES,
        ).exists()

        if is_bypass_phone_same_nik_exists:
            change_reason = OnboardingApproveReason.APPROVED_WITH_NEW_NIK_RULES
        else:
            change_reason = "credit limit generated"

        process_application_status_change(
            application_id,
            new_status_code=next_status_code,
            change_reason=change_reason,
        )

    def activate_dana_account(self) -> None:
        account = self.application.account

        if not account:
            logger.info(
                {
                    'action': 'dana_customer_account_not_update_to_active_at_190',
                    'application_id': self.application.id,
                    'message': 'Account Not Found',
                }
            )
            return

        account_limit = AccountLimit.objects.filter(account=account).last()
        if not account_limit:
            logger.info(
                {
                    'action': 'dana_update_account_limit',
                    'application_id': self.application.id,
                    'message': 'Account Limit Not Found',
                }
            )
            return

        account_limit.update_safely(available_limit=account_limit.set_limit)

        # Update to active status
        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.active,
            change_reason="DANA application approved",
        )

    def mark_user_as_fraud_account(self) -> None:
        account = self.application.account
        if not account:
            logger.info(
                {
                    'action': 'dana_customer_account_mark_as_fraud_account',
                    'application_id': self.application.id,
                    'message': 'Account Not Found',
                }
            )
            return

        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.fraud_reported,
            change_reason="Mark as fraud account",
        )

    def mark_user_as_delinquent(self) -> None:
        account = self.application.account
        if not account:
            logger.info(
                {
                    'action': 'dana_customer_account_mark_user_as_delinquent',
                    'application_id': self.application.id,
                    'message': 'Account Not Found',
                }
            )
            return

        process_change_account_status(
            account,
            AccountConstant.STATUS_CODE.suspended,
            change_reason="Mark as delinquent account",
        )

    def generate_dana_credit_score(self) -> None:
        dana_credit_score = self.application.dana_customer_data.credit_score
        julo_credit_score = ''

        if dana_credit_score > 750:
            julo_credit_score = 'A+'
        elif dana_credit_score <= 750 and dana_credit_score > 500:
            julo_credit_score = 'A-'
        elif dana_credit_score <= 500 and dana_credit_score > 250:
            julo_credit_score = 'B+'
        elif dana_credit_score <= 250 and dana_credit_score >= 0:
            julo_credit_score = 'B-'

        if not julo_credit_score:
            logger.info(
                {
                    'action': 'generate_dana_credit_score',
                    'application_id': self.application.id,
                    'message': 'Unidentified Dana Credit Score',
                }
            )
            return
        else:
            CreditScore.objects.create(application_id=self.application.id, score=julo_credit_score)

    def process_dana_fdc_result_as_init(self):
        """
        For Create Dana FDC status, we start status with INIT,
        will update after have result FDC status
        """
        dana_customer_data = DanaCustomerData.objects.filter(
            customer=self.application.customer
        ).last()

        DanaFDCResult.objects.create(
            dana_customer_identifier=dana_customer_data.dana_customer_identifier,
            application_id=self.application.id,
            status=DanaFDCStatusSentRequest.PENDING,
            lender_product_id=dana_customer_data.lender_product_id,
        )

    def set_creditor_check_as_init(self):
        application_id = self.application.id
        dana_application_reference = DanaApplicationReference.objects.filter(
            application_id=application_id
        ).last()
        if dana_application_reference:
            dana_application_reference.update_safely(
                creditor_check_status=MaxCreditorStatus.PENDING
            )
        else:
            logger.info(
                {
                    'action': 'set_creditor_check_as_init',
                    'application_id': application_id,
                    'message': 'dana_application_reference not found, need to check',
                }
            )
