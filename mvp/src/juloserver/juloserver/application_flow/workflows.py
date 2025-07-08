"""workflows.py"""

import logging

import semver
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from juloserver.account.constants import AccountConstant
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLookup,
    CreditLimitGeneration,
)
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account.services.credit_limit import (
    generate_credit_limit,
    get_credit_limit_reject_affordability_value,
    store_account_property,
    store_related_data_for_generate_credit_limit,
    update_related_data_for_generate_credit_limit,
    get_triple_pgood_limit,
    get_non_fdc_job_check_fail_limit,
    get_orion_fdc_limit_adjustment,
)
from juloserver.apiv2.services import (
    check_iti_repeat,
    is_email_whitelisted_to_force_high_score,
)
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
)
from juloserver.application_flow.services import (
    check_application_version,
    is_experiment_application,
    check_bad_history,
    check_click_pass,
)
from juloserver.application_flow.services2.bank_statement import BankStatementClient
from juloserver.application_flow.constants import CacheKey
from juloserver.autodebet.services.benefit_services import (
    set_default_autodebet_benefit_control,
)
from juloserver.channeling_loan.services.general_services import (
    application_risk_acceptance_ciriteria_check,
    generate_channeling_status,
    get_channeling_loan_priority_list,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.customer_module.services.customer_related import (
    get_or_create_cashback_balance,
)
from juloserver.disbursement.models import NameBankValidation
from juloserver.entry_limit.services import EntryLevelLimitProcess
from juloserver.julo.constants import (
    ApplicationStatusCodes,
    ExperimentConst,
    FeatureNameConst,
    WorkflowConst,
    OnboardingIdConst,
)
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from juloserver.julo.models import (
    AffordabilityHistory,
    Application,
    ApplicationNote,
    Bank,
    CreditScore,
    CustomerFieldChange,
    ExperimentSetting,
    FeatureSetting,
    PartnerBankAccount,
    Workflow,
    BankStatementSubmit,
    FDCInquiry,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one
from juloserver.julo.tasks2.partner_tasks import send_sms_to_specific_partner_customers
from juloserver.julo.utils import execute_after_transaction_safely, remove_current_user
from juloserver.julo.workflows import WorkflowAction
from juloserver.julolog.julolog import JuloLog
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_submit_bank_statement,
)
from juloserver.partnership.constants import (
    PartnershipPreCheckFlag,
    PartnershipProductFlow,
)
from juloserver.partnership.models import (
    PartnershipApplicationFlag,
    PartnershipCustomerData,
    PartnershipFlowFlag,
)
from juloserver.partnership.tasks import (
    process_sending_email_agent_assisted,
    send_email_agent_assisted,
)
from juloserver.personal_data_verification.services import (
    is_dukcapil_fraud,
    is_pass_dukcapil_verification_at_x130,
    get_dukcapil_fr_setting,
)
from juloserver.personal_data_verification.tasks import (
    face_recogniton,
    send_dukcapil_official_callback_data,
)
from juloserver.referral.services import generate_customer_level_referral_code
from juloserver.streamlined_communication.services import customer_have_upgrade_case

from ..disbursement.exceptions import DisbursementServiceError, XfersApiError
from ..julo.exceptions import InvalidBankAccount
from .constants import BankStatementConstant, JuloOneChangeReason
from .services import JuloOneByPass, JuloOneService
from .services2.bank_validation import (
    BankValidationError,
    has_levenshtein_distance_similarity,
    validate_bank,
)
from juloserver.application_form.constants import EmergencyContactConst
from ..julo.exceptions import JuloException
from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.fdc.constants import FDCInquiryStatus, FDCStatus
from juloserver.personal_data_verification.clients.dukcapil_fr_client import DukcapilFRClient

logger = logging.getLogger(__name__)
juloLogger = JuloLog()


class JuloOneWorkflowAction(WorkflowAction):
    def process_julo_one_at_190(self):
        import juloserver.pin.services as pin_services
        from juloserver.application_flow.services import check_revive_mtl

        if check_revive_mtl(self.application):
            logger.info(
                {
                    'action': 'julo one revive mtl account to active at 190',
                    'application_id': self.application.id,
                    'message': 'process reset pin',
                }
            )
            customer = self.application.customer
            email = self.application.email if self.application.email else customer.email
            pin_services.process_reset_pin_request(customer, email)

        account = Account.objects.filter(customer=self.application.customer).last()
        if not account:
            logger.info(
                {
                    'action': 'julo one update account to active at 190',
                    'application_id': self.application.id,
                    'message': 'Account Not Found',
                }
            )
            return

        with transaction.atomic():
            is_upgrade_application = customer_have_upgrade_case(
                self.application.customer, self.application
            )
            get_or_create_cashback_balance(account.customer)
            app_product_line = self.application.product_line
            ef_product_line = ProductLineCodes.EMPLOYEE_FINANCING
            if not is_upgrade_application:
                if app_product_line and (app_product_line.product_line_code == ef_product_line):
                    process_change_account_status(
                        account,
                        AccountConstant.STATUS_CODE.inactive,
                        change_reason="Waiting for master agreement sign",
                    )
                else:
                    process_change_account_status(
                        account,
                        AccountConstant.STATUS_CODE.active,
                        change_reason="Julo One application approved",
                    )

            account_limit = AccountLimit.objects.filter(account=account).last()
            if not account_limit:
                logger.info(
                    {
                        'action': 'julo one update account limit available limit',
                        'application_id': self.application.id,
                        'message': 'Account Limit Not Found',
                    }
                )
                return
            available_limit = account_limit.set_limit - account_limit.used_limit
            account_limit.update_safely(available_limit=available_limit)

            account_lookup = AccountLookup.objects.filter(workflow=self.application.workflow).last()
            account.update_safely(account_lookup=account_lookup)
            generate_customer_level_referral_code(self.application)

            if is_upgrade_application:
                credit_limit = CreditLimitGeneration.objects.filter(
                    application_id=self.application.id
                ).last()
                store_account_property(self.application, credit_limit.set_limit)

                if account.status_id == AccountConstant.STATUS_CODE.inactive:
                    process_change_account_status(
                        account,
                        AccountConstant.STATUS_CODE.active,
                        change_reason="Julo One application approved",
                    )

        # not handled if not account limit because already handled on top
        account_limit = AccountLimit.objects.filter(account=account).last()
        set_limit = account_limit.set_limit

        # Send email 190 if partnership application
        partnership_application_flag = None
        if self.application.partner:
            partnership_application_id = self.application.id
            partnership_application_flag = PartnershipApplicationFlag.objects.filter(
                application_id=partnership_application_id,
                name=PartnershipPreCheckFlag.APPROVED,
            ).exists()

        if partnership_application_flag:
            is_pin_created = pin_services.does_user_have_pin(self.application.customer.user)

            if is_pin_created:
                filters = {
                    'partner': self.application.partner,
                    'name': PartnershipProductFlow.AGENT_ASSISTED,
                    'configs__approved_agent_assisted_email__without_create_pin': True,
                }
            else:
                filters = {
                    'partner': self.application.partner,
                    'name': PartnershipProductFlow.AGENT_ASSISTED,
                    'configs__approved_agent_assisted_email__with_create_pin': True,
                }

            partnership_flow_configs = PartnershipFlowFlag.objects.filter(**filters).exists()

            logger.info(
                {
                    'action': 'send_email_190_for_agent_assisted_application',
                    'application_id': self.application.id,
                    'application_status': self.application.application_status_id,
                    'account_id': account.id,
                    'set_limit': set_limit,
                }
            )

            if partnership_flow_configs:
                send_email_agent_assisted.delay(
                    application_id=self.application.id,
                    is_reject=False,
                    is_x190=True,
                    set_limit=set_limit,
                )

    def process_affordability_calculation(self):
        app_sonic = self.application.applicationhistory_set.filter(
            change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY
        )
        if app_sonic:
            return
        julo_one_service = JuloOneService()
        input_params = julo_one_service.construct_params_for_affordability(self.application)
        compute_affordable_payment(**input_params)

    def process_credit_limit_generation(self):
        juloLogger.info(
            {
                "message": "Credit limit generation started",
                "application_id": self.application.id,
                "status": self.application.status,
            }
        )

        from juloserver.application_flow.services import eligible_to_offline_activation_flow
        if self.application.is_assisted_selfie is None:
            self.application.update_safely(is_assisted_selfie=False)

        max_limit, set_limit = generate_credit_limit(self.application)

        tag = BankStatementClient.APPLICATION_TAG
        application_path_tag_status = ApplicationPathTagStatus.objects.filter(
            application_tag=tag, status=BankStatementClient.TAG_STATUS_SUCCESS
        ).last()
        bank_statement_success = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=application_path_tag_status,
        ).exists()

        lbs_bypass_setting = ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.LBS_130_BYPASS
        ).last()
        swapout_dukcapil_bp_quota = (
            lbs_bypass_setting.criteria.get("limit_total_of_application_swap_out_dukcapil", 0)
            if lbs_bypass_setting
            else 0
        )
        eligible_to_offline_flow = eligible_to_offline_activation_flow(self.application)
        redis_client = get_redis_client()
        swapout_dukcapil_bp_count = redis_client.get(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER)
        if not swapout_dukcapil_bp_count:
            redis_client.set(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER, 0)
            swapout_dukcapil_bp_count = 0
        else:
            swapout_dukcapil_bp_count = int(swapout_dukcapil_bp_count)
        bypass_swapout_dukcapil = False

        if (
            not max_limit
            and not eligible_to_offline_flow
            and bank_statement_success
            and self.application.status == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
        ):
            powercred = BankStatementClient(self.application)
            # powercred.update_tag_to_failed()
            # send_user_attributes_to_moengage_for_submit_bank_statement.delay(
            #     self.application.id, None, False
            # )
            # process_application_status_change(
            #     self.application.id,
            #     ApplicationStatusCodes.APPLICATION_DENIED,
            #     'bank statement balance below threshold',
            # )
            powercred.reject('bank statement balance below threshold')
            return

        if max_limit > 0:
            juloLogger.info(
                {
                    "message": "Credit limit max limit gt 0",
                    "application_id": self.application.id,
                    "status": self.application.status,
                }
            )
            is_dukcapil_check_valid = is_pass_dukcapil_verification_at_x130(self.application)
            is_whitelisted_force_high_score = is_email_whitelisted_to_force_high_score(
                self.application.email
            )
            if (
                is_dukcapil_check_valid
                or eligible_to_offline_flow
                or is_whitelisted_force_high_score
            ):
                new_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
                change_reason = 'Credit limit generated'
                if is_whitelisted_force_high_score:
                    change_reason += ' (force high score)'
            elif bank_statement_success and swapout_dukcapil_bp_count < swapout_dukcapil_bp_quota:
                new_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
                change_reason = 'Credit limit generated'
                redis_client.increment(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER)
                swapout_dukcapil_bp_quota_left = (
                    swapout_dukcapil_bp_quota - swapout_dukcapil_bp_count - 1
                )
                if swapout_dukcapil_bp_quota_left in (0, 25, 50, 75, 100):
                    slack_channel = "#alerts-backend-onboarding"
                    mentions = "<@U04EDJJTX6Y> <@U040BRBR5LM>\n"
                    title = ":alert: ===LBS Bypass Quota Alert=== :alert: \n"
                    message = (
                        "Swapout Dukcapil Bypass Quota : "
                        + str(swapout_dukcapil_bp_quota_left)
                        + " left\n"
                    )
                    text = mentions + title + message
                    if settings.ENVIRONMENT != 'prod':
                        text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
                    send_slack_bot_message(slack_channel, text)
                bypass_swapout_dukcapil = True
            elif is_dukcapil_fraud(self.application.id):
                new_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
                change_reason = 'Credit limit generated (Fraud Dukcapil)'
            elif not eligible_to_offline_flow:
                new_status_code = ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
                change_reason = 'Credit limit generated (Fail Dukcapil)'

            juloLogger.info(
                {
                    "message": "Credit limit max limit gt 0, after dukcapil",
                    "application_id": self.application.id,
                    "status": self.application.status,
                    "new_status_code": new_status_code,
                    "change_reason": change_reason,
                    "is_dukcapil_check_valid": is_dukcapil_check_valid,
                }
            )

            # Check if the application has triple pgood. So he/she can have bigger limit.
            max_limit, set_limit = get_triple_pgood_limit(
                self.application, max_limit=max_limit, set_limit=set_limit
            )

            max_limit, set_limit = get_non_fdc_job_check_fail_limit(
                self.application, max_limit=max_limit, set_limit=set_limit
            )

            max_limit, set_limit = get_orion_fdc_limit_adjustment(
                self.application, max_limit=max_limit, set_limit=set_limit
            )

            # Store related data
            account = self.application.customer.account_set.last()
            if not account:
                juloLogger.info(
                    {
                        "message": "Credit limit does not have account",
                        "application_id": self.application.id,
                        "status": self.application.status,
                    }
                )
                store_related_data_for_generate_credit_limit(self.application, max_limit, set_limit)
                self.application.refresh_from_db()

                # generate account_property and history
                store_account_property(self.application, set_limit)
            else:
                juloLogger.info(
                    {
                        "message": "Credit limit have account",
                        "application_id": self.application.id,
                        "status": self.application.status,
                    }
                )
                update_related_data_for_generate_credit_limit(
                    self.application, max_limit, set_limit
                )
        else:
            new_status_code = ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
            change_reason = 'Credit limit generation failed'

            self.application.refresh_from_db()
            if self.application.application_status_id == new_status_code:
                return

        credit_limit_generation_obj = CreditLimitGeneration.objects.filter(
            application_id=self.application.id
        ).last()
        if credit_limit_generation_obj:
            account = self.application.customer.account_set.last()
            credit_limit_generation_obj.account = account
            credit_limit_generation_obj.save()

        juloLogger.info(
            {
                "message": "Credit limit generation saved",
                "application_id": self.application.id,
                "status": self.application.status,
            }
        )

        # Store application account to partnership customer data if partnership application
        partnership_application = None
        if self.application.partner:
            partnership_application_id = self.application.id
            partnership_application = PartnershipApplicationFlag.objects.filter(
                application_id=partnership_application_id,
                name=PartnershipPreCheckFlag.APPROVED,
            ).exists()

        if partnership_application:
            partnership_customer = PartnershipCustomerData.objects.filter(
                application_id=self.application.id
            ).last()

            if partnership_customer:
                account_id = (
                    Account.objects.filter(customer=self.application.customer)
                    .values_list('id', flat=True)
                    .last()
                )
                juloLogger.info(
                    {
                        "message": "Update account in the partnership customer data",
                        "application_id": self.application.id,
                        "partnership_customer_data_id": partnership_customer.id,
                        "account_id": account_id,
                    }
                )
                partnership_customer.account_id = account_id
                partnership_customer.save()

        self.application.refresh_from_db()

        if not check_click_pass(self.application):
            from juloserver.application_flow.services2.clik import CLIKClient

            clik = CLIKClient(self.application)
            clik_pass_swap_out = clik.pass_swap_out()
            swapout_dukcapil_bp_count = redis_client.get(
                CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER
            )
            if not swapout_dukcapil_bp_count:
                redis_client.set(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER, 0)
                swapout_dukcapil_bp_count = 0
            else:
                swapout_dukcapil_bp_count = int(swapout_dukcapil_bp_count)
            if (
                not clik_pass_swap_out
                and not bypass_swapout_dukcapil
                and bank_statement_success
                and swapout_dukcapil_bp_count < swapout_dukcapil_bp_quota
            ):
                redis_client.increment(CacheKey.LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER)
                swapout_dukcapil_bp_quota_left = (
                    swapout_dukcapil_bp_quota - swapout_dukcapil_bp_count - 1
                )
                if swapout_dukcapil_bp_quota_left in (0, 25, 50, 75, 100):
                    slack_channel = "#alerts-backend-onboarding"
                    mentions = "<@U04EDJJTX6Y> <@U040BRBR5LM>\n"
                    title = ":alert: ===LBS Bypass Quota Alert=== :alert: \n"
                    message = (
                        "Swapout Dukcapil Bypass Quota : "
                        + str(swapout_dukcapil_bp_quota_left)
                        + " left\n"
                    )
                    text = mentions + title + message
                    if settings.ENVIRONMENT != 'prod':
                        text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
                    send_slack_bot_message(slack_channel, text)
                bypass_swapout_dukcapil = True
            if (
                not clik_pass_swap_out
                and not bypass_swapout_dukcapil
                and not eligible_to_offline_flow
            ):
                juloLogger.info(
                    {
                        "message": "not clik.pass_swap_out",
                        "application_id": self.application.id,
                    }
                )
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    change_reason='Fail CLIK Check',
                )
                self.application.customer.update_safely(
                    can_reapply=False,
                    can_reapply_date=timezone.localtime(timezone.now()) + relativedelta(days=30),
                )
                return
            else:
                from juloserver.application_flow.tasks import async_telco_score_in_130_task

                async_telco_score_in_130_task.delay(self.application.id)

        if self.has_shopee_blacklist_executed(
            new_status_code, change_reason, bypass_swapout_dukcapil
        ):
            juloLogger.info(
                {
                    "message": "has_shopee_blacklist_executed return true",
                    "application_id": self.application.id,
                    "status": self.application.status,
                }
            )
            return

        self.application.refresh_from_db()
        if (
            self.application.application_status_id != new_status_code
            and self.application.application_status_id
            not in [
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
            ]
        ):
            process_application_status_change(
                self.application.id, new_status_code, change_reason=change_reason
            )

    def has_shopee_blacklist_executed(
        self, new_status_code, change_reason, bypass_swapout_dukcapil=False
    ) -> bool:
        from juloserver.application_flow.services2.shopee_scoring import ShopeeBlacklist

        return ShopeeBlacklist(
            self.application, new_status_code, change_reason, bypass_swapout_dukcapil
        ).run()

    def populate_bank_account_destination(self):
        category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.SELF)
        bank = Bank.objects.get(bank_name__iexact=self.application.bank_name)

        bank_account_data = [
            BankAccountDestination(
                bank_account_category=category,
                customer=self.application.customer,
                bank=bank,
                account_number=self.application.bank_account_number,
                name_bank_validation=self.application.name_bank_validation,
            )
        ]

        if self.application.is_partnership_app():
            partnership_bank_account = PartnerBankAccount.objects.filter(
                partner=self.application.partner
            ).last()
            if partnership_bank_account and partnership_bank_account.name_bank_validation_id:
                partner_category = BankAccountCategory.objects.get(
                    category=BankAccountCategoryConst.PARTNER
                )
                name_bank_validation = NameBankValidation.objects.get_or_none(
                    pk=partnership_bank_account.name_bank_validation_id
                )
                bank_partner = Bank.objects.get(xfers_bank_code=name_bank_validation.bank_code)
                bank_account_data.append(
                    BankAccountDestination(
                        bank_account_category=partner_category,
                        customer=self.application.customer,
                        bank=bank_partner,
                        account_number=partnership_bank_account.bank_account_number,
                        name_bank_validation_id=partnership_bank_account.name_bank_validation_id,
                    )
                )

        for bank_account in bank_account_data:
            if BankAccountDestination.objects.filter(
                customer=self.application.customer, account_number=bank_account.account_number
            ).exists():
                bank_account_data.remove(bank_account)

        BankAccountDestination.objects.bulk_create(bank_account_data)

    def generate_payment_method(self):
        generate_customer_va_for_julo_one(self.application)

    def process_documents_resubmission_action_j1(self):
        if self.old_status_code is not ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR:
            self.application.is_document_submitted = False
            self.application.save()

    def bypass_entry_level_141(self):
        # Make sure the status is updated not cached.
        self.application.refresh_from_db()
        if self.application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
            return

        entry_limit_process = EntryLevelLimitProcess(
            self.application.id, application=self.application
        )
        if entry_limit_process.can_bypass_141():
            if self.application.name_bank_validation.is_success:
                process_application_status_change(
                    self.application,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                    change_reason="Entry Level Bypass 141",
                )
            else:
                process_application_status_change(
                    self.application,
                    ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
                    change_reason="system_triggered",
                )

    def bypass_entry_level_124(self):
        if is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
            # bypass bank name validation if the application using uw overhaul
            bank_name_validation = True
        else:
            bank_name_validation = False
            if self.application.name_bank_validation:
                bank_name_validation = self.application.name_bank_validation.is_success

        if bank_name_validation:
            entry_limit_process = EntryLevelLimitProcess(self.application.id)
            if entry_limit_process.can_bypass_124():
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    change_reason="Entry Level Bypass 124",
                )

    def application_risk_acceptance_ciriteria_check_action(self):
        for channeling_type in get_channeling_loan_priority_list():
            criteria_check_result, reason, version = application_risk_acceptance_ciriteria_check(
                self.application, channeling_type
            )
            generate_channeling_status(
                self.application, channeling_type, criteria_check_result, reason, version
            )

    def personal_data_verification_190_async(self):
        execute_after_transaction_safely(
            lambda: send_dukcapil_official_callback_data.apply_async(args=(self.application.id,))
        )

    def notify_customers_for_specific_partners(self):
        logger.info(
            'inside notify_customers_for_specific_partners send_sms_to_specific_partner_customers, '
            'app=%s' % str(self.application.id)
        )
        # SMS notification to customers on doc submission for applications with specific partners
        execute_after_transaction_safely(
            lambda: send_sms_to_specific_partner_customers.apply_async((self.application.id,))
        )

    def validate_name_in_bank(self):
        data = {
            "name_bank_validation_id": self.application.name_bank_validation_id,
            "validation_method": "Xfers",
            "name_in_bank": self.application.name_in_bank,
            "bank_name": self.application.bank_name,
            "bank_account_number": self.application.bank_account_number,
        }
        try:
            juloLogger.info({"msg": "Trying to validate bank", "data": data})
            validate_bank(application=self.application, data=data)
        except (InvalidBankAccount, DisbursementServiceError, BankValidationError) as e:
            # note: do not generalize the exception with catch the Exception, because I need
            # to continue the XfersApiException and catch it in next process.

            juloLogger.warning(
                {
                    "msg": str(e),
                    "application_id": self.application.id,
                }
            )
            return None

        self.application.refresh_from_db()
        if (
            self.application.is_julo_one()
            or self.application.is_julo_one_ios()
            or self.application.is_grab()
            or self.application.is_julover()
            or self.application.is_julo_starter()
        ):
            name_bank_validation_id = self.application.name_bank_validation_id
        else:
            juloLogger.warning(
                {
                    "msg": "The application not in allowed workflow",
                    "application_id": self.application.id,
                }
            )
            return None

        return NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)

    def bypass_activation_call(self):
        from juloserver.application_flow.services import (
            check_bpjs_bypass,
            check_bpjs_entrylevel,
            is_offline_activation,
        )
        from juloserver.application_flow.services2 import AutoDebit

        # Check if valid for bypass
        if self.application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
            return

        if (
            not check_bpjs_entrylevel(self.application)
            and not check_bpjs_bypass(self.application)
            and not is_offline_activation(self.application)
        ):
            setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.ACTIVATION_CALL_BYPASS, is_active=True
            ).last()
            if setting is None:
                juloLogger.warning(
                    {
                        "message": "AC bypass setting not found.",
                        "customer_id": self.application.customer.id,
                    }
                )
                return

            criteria_customers_id = setting.parameters['bypass_customer_id']
            if int(str(self.application.customer.id)[-1:]) not in criteria_customers_id:
                juloLogger.warning(
                    {
                        "message": "Customer id is not in experiment AC bypass setting.",
                        "customer_id": self.application.customer.id,
                    }
                )
                return

        # Call the XFers check
        juloLogger.info(
            {
                "msg": "Trying to validate bank from bypass AC",
                "application_id": self.application.id,
            }
        )

        name_bank_validation = self.application.name_bank_validation

        if name_bank_validation and name_bank_validation.method == 'Xfers':
            try:
                name_bank_validation = self.validate_name_in_bank()
                if name_bank_validation:
                    juloLogger.info(
                        {
                            "message": "we not validate it again on x141",
                            "application_id": self.application.id,
                            "name_bank_validation_status": name_bank_validation.validation_status,
                        }
                    )
                else:
                    juloLogger.info(
                        {
                            "message": "we not validate it again on x141",
                            "application_id": self.application.id,
                            "name_bank_validation_status": "no bank validation found",
                        }
                )

            except XfersApiError as e:
                logger.warning(
                    {
                        "error": str(e),
                        "message": "fail when call validate_name_in_bank",
                        "application_id": self.application.id,
                    }
                )
                return
        else:
            name_bank_validation = self.application.name_bank_validation

        autodebit = AutoDebit(self.application)

        # bypass name bank validation to be success
        # only if email is registered in force high score feature
        feature_high_score = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
        ).last()
        if feature_high_score:
            email_in_whitelisted = self.application.email in feature_high_score.parameters
            is_bank_validation_failed = (
                name_bank_validation is not None and not name_bank_validation.is_success
            ) or name_bank_validation is None

            if email_in_whitelisted and is_bank_validation_failed:
                nbv = NameBankValidation.objects.get(pk=self.application.name_bank_validation_id)
                nbv.validation_status = 'SUCCESS'
                nbv.reason = 'success'
                nbv.save(update_fields=['validation_status', 'reason'])
                if autodebit.has_pending_tag:
                    autodebit.ask_to_activate()
                else:
                    process_application_status_change(
                        self.application.id,
                        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                        "Credit approved by system, bypassed force high score feature.",
                    )
                return

        if name_bank_validation is not None and name_bank_validation.is_success:
            if autodebit.has_pending_tag:
                autodebit.ask_to_activate()
            else:
                # Change to 150, it will be automatically to 190
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                    "Credit approved by system.",
                )
            return

        setting = FeatureSetting.objects.filter(
            feature_name="bank_validation", is_active=True
        ).last()
        if not setting:
            juloLogger.warning(
                {
                    "msg": "check_bank_name_similarity no Levenshtein feature setting",
                    "application_id": self.application.id,
                }
            )
            return

        if has_levenshtein_distance_similarity(
            self.application, name_bank_validation, setting=setting
        ):
            if autodebit.has_pending_tag:
                autodebit.ask_to_activate()
            else:
                process_application_status_change(
                    self.application.id,
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
                    "Credit approved by system, pass levenshtein distance.",
                )
        else:
            process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                "Bank validation fail by system",
            )

        return

    def deny_blocked_referral(self):
        if self.application.status != ApplicationStatusCodes.FORM_PARTIAL:
            juloLogger.warning(
                {
                    "message": f"Block attempt from application status {self.application.status}",
                    "action": "deny_blocked_referral",
                    "application_id": self.application.id,
                }
            )
            return
        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason="under performing partner",
        )

    def assign_autodebet_benefit(self):
        if not self.application.account:
            logger.warning(
                {
                    'message': 'Account is not exists',
                    'action': 'juloserver.application_flow.workflows.assign_autodebet_benefit',
                    'application_id': self.application.id,
                },
                exc_info=True,
            )
            return
        set_default_autodebet_benefit_control(self.application.account)

    def move_user_coming_from_175_to_135(self):
        if self.application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.NAME_VALIDATE_FAILED
        ):
            process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "Failed Bank Info Update",
            )
            customer = self.application.customer
            if not customer.can_reapply:
                customer.can_reapply = True
                customer.save()
                CustomerFieldChange.objects.create(
                    customer=customer, field_name="can_reapply", old_value=False, new_value=True
                )

    def move_upgraded_jstarter_to_192(self):
        from juloserver.julo_starter.services.services import user_have_upgrade_application

        workflow = Workflow.objects.filter(name=WorkflowConst.JULO_STARTER).last()
        customer = self.application.customer

        _, latest_app_upgrade = user_have_upgrade_application(customer, return_instance=True)
        if not latest_app_upgrade:
            logger.info(
                {
                    'message': 'Not have upgrade flow',
                    'customer': customer.id,
                    'application': self.application.id,
                }
            )
            return

        # get application jturbo in x191 to be moved x192
        latest_jstarter_app = Application.objects.filter(
            pk=latest_app_upgrade.application_id_first_approval,
            workflow=workflow,
        ).last()

        if not latest_jstarter_app:
            logger.error(
                {
                    'message': 'application is not Jturbo',
                    'customer': customer.id,
                    'app_upgrade_id': latest_app_upgrade.id,
                    'function': 'move_upgraded_jstarter_to_192',
                }
            )
            return

        if (
            latest_jstarter_app.application_status_id
            != ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        ):
            logger.info(
                {
                    'message': 'Skip the process the application Jturbo is not x191',
                    'application': latest_jstarter_app.id,
                    'application_status': latest_jstarter_app.application_status_id,
                }
            )
            return

        # moved the application to x192 status
        process_application_status_change(
            latest_jstarter_app.id,
            ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            "Julo Starter upgrade to Julo One is accepted",
        )

        if latest_app_upgrade.is_upgrade != 1:
            latest_app_upgrade.update_safely(is_upgrade=1)

    def is_eligible_nonfdc_autodebit(self):
        """
        Check if the application is eligible for non-FDC autodebit
        with change the status to x130.
        """
        from juloserver.application_flow.services2 import AutoDebit

        if self.application.status != ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL:
            return False

        autodebit = AutoDebit(self.application)
        if autodebit.has_pending_tag:
            process_application_status_change(
                self.application,
                ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                change_reason="Bypass no-FDC auto-debit",
            )

            return True

        return False

    def need_check_bank_statement(self):
        bank_statement = BankStatementClient(self.application)
        lbs_setting = bank_statement.get_lbs_experiment_setting()

        if not lbs_setting:
            return False

        if lbs_setting:
            ab_testing = lbs_setting.criteria['a/b_test']
            per_request = ab_testing.get('per_request')
            redis_clients = lbs_setting.criteria['clients']

            if per_request == 0 or not redis_clients:
                return False

        credit_score = CreditScore.objects.filter(application=self.application).last()

        if not credit_score:
            return False

        if check_bad_history(self.application):
            return False

        if bank_statement.blocked_lbs_by_change_reason():
            return False

        # Check fraud status if the application already submit the bank statement
        # otherwise not detected as fraud.
        submission = BankStatementSubmit.objects.filter(application_id=self.application.id).last()
        is_fraud = (submission.is_fraud or False) if submission else False

        if (
            not self.application.is_regular_julo_one()
            or self.application.status != ApplicationStatusCodes.APPLICATION_DENIED
            or customer_have_upgrade_case(self.application.customer, self.application)
            or is_fraud
        ):
            return False

        if semver.match(self.application.app_version, "<=8.12.0"):
            return BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_EMAIL
        else:
            return BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_ALL

    def process_bank_statement_revival(self, is_available_bank_statement):
        juloLogger.info(
            {
                "message": "start bank statement process",
                "application_id": self.application.id,
            }
        )

        bank_statement = BankStatementClient(self.application)
        bank_statement.set_tag_to_pending()

        landing_url = bank_statement.generate_landing_url()
        send_user_attributes_to_moengage_for_submit_bank_statement.delay(
            self.application.id, landing_url, is_available_bank_statement
        )

    def trigger_dukcapil_fr(self, async_task=False):
        if async_task:
            face_recogniton.delay(self.application.id, self.application.ktp)
        else:
            face_recogniton(self.application.id, self.application.ktp)

    def disable_bank_statement_revival(self):
        client = BankStatementClient(self.application)
        client.disable_moengage()

    def send_email_soft_rejection_for_agent_assisted_application(self):
        import juloserver.pin.services as pin_services

        # Check if customer already create pin
        is_pin_created = pin_services.does_user_have_pin(self.application.customer.user)

        if is_pin_created:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__reject_agent_assisted_email__without_create_pin': True,
            }
        else:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__reject_agent_assisted_email__with_create_pin': True,
            }

        partnership_flow_configs = PartnershipFlowFlag.objects.filter(**filters).exists()

        logger.info(
            {
                "action": "send_email_soft_rejection_for_agent_assisted_application",
                "application_id": self.application.id,
                "partnership_flow_configs": partnership_flow_configs,
                "configs": "reject_agent_assisted_email",
                "has_pin": is_pin_created,
            }
        )

        if partnership_flow_configs:
            process_sending_email_agent_assisted.delay(
                application_id=self.application.id, is_reject=True, is_x190=False
            )

    def send_email_190_for_agent_assisted_application(self):
        import juloserver.pin.services as pin_services

        # Check if customer already create pin
        is_pin_created = pin_services.does_user_have_pin(self.application.customer.user)

        if is_pin_created:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__approved_agent_assisted_email__without_create_pin': True,
            }
        else:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__approved_agent_assisted_email__with_create_pin': True,
            }

        partnership_flow_configs = PartnershipFlowFlag.objects.filter(**filters).exists()

        logger.info(
            {
                "action": "send_email_190_for_agent_assisted_application",
                "application_id": self.application.id,
                "partnership_flow_configs": partnership_flow_configs,
                "configs": "approved_agent_assisted_email",
                "has_pin": is_pin_created,
                "application_status": self.application.application_status_id,
                "application_account_id": self.application.account_id,
            }
        )

        if partnership_flow_configs:
            process_sending_email_agent_assisted.delay(
                application_id=self.application.id, is_reject=False, is_x190=True
            )

    def send_email_105_for_agent_assisted_application(self):
        import juloserver.pin.services as pin_services

        # Check if customer already create pin
        is_pin_created = pin_services.does_user_have_pin(self.application.customer.user)

        if is_pin_created:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__form_submitted_agent_assisted_email__without_create_pin': True,
            }
        else:
            filters = {
                'partner': self.application.partner,
                'name': PartnershipProductFlow.AGENT_ASSISTED,
                'configs__form_submitted_agent_assisted_email__with_create_pin': True,
            }

        partnership_flow_configs = PartnershipFlowFlag.objects.filter(**filters).exists()

        logger.info(
            {
                "action": "send_email_105_for_agent_assisted_application",
                "application_id": self.application.id,
                "partnership_flow_configs": partnership_flow_configs,
                "configs": "form_submitted_agent_assisted_email",
                "has_pin": is_pin_created,
            }
        )

        if partnership_flow_configs:
            process_sending_email_agent_assisted.delay(
                application_id=self.application.id, is_reject=False, is_x190=False
            )

    def shadow_score_with_toko_score(self):
        from juloserver.tokopedia.tasks.common_task import trigger_shadow_score_with_toko_score
        from juloserver.tokopedia.services.common_service import (
            is_allowed_to_run_shadow_score,
        )

        if is_allowed_to_run_shadow_score():
            logger.info(
                {
                    'message': 'ShadowScore: Experiment is active!',
                    'application': self.application.id,
                }
            )
            trigger_shadow_score_with_toko_score.apply_async((self.application.id,), countdown=5)

    def generate_capped_limit_for_188(self):
        if (
            self.application.is_kin_approved not in EmergencyContactConst.CAPPED_LIMIT_VALUES
            and self.application.onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        ):
            return

        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.LIMIT_CAP_EMERGENCY_CONTACT, is_active=True
        ).last()
        if not fs:
            return

        limit_cap_percentage = fs.parameters.get('limit_cap_percentage', None)
        if not limit_cap_percentage:
            logger.error(
                {
                    'action': 'generate_capped_limit_emergency_contact',
                    'message': 'Feature setting parameter is not set up correctly',
                    'application': self.application.id,
                    'is_kin_approved': self.application.is_kin_approved,
                }
            )
            raise JuloException('Terjadi kesalahan pada pembatasan limit')

        credit_limit = CreditLimitGeneration.objects.filter(
            application_id=self.application.id
        ).last()
        if not credit_limit:
            logger.error(
                {
                    'action': 'generate_capped_limit',
                    'message': 'Feature setting parameter is not set up correctly',
                    'application': self.application.id,
                    'is_kin_approved': self.application.is_kin_approved,
                }
            )
            raise JuloException('Terjadi kesalahan pada pembatasan limit')

        capped_limit = credit_limit.set_limit * limit_cap_percentage / 100
        customer = self.application.customer

        logger.info(
            {
                'action': 'generate_capped_limit',
                'message': 'Customer capped limit generated successfully',
                'customer': customer.id,
                'credit_limit_generation_id': credit_limit.id,
                'max_limit': credit_limit.max_limit,
                'capped_limit': capped_limit,
            }
        )

        customer.customer_capped_limit = capped_limit
        customer.save()

    def dukcapil_fr_j1(self) -> bool:
        """
        Check dukcapil face recognition result for J1
        """

        from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck

        setting = get_dukcapil_fr_setting()
        if not setting:
            logger.info(
                {
                    "message": "dukcapil_fr_j1, no setting.",
                    "application_id": self.application.id,
                }
            )
            # If this have no setting turned on, go to next process
            return True

        if setting.is_active is False:
            logger.info(
                {
                    "message": "dukcapil_fr_j1, setting.is_active is False",
                    "application_id": self.application.id,
                }
            )
            # If setting is disabled, go to next process
            return True

        j1_setting = setting.parameters["j1"]
        if j1_setting["is_active"] is False:
            logger.info(
                {
                    "message": "dukcapil_fr_j1, j1_setting.is_active is False",
                    "application_id": self.application.id,
                }
            )
            # If setting is disabled, go to next process
            return True

        if not DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id,
            response_code__isnull=False,
        ).exists():
            self.trigger_dukcapil_fr()

        fr_data = DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id,
            response_code__isnull=False,
        ).last()

        if not fr_data:
            logger.info(
                {
                    "message": "dukcapil_fr_j1, not fr_data",
                    "application_id": self.application.id,
                }
            )
            # No data found, go to next process
            return True

        score = float(fr_data.response_score)

        if int(fr_data.response_code) == DukcapilFRClient.InternalStatus.NIK_NOT_FOUND:
            process_application_status_change(
                self.application,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                "Dukcapil FR NIK Not Found",
            )
            return False
        elif int(fr_data.response_code) != DukcapilFRClient.InternalStatus.SUCCESS:
            logger.info(
                {
                    "message": "dukcapil_fr_j1, bad response code",
                    "application_id": self.application.id,
                    "response_code": fr_data.response_code,
                }
            )
            return True

        very_high_threshold = float(j1_setting.get("very_high", 0))
        high_threshold = float(j1_setting.get("high", 0))

        logger.info(
            {
                "message": "dukcapil_fr_j1, decision",
                "application_id": self.application.id,
                "score": score,
            }
        )

        if score == 0:
            return True
        elif score >= very_high_threshold:
            process_application_status_change(self.application, 133, "Failed Dukcapil FR too high")
            return False
        elif score < high_threshold:
            process_application_status_change(self.application, 133, "Failed Dukcapil FR too low")
            return False

        return True

    def send_cde(self):
        """Send CDE shadow score"""

        from juloserver.application_flow.services2.cde import CDEClient

        CDEClient(self.application).hit_cde()

    def process_clik_model_on_submission(self):
        from juloserver.application_flow.tasks import process_clik_model

        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CLIK_MODEL, is_active=True
        ).first()
        if fs:
            if not FDCInquiry.objects.filter(
                application_id=self.application.id,
                status__iexact=FDCStatus.FOUND,
                inquiry_status__iexact=FDCInquiryStatus.SUCCESS,
            ).exists():
                logger.info(
                    {
                        "action": "calling process_clik_model",
                        "application_id": self.application.id,
                        "application_status_code": self.application.application_status_id,
                    }
                )

                process_clik_model.delay(self.application.id)

    def dukcapil_fr_partnership_leadgen(self) -> bool:
        """
        Check dukcapil face recognition result for Partnership Leadgen
        """

        from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck

        if not self.application.partner:
            raise ValueError(
                'Invalid application id: {} not have a partner id'.format(self.application.id)
            )

        partner_name = '_'.join(self.application.partner.name.split()).lower()

        is_using_j1_dukcapil_config = True
        dukcapil_fr_parameters = {}

        # Using Partnership Config
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DUKCAPIL_FR_THRESHOLD_PARTNERSHIP_LEADGEN,
        ).last()

        if (
            setting
            and setting.is_active
            and setting.parameters.get(partner_name)
            and setting.parameters[partner_name].get("is_active")
        ):
            dukcapil_fr_parameters = setting.parameters[partner_name]
            is_using_j1_dukcapil_config = False

            logger.info(
                {
                    "message": "dukcapil_fr_partnership, using partnership config",
                    "application_id": self.application.id,
                }
            )
        else:
            logger.info(
                {
                    "message": "dukcapil_fr_partnership, not active or not found",
                    "application_id": self.application.id,
                }
            )

        # Default using Dukcapil J1
        if is_using_j1_dukcapil_config:
            setting = get_dukcapil_fr_setting()
            if not setting:
                logger.info(
                    {
                        "message": "dukcapil_fr_partnership, use j1 config no setting.",
                        "application_id": self.application.id,
                    }
                )
                # If this have no setting turned on, go to next process
                return True

            if setting.is_active is False:
                logger.info(
                    {
                        "message": "dukcapil_fr_partnership, j1 config setting.is_active is False",
                        "application_id": self.application.id,
                    }
                )
                # If setting is disabled, go to next process
                return True

            dukcapil_fr_parameters = setting.parameters["j1"]
            if dukcapil_fr_parameters["is_active"] is False:
                logger.info(
                    {
                        "message": "dukcapil_fr_partnership, j1_setting.is_active is False",
                        "application_id": self.application.id,
                    }
                )
                # If setting is disabled, go to next process
                return True

        if not DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id,
            response_code__isnull=False,
        ).exists():
            self.trigger_dukcapil_fr()

        fr_data = DukcapilFaceRecognitionCheck.objects.filter(
            application_id=self.application.id,
            response_code__isnull=False,
        ).last()

        if not fr_data:
            logger.info(
                {
                    "message": "dukcapil_fr_partnership, not fr_data",
                    "application_id": self.application.id,
                }
            )
            # No data found, go to next process
            return True

        score = float(fr_data.response_score)
        very_high_threshold = float(dukcapil_fr_parameters.get("very_high", 0))
        high_threshold = float(dukcapil_fr_parameters.get("high", 0))

        logger.info(
            {
                "message": "dukcapil_fr_partnership, decision",
                "application_id": self.application.id,
                "score": score,
            }
        )

        if score == 0:
            process_application_status_change(
                self.application, 135, "Failed to get Dukcapil FR score"
            )

            today = timezone.now()
            expired_date = today + relativedelta(days=14)

            customer = self.application.customer
            field_change_data = []
            fields_data_1 = {"customer": customer, "application": self.application}
            fields_data_1["field_name"] = "disabled_reapply_date"
            fields_data_1["old_value"] = customer.disabled_reapply_date
            customer.disabled_reapply_date = today
            fields_data_1["new_value"] = customer.disabled_reapply_date
            field_change_data.append(fields_data_1)

            fields_data_2 = {"customer": customer, "application": self.application}
            fields_data_2["field_name"] = "can_reapply_date"
            fields_data_2["old_value"] = customer.can_reapply_date
            customer.can_reapply_date = expired_date
            fields_data_2["new_value"] = customer.can_reapply_date
            field_change_data.append(fields_data_2)

            fields_data_3 = {"customer": customer, "application": self.application}
            fields_data_3["field_name"] = "can_reapply"
            fields_data_3["old_value"] = customer.can_reapply
            customer.can_reapply = False
            fields_data_3["new_value"] = customer.can_reapply
            field_change_data.append(fields_data_3)

            customer.save()

            for data in field_change_data:
                if data["old_value"] != data["new_value"]:
                    CustomerFieldChange.objects.create(**data)

            # Status change happen, do not continue to next process
            return False
        elif score >= very_high_threshold:
            process_application_status_change(self.application, 133, "Failed Dukcapil FR too high")

            # Status change happen, do not continue to next process
            return False
        elif score < high_threshold:
            process_application_status_change(self.application, 133, "Failed Dukcapil FR too low")

            # Status change happen, do not continue to next process
            return False

        return True

    def trigger_repopulate_company_address(self):
        from juloserver.application_form.tasks import repopulate_company_address

        repopulate_company_address.delay(self.application.id)


