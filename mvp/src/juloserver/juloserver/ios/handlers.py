import logging

from juloserver.julo.workflows2.handlers import BaseActionHandler
from juloserver.julo.workflows import WorkflowAction
from juloserver.ios.workflows import JuloOneIOSWorkflowAction
from juloserver.application_flow.workflows import JuloOneWorkflowAction

from juloserver.google_analytics.constants import GAEvent
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.fraud_score.tasks import fetch_monnai_application_submit_result

from juloserver.fdc.services import check_fdc_inquiry
from juloserver.application_flow.services import (
    check_liveness_detour_workflow_status_path,
    is_referral_blocked,
)
from juloserver.ios.tasks import handle_iti_ready_ios
from juloserver.julo.utils import execute_after_transaction_safely

from juloserver.julo.clients import get_julo_sentry_client

sentry_client = get_julo_sentry_client()

log = logging.getLogger(__name__)


class JuloOneIOSWorkflowHandler(BaseActionHandler):
    def __init__(self, *arg, **karg):
        super().__init__(*arg, **karg)
        self.ios_action = JuloOneIOSWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )
        self.workflow_action = WorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )
        self.j1_workflow_action = JuloOneWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class JuloOneIOS105Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        if check_fdc_inquiry(self.application.id) and self.application.ktp:
            self.workflow_action.run_fdc_task()

        if not check_liveness_detour_workflow_status_path(
            self.application,
            ApplicationStatusCodes.FORM_PARTIAL,
            status_old=self.old_status_code,
            change_reason=self.change_reason,
        ):
            self.workflow_action.update_status_apps_flyer()
        self.workflow_action.create_application_original()
        self.workflow_action.send_event_to_ga(GAEvent.REFERRAL_CODE_USED)
        self.j1_workflow_action.process_clik_model_on_submission()
        self.j1_workflow_action.trigger_repopulate_company_address()

    def post(self):
        if self.workflow_action.check_fraud_bank_account_number():
            self.workflow_action.update_customer_data()
            return

        if is_referral_blocked(self.application):
            self.workflow_action.underperforming_referral_deny_application()
            self.workflow_action.update_customer_data()
            self.workflow_action.process_customer_may_not_reapply_action()
            return
        if check_liveness_detour_workflow_status_path(
            self.application,
            ApplicationStatusCodes.FORM_PARTIAL,
            status_old=self.old_status_code,
            change_reason=self.change_reason,
        ):
            execute_after_transaction_safely(
                lambda: handle_iti_ready_ios.delay(self.application.id)
            )
            return
        self.workflow_action.update_customer_data()
        self.workflow_action.trigger_anaserver_status105()
        self.workflow_action.send_application_event_for_x105_bank_name_info()


class JuloOneIOS115Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS120Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        self.workflow_action.update_status_apps_flyer()

    def post(self):
        self.workflow_action.process_verify_ktp()
        self.workflow_action.process_customer_may_not_reapply_action()
        self.ios_action.process_hsfbp()


class JuloOneIOS121Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        self.workflow_action.update_status_apps_flyer()


class JuloOneIOS124Handler(JuloOneIOSWorkflowHandler):
    def post(self):
        self.ios_action.x124_bypass()


class JuloOneIOS127Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS130Handler(JuloOneIOSWorkflowHandler):
    def post(self):
        self.j1_workflow_action.trigger_pg_validate_bank()
        self.j1_workflow_action.process_affordability_calculation()
        self.j1_workflow_action.process_credit_limit_generation()


class JuloOneIOS131Handler(JuloOneIOSWorkflowHandler):
    def post(self):
        self.j1_workflow_action.process_documents_resubmission_action_j1()


class JuloOneIOS132Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS133Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS135Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        self.j1_workflow_action.update_status_apps_flyer()

    def post(self):
        self.j1_workflow_action.process_application_reapply_status_action()


class JuloOneIOS136Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        self.action.update_status_apps_flyer()

    def post(self):
        self.action.process_application_reapply_status_action()


class JuloOneIOS137Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS140Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS141Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        fetch_monnai_application_submit_result.delay(application_id=self.application.id)

    def post(self):
        from juloserver.apiv2.services import (
            is_email_whitelisted_to_force_high_score,
        )

        if not is_email_whitelisted_to_force_high_score(self.application.email):
            if not self.j1_workflow_action.dukcapil_fr_j1():
                return

        self.j1_workflow_action.generate_payment_method()
        self.j1_workflow_action.bypass_activation_call()
        self.j1_workflow_action.assign_autodebet_benefit()


class JuloOneIOS142Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS150Handler(JuloOneIOSWorkflowHandler):
    def post(self):
        self.action.register_or_update_customer_to_privy()


class JuloOneIOS175Handler(JuloOneIOSWorkflowHandler):
    def async_task(self):
        self.workflow_action.automate_sending_reconfirmation_email_175()


class JuloOneIOS179Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS183Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS184Handler(JuloOneIOSWorkflowHandler):
    pass


class JuloOneIOS190Handler(JuloOneIOSWorkflowHandler):
    def post(self):
        self.j1_workflow_action.process_julo_one_at_190()
        if self.application.name_bank_validation:
            self.j1_workflow_action.populate_bank_account_destination()
        self.j1_workflow_action.application_risk_acceptance_ciriteria_check_action()

    def async_task(self):
        self.workflow_action.update_status_apps_flyer()

        # send GA events
        self.workflow_action.send_event_to_ga(GAEvent.X190)
        self.workflow_action.send_application_event_by_certain_pgood(
            ApplicationStatusCodes.LOC_APPROVED
        )
        self.workflow_action.send_application_event_base_on_mycroft(
            ApplicationStatusCodes.LOC_APPROVED
        )

        self.j1_workflow_action.personal_data_verification_190_async()
        self.j1_workflow_action.shadow_score_with_toko_score()
