import logging

from juloserver.application_flow.services import (
    check_liveness_detour_workflow_status_path,
    is_experiment_application,
    is_referral_blocked,
    _assign_hsfbp_income_path_tag,
)
from juloserver.application_flow.services import pass_mycroft_threshold
from juloserver.application_flow.tasks import handle_iti_ready
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.fdc.services import check_fdc_inquiry
from juloserver.fraud_score.tasks import fetch_monnai_application_submit_result
from juloserver.fraud_security.tasks import (
    insert_fraud_application_bucket,
)
from juloserver.google_analytics.constants import GAEvent
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.workflows2.handlers import BaseActionHandler, Status120Handler
from juloserver.partnership.services.services import update_application_partner_id_by_referral_code
from juloserver.sdk.constants import LIST_PARTNER
from juloserver.sdk.constants import PARTNER_PEDE
from juloserver.face_recognition.tasks import store_fraud_face_task
from juloserver.application_flow.constants import PartnerNameConstant, JuloOneChangeReason

sentry_client = get_julo_sentry_client()

log = logging.getLogger(__name__)


class JuloOneActionHandler(BaseActionHandler):
    def __init__(self, *arg, **karg):
        super(JuloOneActionHandler, self).__init__(*arg, **karg)
        self.action = JuloOneWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class JuloOne105Handler(JuloOneActionHandler):
    def async_task(self):
        if self.application.is_partnership_leadgen():
            from juloserver.partnership.services.services import (
                partnership_leadgen_check_liveness_result,
            )

            # Partnership Leadgen Logic
            if check_fdc_inquiry(self.application.id) and self.application.ktp:
                self.action.run_fdc_task()

            self.action.send_email_105_for_agent_assisted_application()
            # Partnership Liveness check
            try:
                partnership_leadgen_check_liveness_result(
                    self.application.id,
                    self.old_status_code,
                    self.change_reason,
                )
            except Exception:
                sentry_client.captureException()

            self.action.create_application_original()
            if is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
                try:
                    self.action.trigger_process_validate_bank()
                except Exception:
                    sentry_client.captureException()
            self.action.notify_customers_for_specific_partners()
        else:
            # J1 Logic
            if (
                self.application.is_agent_assisted_submission()
                and not self.action.is_terms_agreed()
            ):
                return
            if check_fdc_inquiry(self.application.id) and self.application.ktp:
                self.action.run_fdc_task()

        if not check_liveness_detour_workflow_status_path(
            self.application,
            ApplicationStatusCodes.FORM_PARTIAL,
            status_old=self.old_status_code,
            change_reason=self.change_reason,
        ):
            self.action.update_status_apps_flyer()
        self.action.create_application_original()
        self.action.send_event_to_ga(GAEvent.REFERRAL_CODE_USED)

        # if application is Webapp will check liveness on status 105
        if self.application.is_partnership_webapp():
            self.action.partnership_check_liveness_result()

        self.action.notify_customers_for_specific_partners()
        self.action.process_clik_model_on_submission()
        self.action.trigger_repopulate_company_address()

    def post(self):
        if self.application.is_partnership_leadgen():
            # Partnership Leadgen Logic
            if self.application.bank_account_number and self.application.bank_name:
                if self.action.check_fraud_bank_account_number():
                    self.action.update_customer_data()
                    return

            if is_referral_blocked(self.application):
                self.action.underperforming_referral_deny_application()
                self.action.update_customer_data()
                self.action.process_customer_may_not_reapply_action()
                return

            # TODO: Partnership Liveness Logic

            self.action.update_customer_data()
            self.action.trigger_anaserver_status105()
            self.action.send_application_event_for_x105_bank_name_info()

        else:
            # J1 Logic
            # Currently this process for handling partnership one link, eg. Leadgen qoala
            if self.application.referral_code:
                update_application_partner_id_by_referral_code(self.application)
                self.application.refresh_from_db()

            if (
                self.application.is_agent_assisted_submission()
                and not self.action.is_terms_agreed()
            ):
                return

            if (
                self.application.partner
                and self.application.partner.name != PartnerNameConstant.GRAB
            ):
                # Handling J1 Partner User Fraud Bank Account
                if self.application.bank_account_number and self.application.bank_name:
                    if self.action.check_fraud_bank_account_number():
                        self.action.update_customer_data()
                        return
            else:
                # Handling J1 and Grab User Fraud Bank Account
                if self.action.check_fraud_bank_account_number():
                    self.action.update_customer_data()
                    return

            if is_referral_blocked(self.application):
                self.action.underperforming_referral_deny_application()
                self.action.update_customer_data()
                self.action.process_customer_may_not_reapply_action()
                return

            if check_liveness_detour_workflow_status_path(
                self.application,
                ApplicationStatusCodes.FORM_PARTIAL,
                status_old=self.old_status_code,
                change_reason=self.change_reason,
            ):
                execute_after_transaction_safely(
                    lambda: handle_iti_ready.delay(self.application.id)
                )
                return
            self.action.update_customer_data()
            self.action.trigger_anaserver_status105()
            self.action.send_application_event_for_x105_bank_name_info()