def process_bypass_julo_one_at_122(application):
    """bypass 122 for julo1"""
    juloLogger.info(
        {
            "message": "Bypass x122 started",
            "application_id": application.id,
            "status": application.status,
        }
    )
    remove_current_user()
    julo_one_service = JuloOneService()
    if check_iti_repeat(application.id) and julo_one_service.check_affordability_julo_one(
        application
    ):
        by_pass_service = JuloOneByPass()
        by_pass_service.bypass_julo_one_iti_122_to_124(application)
    else:
        juloLogger.info(
            {
                "message": "Bypass x122 failed",
                "application_id": application.id,
                "status": application.status,
            }
        )


def process_bypass_julo_one_at_120(application):
    """bypass 122 for julo1"""
    remove_current_user()

    if application.status != ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        juloLogger.info(
            {
                "message": "process_bypass_julo_one_at_120 failed",
                "application_id": application.id,
                "status": application.status,
            }
        )
        return

    julo_one_service = JuloOneService()

    if julo_one_service.check_affordability_julo_one(application):
        from juloserver.ana_api.services import check_positive_processed_income

        affordability_history = AffordabilityHistory.objects.filter(application=application).last()
        affordability_value = affordability_history.affordability_value

        is_sonic_shortform = check_application_version(application)
        credit_limit_reject_value = get_credit_limit_reject_affordability_value(
            application, is_sonic_shortform
        )
        is_affordable = True

        input_params = julo_one_service.construct_params_for_affordability(application)

        sonic_affordability_value = affordability_value
        is_monthly_income_changed = ApplicationNote.objects.filter(
            application_id=application.id, note_text='change monthly income by bank scrape model'
        ).last()
        if is_monthly_income_changed and check_positive_processed_income(application.id):
            affordability_result = compute_affordable_payment(**input_params)
            affordability_value = affordability_result['affordable_payment']

        if affordability_value < credit_limit_reject_value or (
            sonic_affordability_value and sonic_affordability_value < credit_limit_reject_value
        ):
            is_affordable = False

        if is_affordable:
            by_pass_service = JuloOneByPass()
            by_pass_service.bypass_julo_one_iti_120_to_121(application)
        else:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                change_reason="affordability_fail",
            )

    else:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason="affordability_fail",
        )
