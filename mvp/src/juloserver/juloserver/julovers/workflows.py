import json
import logging

from django.db import transaction
from requests.exceptions import ReadTimeout

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account.services.credit_limit import (
    get_credit_matrix,
    get_credit_matrix_parameters,
    get_transaction_type,
    store_credit_limit_generated,
    store_related_data_for_generate_credit_limit,
)
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.disbursement.exceptions import XfersApiError
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.julo.constants import Affordability
from juloserver.julo.models import AffordabilityHistory, CreditScore, ProductLine
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julovers.constants import JuloverConst, JuloverReason
from juloserver.julovers.exceptions import SetLimitMoreThanMaxAmount
from juloserver.julovers.models import Julovers
from juloserver.julovers.services.core_services import (
    contruct_params_from_set_limit_for_julover,
    store_account_property_julover,
)
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_self_referral_code_change,
)
from juloserver.pin.services import process_reset_pin_request
from juloserver.referral.services import generate_customer_level_referral_code

logger = logging.getLogger(__name__)


class JuloverWorkflowAction(JuloOneWorkflowAction):
    def process_bank_validation(self):
        validated = False
        data_to_validate = {
            'name_bank_validation_id': None,
            'bank_name': self.application.bank_name,
            'account_number': self.application.bank_account_number,
            'name_in_bank': self.application.name_in_bank,
            'mobile_phone': self.application.mobile_phone_1,
            'application': self.application,
        }
        validation_process = trigger_name_in_bank_validation(
            data_to_validate=data_to_validate,
            new_log=True,
            method=NameBankValidationVendors.DEFAULT,
        )
        name_bank_validation = validation_process.name_bank_validation
        self.application.update_safely(
            name_bank_validation_id=name_bank_validation.id,
        )
        try:
            validation_process.validate()
            if not validation_process.is_success():
                logger.error({
                    'module': 'julovers',
                    'action': 'Process validate bank for julovers',
                    'message': f'Failed to validate bank for julover app: {self.application.id}',
                    'status': name_bank_validation.validation_status,
                    'reason': name_bank_validation.reason,
                })
            else:
                validated = True
                self.application.update_safely(
                    bank_account_number=name_bank_validation.account_number,
                    name_in_bank=name_bank_validation.validated_name,
                )
        except (
            ReadTimeout, #xfers
            XfersApiError, #xfers
        ) as e:
            pass

        return validated

    def move_to_130(self):
        process_application_status_change(
            self.application.id,
            new_status_code=130,
            change_reason='julover credit score generated',
        )

    def move_to_141(self):
        process_application_status_change(
            self.application.id,
            new_status_code=141,
            change_reason='julover bank validation failed',
        )

    def move_to_190(self):
        process_application_status_change(
            self.application.id,
            new_status_code=190,
            change_reason='credit limit generated for julover',
        )


    def process_credit_score_generation(self):
        CreditScore.objects.get_or_create(
            application=self.application,
            score=JuloverConst.DEFAULT_CREDIT_SCORE,
            message=JuloverReason.CREDIT_SCORE_GENERATION,
            products_str=json.dumps([ProductLineCodes.JULOVER]),
            inside_premium_area=True,
        )

    def process_credit_limit_generation(self):
        set_limit = Julovers.objects.filter(
            email__iexact=self.application.email,
        ).values_list('set_limit', flat=True).last()
        max_amount = ProductLine.objects.filter(
            product_line_code=ProductLineCodes.JULOVER,
        ).values_list('max_amount', flat=True).last()

        if set_limit > max_amount:
            raise SetLimitMoreThanMaxAmount

        max_limit = set_limit
        credit_matrix = get_credit_matrix(
            parameters=get_credit_matrix_parameters(self.application),
            transaction_type=get_transaction_type(),
        )
        params = contruct_params_from_set_limit_for_julover(set_limit)

        with transaction.atomic():
            afford_history = AffordabilityHistory.objects.create(
                affordability_value=params['affordability_value'],
                affordability_type=Affordability.AFFORDABILITY_TYPE,
                application=self.application,
                application_status=self.application.application_status,
                reason=JuloverReason.LIMIT_GENERATION,
            )

            # ops.CreditLimitGeneration
            store_credit_limit_generated(
                application=self.application,
                account=None,
                credit_matrix=credit_matrix,
                affordability_history=afford_history,
                max_limit=max_limit,
                set_limit=set_limit,
                log_data=json.dumps({ # this is extra
                    'simple_limit': params['simple_limit'],
                    'reduced_limit': params['reduced_limit'],
                    'limit_adjustment_factor': params['limit_adjustment_factor'],
                }),
                reason=JuloverReason.LIMIT_GENERATION,
            )

            # ops.account, account limmit, customer limit
            store_related_data_for_generate_credit_limit(
                application=self.application,
                max_limit=max_limit,
                set_limit=set_limit,
            )
            # account property
            store_account_property_julover(
                application=self.application,
                set_limit=set_limit,
            )

    def process_activate_julover_account(self):
        account = self.application.customer.account_set.last()
        with transaction.atomic():
            account_limit = AccountLimit.objects.filter(account=account).last()
            account_limit.update_safely(
                available_limit=account_limit.set_limit,
            )
            process_change_account_status(
                account=account,
                new_status_code=AccountConstant.STATUS_CODE.active,
                change_reason='activate Julover account'
            )

    def send_notification_email(self):
        # send notfication email to reset PIN for julover
        customer = self.application.customer
        process_reset_pin_request(
            customer=customer,
            email=customer.email,
            new_julover=True,
        )

    def generate_referral_code(self):
        generate_customer_level_referral_code(self.application)
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_self_referral_code_change.delay(
                self.application.customer_id
            )
        )