class JuloOne120Handler(JuloOneActionHandler, Status120Handler):
    def post(self):

        super(JuloOne120Handler, self).post()

        log.info({"application_id": self.application.id, "message": "JuloOne120Handler.post"})

        sonic = self.application.applicationhistory_set.filter(
            change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY
        ).exists()
        if not sonic:
            self.action.send_cde()


class JuloOne121Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.remove_application_from_fraud_application_bucket()
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.send_cde()


class JuloOne115Handler(JuloOneActionHandler):
    def async_task(self):
        execute_after_transaction_safely(
            lambda: insert_fraud_application_bucket.delay(
                self.application.id,
                self.change_reason,
            )
        )


class JuloOne122Handler(JuloOneActionHandler):
    def post(self):
        if not is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
            self.action.trigger_anaserver_status_122()


class JuloOne124Handler(JuloOneActionHandler):
    def post(self):
        _assign_hsfbp_income_path_tag(self.application.id)

        if self.action.is_eligible_nonfdc_autodebit():
            return

        self.application.refresh_from_db()
        if not pass_mycroft_threshold(self.application.id):
            return

        if not is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
            self.action.process_validate_bank()
        self.action.bypass_entry_level_124()


class JuloOne127Handler(JuloOneActionHandler):
    pass


class JuloOne128Handler(JuloOneActionHandler):
    pass


class JuloOne150Handler(JuloOneActionHandler):
    def post(self):
        self.action.register_or_update_customer_to_privy()


class JuloOne188Handler(JuloOneActionHandler):
    def post(self):
        self.action.generate_capped_limit_for_188()


class JuloOne190Handler(JuloOneActionHandler):
    def post(self):
        self.action.process_julo_one_at_190()
        if self.application.name_bank_validation:
            self.action.populate_bank_account_destination()
        self.action.application_risk_acceptance_ciriteria_check_action()
        self.action.move_upgraded_jstarter_to_192()
        self.action.send_cde()

    def async_task(self):
        self.action.update_status_apps_flyer()

        # send GA events
        self.action.send_event_to_ga(GAEvent.X190)
        self.action.send_application_event_by_certain_pgood(ApplicationStatusCodes.LOC_APPROVED)
        self.action.send_application_event_base_on_mycroft(ApplicationStatusCodes.LOC_APPROVED)

        self.action.personal_data_verification_190_async()
        self.action.shadow_score_with_toko_score()
        self.action.remove_application_from_fraud_application_bucket()


class JuloOne130Handler(JuloOneActionHandler):
    def post(self):
        from juloserver.application_flow.services import process_bad_history_customer
        from juloserver.cfs.services.core_services import get_pgood
        from juloserver.partnership.tasks import partnership_trigger_process_validate_bank
        from juloserver.julo.workflows2.tasks import process_validate_bank_task
        from juloserver.partnership.models import (
            PartnershipFlowFlag,
        )
        from juloserver.partnership.constants import PartnershipFlag

        # Partnership bank account validation
        if self.application.is_partnership_app() or self.application.is_partnership_leadgen():
            partnership_flow_flag = (
                PartnershipFlowFlag.objects.filter(
                    partner_id=self.application.partner.id,
                    name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
                )
                .values_list('configs', flat=True)
                .last()
            )
            if partnership_flow_flag and partnership_flow_flag.get('payment_gateway_service', True):
                partnership_trigger_process_validate_bank(self.application.id)
            else:
                process_validate_bank_task(self.application.id)

        if self.application.is_julo_one() and not self.application.partner:
            self.action.trigger_pg_validate_bank()

        is_bad_history_customer = process_bad_history_customer(self.application)
        if is_bad_history_customer:
            return

        # CDE that should hit when pgood below 0.85 in x130 [UND-2284]
        pgood = get_pgood(self.application.id)
        if pgood and pgood < 0.85:
            self.action.send_cde()

        self.action.process_affordability_calculation()
        self.action.process_credit_limit_generation()


