from django.db import transaction
from juloserver.julo import services

from juloserver.apiv2.models import PdCreditModelResult
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    AffordabilityHistory,
    CustomerFieldChange,
    FeatureSetting,
    OnboardingEligibilityChecking,
    Application,
    PartnerBankAccount,
    Bank,
    ApplicationHistory,
    ApplicationUpgrade,
)

from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.customer_module.models import BankAccountCategory, BankAccountDestination
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.disbursement.models import NameBankValidation

from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.workflows import WorkflowAction

from juloserver.application_form.constants import JuloStarterFormResponseMessage
from juloserver.account.models import CreditLimitGeneration

from juloserver.personal_data_verification.services import is_pass_dukcapil_verification
from juloserver.account.services.credit_limit import (
    store_related_data_for_generate_credit_limit,
    store_account_property,
    update_related_data_for_generate_credit_limit,
)

from juloserver.julo_starter.constants import JuloStarterDukcapilCheck
from juloserver.julo_starter.exceptions import JuloStarterException
from juloserver.julo_starter.services.credit_limit import (
    generate_credit_limit,
    activate_credit_limit,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.account.models import AccountLimit

from juloserver.personal_data_verification.constants import (
    MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
)

from juloserver.julo_starter.tasks.app_tasks import trigger_push_notif_check_scoring
from juloserver.julo_starter.constants import (
    NotificationSetJStarter,
    JuloStarter190RejectReason,
)
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one

juloLogger = JuloLog(__name__)


class JuloStarterWorkflowAction(WorkflowAction):
    def affordability_calculation(self):
        from juloserver.julo_starter.handlers import JuloStarterException
        from juloserver.julo_starter.services.mocking_services import mock_determine_pgood

        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SPHINX_THRESHOLD, is_active=True
        ).last()
        if setting is None:
            juloLogger.warning(
                {
                    "msg": "affordability_calculation, setting not found",
                    "application_id": self.application.id,
                }
            )
            return

        if not self.application:
            juloLogger.warning(
                {
                    "msg": JuloStarterFormResponseMessage.APPLICATION_NOT_FOUND,
                    "application_id": self.application.id,
                }
            )
            return

        valid_application_status = [
            ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
            ApplicationStatusCodes.LOC_APPROVED,
        ]
        if (
            self.application.application_status_id not in valid_application_status
            or not self.application.is_julo_starter()
        ):
            juloLogger.warning(
                {
                    "msg": JuloStarterFormResponseMessage.APPLICATION_NOT_ALLOW,
                    "application_id": self.application.id,
                }
            )
            return

        lowest_threshold = float(setting.parameters['low']['bottom_threshold'])

        credit_model = PdCreditModelResult.objects.filter(application_id=self.application.id).last()

        if credit_model is None:
            juloLogger.warning(
                {
                    "msg": "Credit model not found",
                    "application_id": self.application.id,
                }
            )
            return

        # Based on feature setting and for testing env only
        pgood = mock_determine_pgood(self.application, credit_model.pgood)

        if pgood >= lowest_threshold:
            income = 2500000
            if self.application.has_submit_extra_form():
                income = self.application.monthly_income
        else:
            raise JuloStarterException("Illegal BPJS income check due to not allowed threshold.")

        affordability = setting.parameters['affordability_formula'] * income
        status_code = str(self.application.application_status.status_code)
        affordability_type = status_code + " Affordability"

        AffordabilityHistory.objects.create(
            application_id=self.application.id,
            application_status=self.application.application_status,
            affordability_value=affordability,
            affordability_type=affordability_type,
            reason="J-Starter Affordability check",
        )

    def credit_limit_generation(self):
        from juloserver.julo_starter.services.flow_dv_check import is_active_partial_limit

        is_active_partial_limit = is_active_partial_limit()
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SPHINX_THRESHOLD, is_active=True
        ).last()
        if setting is None:
            juloLogger.warning(
                {
                    "msg": "credit_limit_generation, setting not found",
                    "application_id": self.application.id,
                }
            )
            return

        credit_limit = generate_credit_limit(self.application, setting, is_active_partial_limit)
        if credit_limit > 0:
            new_status_code, change_reason, template_code_pn = self._get_turbo_case_params()

            # Store related data
            account = self.application.customer.account_set.last()
            if not account:
                store_related_data_for_generate_credit_limit(
                    self.application, credit_limit, credit_limit
                )
                self.application.refresh_from_db()

                # generate account_property and history
                store_account_property(self.application, credit_limit)
            else:
                update_related_data_for_generate_credit_limit(
                    self.application, credit_limit, credit_limit
                )
        else:
            template_code_pn = NotificationSetJStarter.KEY_MESSAGE_REJECTED
            new_status_code = ApplicationStatusCodes.APPLICATION_DENIED
            change_reason = 'Credit limit generation failed'

        credit_limit_generation_obj = CreditLimitGeneration.objects.filter(
            application_id=self.application.id
        ).last()
        if credit_limit_generation_obj:
            account = self.application.customer.account_set.last()
            credit_limit_generation_obj.account = account
            credit_limit_generation_obj.save()

        if new_status_code == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
            activate_credit_limit(account, self.application.id)

        if self.application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            activate_credit_limit(account, self.application.id)
            return

        self.application.refresh_from_db()
        if (
            new_status_code is not None
            and self.application.application_status_id != new_status_code
        ):
            process_application_status_change(
                self.application.id, new_status_code, change_reason=change_reason
            )

            if template_code_pn is not None:
                # Call task notif to customer
                trigger_push_notif_check_scoring.delay(self.application.id, template_code_pn)

    def _get_turbo_case_params(self):
        from juloserver.julo_starter.services.flow_dv_check import (
            is_active_full_dv,
            is_active_partial_limit,
        )

        if self.application.status == ApplicationStatusCodes.LOC_APPROVED:
            return None, None, None

        error_message = "Application {} has limit but has no Turbo flow matched.".format(
            self.application.id
        )

        if is_active_partial_limit():
            if self.application.status == ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK:
                new_status_code = ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
                change_reason = 'Partial credit limit generated'
                template_code_pn = NotificationSetJStarter.KEY_MESSAGE_OK
                return new_status_code, change_reason, template_code_pn
            elif self.application.status == ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
                new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                change_reason = 'Julo Starter Verified'
                template_code_pn = NotificationSetJStarter.KEY_MESSAGE_OK
                return new_status_code, change_reason, template_code_pn

            error_message = (
                "Application {} has active partial limit but status {} not appropriate.".format(
                    self.application.id, self.application.status
                )
            )

        elif is_active_full_dv():
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            change_reason = 'JULO Starter verified'
            template_code_pn = NotificationSetJStarter.KEY_MESSAGE_OK_FULL_DV
            return new_status_code, change_reason, template_code_pn

        juloLogger.error(
            {
                "message": error_message,
                "status": self.application.status,
                "application": self.application.id,
            }
        )
        raise JuloStarterException(error_message)

    def check_bank_name_similarity(self):
        from juloserver.application_flow.workflows import JuloOneWorkflowAction
        from juloserver.application_flow.services2.bank_validation import (
            has_levenshtein_distance_similarity,
        )

        # WARNING: override section
        from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists

        # No need to detokenize customer here, because it passed to `is_email_for_whitelists`
        # Do more detokenization if used PII attribute!
        customer = self.application.customer

        is_target_whitelist = is_email_for_whitelists(customer)
        if is_target_whitelist:
            juloLogger.info(
                {
                    'message': '[CHECK_BANK_NAME_VALIDATION] bypass',
                    'application': self.application.id,
                }
            )
            return True

        juloLogger.info(
            {
                'message': '[CHECK_BANK_NAME_VALIDATION] continue process without bypass',
                'application': self.application.id,
            }
        )

        j1_action = JuloOneWorkflowAction(
            application=self.application,
            old_status_code=self.old_status_code,
            new_status_code=self.new_status_code,
            change_reason=self.change_reason,
            note=self.note,
        )

        validation = j1_action.validate_name_in_bank()
        if not validation or not validation.validated_name or not validation.name_in_bank:
            juloLogger.warning(
                {
                    "msg": "check_bank_name_similarity no bank validation data",
                    "application_id": self.application.id,
                    "name_bank_validation": validation,
                }
            )
            process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "No Bank Validation Data",
            )
            self.application.refresh_from_db()
            return False

        if validation is not None and validation.is_success:
            return True

        juloLogger.info(
            {
                "msg": "check_bank_name_similarity calling levenshtein",
                "application_id": self.application.id,
                "status": self.application.status,
            }
        )
        if has_levenshtein_distance_similarity(self.application, validation) is False:
            process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                'Bank validation fail by system - levenshtein',
            )

            self.application.refresh_from_db()
            return False
        return True

    def dukcapil_check(self):

        # WARNING: override section
        from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists
        from juloserver.personal_data_verification.constants import DukcapilDirectError

        # No need to detokenize customer here, because it will be used in `is_email_for_whitelists `
        # Do more detokenization if used PII attribute!
        customer = self.application.customer

        is_target_whitelist = is_email_for_whitelists(customer)

        is_pass_dukcapil_verification(self.application)
        dukcapil_response = self.application.dukcapilresponse_set.last()
        results = []
        empty_quota = None
        if dukcapil_response is not None:
            if (
                dukcapil_response.errors == '05'
                or dukcapil_response.errors == DukcapilDirectError.EMPTY_QUOTA
            ):
                empty_quota = DukcapilDirectError.EMPTY_QUOTA
            results.append(dukcapil_response.name)
            results.append(dukcapil_response.birthdate)
        pass_criteria = MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS
        dukcapil_check = JuloStarterDukcapilCheck.NOT_PASSED

        feature = FeatureSetting.objects.filter(feature_name='dukcapil_verification').last()
        if feature:
            pass_criteria = feature.parameters.get(
                'minimum_checks_to_pass', MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS
            )
        if not results or None in results:
            if empty_quota == DukcapilDirectError.EMPTY_QUOTA:
                dukcapil_check = JuloStarterDukcapilCheck.BYPASS
            else:

                # No need to detokenize application here, because it only uses the status.
                # Do more detokenization if used PII attribute!
                app = Application.objects.filter(id=self.application.id).last()

                if (
                    app.status != ApplicationStatusCodes.APPLICATION_DENIED
                    and not is_target_whitelist
                ):
                    status = process_application_status_change(
                        self.application.id,
                        ApplicationStatusCodes.OFFER_REGULAR,
                        change_reason="dukcapil_failed",
                    )
                    juloLogger.info(
                        {
                            'action': 'failed dukcapil check julo starter offer j1',
                            'application_id': self.application.id,
                            'result': status,
                        }
                    )
        elif sum(results) < pass_criteria:
            dukcapil_check = JuloStarterDukcapilCheck.BYPASS

            flag_application = ApplicationRiskyCheck.objects.filter(
                application=self.application
            ).last()

            if flag_application:
                flag_application.update_safely(is_dukcapil_not_match=True)

        else:
            dukcapil_check = JuloStarterDukcapilCheck.PASSED

        # No need to detokenize customer here, because it only uses the id.
        # Do more detokenization if used PII attribute!
        customer = self.application.customer

        onboarding_eligibility_checking = OnboardingEligibilityChecking.objects.filter(
            customer_id=customer.id
        ).last()
        if onboarding_eligibility_checking.application is None:
            onboarding_eligibility_checking.update_safely(
                application=self.application,
                dukcapil_check=dukcapil_check,
                dukcapil_response=dukcapil_response,
            )
        elif onboarding_eligibility_checking.application.id == self.application.id:
            onboarding_eligibility_checking.update_safely(
                dukcapil_check=dukcapil_check, dukcapil_response=dukcapil_response
            )
        else:
            OnboardingEligibilityChecking.objects.create(
                customer=onboarding_eligibility_checking.customer,
                fdc_check=onboarding_eligibility_checking.fdc_check,
                bpjs_check=onboarding_eligibility_checking.bpjs_check,
                application=self.application,
                dukcapil_check=dukcapil_check,
                dukcapil_response=dukcapil_response,
            )

        # WARNING: override section
        if is_target_whitelist:
            juloLogger.info(
                {
                    'message': '[DUKCAPIL_CHECK] bypass',
                    'application': self.application.id,
                }
            )
            return True

        juloLogger.info(
            {
                'message': '[DUKCAPIL_CHECK] no bypass',
                'application': self.application.id,
            }
        )

        return True if dukcapil_check != JuloStarterDukcapilCheck.NOT_PASSED else False

    def set_reapply_status(self):
        from django.utils import timezone
        from juloserver.julo.models import ApplicationHistory

        if self.application.status not in (
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.APPLICATION_DENIED,
        ):
            return

        if self.application.status == ApplicationStatusCodes.APPLICATION_DENIED:
            last_history = ApplicationHistory.objects.filter(application=self.application).last()
            if last_history.change_reason != 'binary_check_failed':
                return

        with transaction.atomic():

            # No need to detokenize customer here, because it only uses the can_reapply.
            # Do more detokenization if used PII attribute!
            customer = self.application.customer

            old_value = customer.can_reapply
            old_value_date = customer.can_reapply_date
            today = timezone.now()

            customer.can_reapply = True
            customer.can_reapply_date = today
            customer.save()

            CustomerFieldChange.objects.create(
                customer=customer, field_name="can_reapply", old_value=old_value, new_value=True
            )
            CustomerFieldChange.objects.create(
                customer=customer,
                field_name="can_reapply_date",
                old_value=old_value_date,
                new_value=today
            )

        return True

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

                # No need to detokenize name bank validation here,
                # because it only uses the bank_code.
                # Do more detokenization if used PII attribute!
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

    def generate_referral_code(self):
        from juloserver.referral.services import generate_customer_level_referral_code

        generate_customer_level_referral_code(self.application)

    def disable_credit_limit(self):
        account = self.application.customer.account_set.last()
        account_limit = AccountLimit.objects.filter(account=account).last()
        available_limit = 0
        account_limit.update_safely(available_limit=available_limit)

    def company_blacklisted_x133_move_to_190_loc_reject(self):
        if (
            self.application.application_status.status_code
            == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        ):
            if ApplicationHistory.objects.filter(
                application_id=self.application.id,
                status_new=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                status_old=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
            ).exists():
                reason = JuloStarter190RejectReason.REJECT

                status_to = ApplicationStatusCodes.LOC_APPROVED
                services.process_application_status_change(self.application, int(status_to), reason)

    def has_turbo_upgrade_history(self):
        return ApplicationUpgrade.objects.filter(
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        ).exists()

    def run_dukcapil_fr_turbo_check(self):
        from juloserver.julo_starter.services.services import process_dukcapil_fr_turbo

        process_dukcapil_fr_turbo(self.application)