class JuloOne132Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.remove_application_from_fraud_application_bucket()


class JuloOne140Handler(JuloOneActionHandler):
    def post(self):
        from juloserver.personal_data_verification.services import is_pass_dukcapil_verification

        if not is_pass_dukcapil_verification(self.application):
            self.action.send_cde()


class JuloOne141Handler(JuloOneActionHandler):
    def async_task(self):
        fetch_monnai_application_submit_result.delay(application_id=self.application.id)

    def post(self):
        from juloserver.application_flow.services import check_revive_mtl
        from juloserver.apiv2.services import (
            is_email_whitelisted_to_force_high_score,
        )

        if not is_email_whitelisted_to_force_high_score(self.application.email):
            if self.application.is_partnership_leadgen():
                if not self.action.dukcapil_fr_partnership_leadgen():
                    # Check dukcapil FR (face recognition)
                    # if status changed because of dukcapil FR
                    # stop the process there!
                    return
            else:
                if not self.action.dukcapil_fr_j1():
                    # Check dukcapil FR (face recognition),
                    # if status changed because of dukcapil FR
                    # stop the process there!
                    return

        if check_revive_mtl(self.application):
            self.action.process_validate_bank()

        self.action.generate_payment_method()
        self.action.bypass_activation_call()
        self.action.bypass_entry_level_141()
        self.action.assign_autodebet_benefit()


class JuloOne142Handler(JuloOneActionHandler):
    def post(self):
        self.action.send_cde()


class JuloOne131Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.notify_customers_for_specific_partners()

    def post(self):
        self.action.process_documents_resubmission_action_j1()


class JuloOne133Handler(JuloOneActionHandler):
    def post(self):
        self.action.process_customer_may_not_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()

        self.action.send_email_soft_rejection_for_agent_assisted_application()
        self.action.send_cde()

    def async_task(self):
        store_fraud_face_task.delay(
            self.application.id,
        )


class JuloOne135Handler(JuloOneActionHandler):
    def async_task(self):
        if not self.application.partner:
            self.action.update_status_apps_flyer()

    def post(self):
        is_available_bank_statement = self.action.need_check_bank_statement()
        if is_available_bank_statement:
            self.action.process_bank_statement_revival(is_available_bank_statement)
        else:
            self.action.disable_bank_statement_revival()
            self.action.process_application_reapply_status_action()
            if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
                self.action.revert_lender_counter()
            if self.application.partner and self.application.partner.name in LIST_PARTNER:
                self.action.callback_to_partner()

        self.action.send_email_soft_rejection_for_agent_assisted_application()
        self.action.send_cde()


class JuloOne136Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_application_reapply_status_action()


class JuloOne137Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_customer_may_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()
        if self.old_status_code is ApplicationStatusCodes.FORM_PARTIAL:
            self.action.trigger_anaserver_short_form_timeout()


class JuloOne138Handler(JuloOneActionHandler):
    pass


class JuloOne139Handler(JuloOneActionHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_customer_may_reapply_action()
        if self.old_status_code in ApplicationStatusCodes.reset_lender_counters():
            self.action.revert_lender_counter()
        self.action.move_user_coming_from_175_to_135()


class JuloOne155Handler(JuloOneActionHandler):
    def post(self):
        self.action.send_cde()


class JuloOne162Handler(JuloOneActionHandler):
    def pre(self):
        self.action.process_sphp_resubmission_action()


class JuloOne172Handler(JuloOneActionHandler):
    def post(self):
        self.action.send_lead_data_to_primo()
        if self.application.partner and self.application.partner.name == PARTNER_PEDE:
            self.action.create_loan_payment_partner()
            self.action.assign_loan_to_virtual_account()
        self.action.ac_bypass_experiment()

    def after(self):
        self.action.delete_lead_data_from_primo()


class JuloOne179Handler(JuloOneActionHandler):
    pass


class JuloOne183Handler(JuloOneActionHandler):
    pass


class JuloOne184Handler(JuloOneActionHandler):
    pass


class JuloOne185Handler(JuloOneActionHandler):
    pass


class JuloOne186Handler(JuloOneActionHandler):
    pass


class MerchantFinancingWorkflowHandler(BaseActionHandler):
    pass


class MerchantFinancing100Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        if self.application.ktp:
            self.action.run_fdc_task()


class MerchantFinancing105Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        self.action.trigger_anaserver_status105()


class MerchantFinancing120Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        self.action.assign_product_lookup_to_merchant()
