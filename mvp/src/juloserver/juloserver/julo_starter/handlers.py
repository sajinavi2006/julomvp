from juloserver.julo.workflows2.handlers import BaseActionHandler

from juloserver.julo.clients import get_julo_sentry_client
from .workflow import JuloStarterWorkflowAction
from juloserver.application_flow.handlers import JuloOne137Handler

from juloserver.application_flow.services import (
    check_liveness_detour_workflow_status_path,
    is_referral_blocked,
)
from juloserver.google_analytics.constants import GAEvent
from juloserver.julo.constants import ApplicationStatusCodes, OnboardingIdConst
from juloserver.julolog.julolog import JuloLog
from juloserver.julo_starter.tasks.app_tasks import trigger_push_notif_check_scoring
from juloserver.julo_starter.constants import NotificationSetJStarter, JuloStarterFlow
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo_starter.services.submission_process import (
    check_black_list_android,
    run_fraud_check,
)
from juloserver.julo_starter.services.services import determine_js_workflow
from juloserver.julo_starter.services.onboarding_check import eligibility_checking
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_jstarter_limit_approved,
)
from juloserver.fraud_security.tasks import (
    insert_fraud_application_bucket,
)

sentry_client = get_julo_sentry_client()
juloLogger = JuloLog(__name__)


class JuloStarterException(Exception):
    pass


class JuloStarterWorkflowHandler(BaseActionHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.action = JuloStarterWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class JuloStarter105Handler(JuloStarterWorkflowHandler):
    def async_task(self):
        if not check_liveness_detour_workflow_status_path(
            self.application,
            ApplicationStatusCodes.FORM_PARTIAL,
            status_old=self.old_status_code,
            change_reason=self.change_reason,
        ):
            self.action.update_status_apps_flyer()
        self.action.create_application_original()
        self.action.send_event_to_ga(GAEvent.REFERRAL_CODE_USED)
        self.action.trigger_process_validate_bank()
        self.action.send_application_event_for_x105_bank_name_info()

    def post(self):
        if self.action.check_fraud_bank_account_number():
            self.action.update_customer_data()
            return
        if is_referral_blocked(self.application):
            self.action.underperforming_referral_deny_application()
            self.action.update_customer_data()
            self.action.process_customer_may_not_reapply_action()
            return
        self.action.update_customer_data()

        # dukcapil check is moved and called after emulator check
        is_blacklisted = check_black_list_android(self.application)
        if is_blacklisted:
            return
        run_fraud_check(self.application)

        if self.application.onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
            eligibility_checking(
                self.application.customer,
                is_send_pn=False,
                application_id=self.application.id,
                process_change_application_status=True,
                onboarding_id=self.application.onboarding_id,
            )
            return

        self.action.trigger_anaserver_status105()


class JuloStarter106Handler(JuloStarterWorkflowHandler):
    def post(self):
        self.action.set_reapply_status()


class JuloStarter107Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter108Handler(JuloStarterWorkflowHandler):
    def post(self):
        if self.action.check_bank_name_similarity():
            self.action.affordability_calculation()
            self.action.credit_limit_generation()
            self.action.generate_payment_method()


class JuloStarter109Handler(JuloStarterWorkflowHandler):
    def async_task(self):
        from juloserver.julo_starter.tasks.app_tasks import (
            trigger_master_agreement_pn_subtask,
            trigger_is_eligible_bypass_to_x121,
        )

        trigger_master_agreement_pn_subtask.delay(self.application.id)
        execute_after_transaction_safely(
            lambda: trigger_is_eligible_bypass_to_x121.apply_async(
                (self.application.id,), countdown=1
            )
        )


class JuloStarter115Handler(JuloStarterWorkflowHandler):
    def async_task(self):
        execute_after_transaction_safely(
            lambda: insert_fraud_application_bucket.delay(
                self.application.id,
                self.change_reason,
            )
        )


class JuloStarter121Handler(JuloStarterWorkflowHandler):
    def post(self):
        self.action.run_dukcapil_fr_turbo_check()
        self.action.populate_bank_account_destination()

    def async_task(self):
        self.action.update_status_apps_flyer()
        self.action.remove_application_from_fraud_application_bucket()


class JuloStarter135Handler(JuloStarterWorkflowHandler):
    def post(self):
        self.action.set_reapply_status()


class JuloStarter137Handler(JuloOne137Handler):
    pass


class JuloStarter149Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter153Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter183Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter184Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter185Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter186Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter190Handler(JuloStarterWorkflowHandler):
    def post(self):
        from juloserver.account.constants import AccountConstant

        if self.action.has_turbo_upgrade_history():
            juloLogger.info(
                {
                    'name': 'has_turbo_downgrade_history',
                    'source': 'JuloStarter190Handler.post',
                    'application': self.application.id,
                }
            )
            return

        self.action.populate_bank_account_destination()
        self.action.generate_referral_code()
        is_fraud = self.application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        ).exists()
        if is_fraud:
            self.action.disable_credit_limit()
            return

        if determine_js_workflow(self.application) == JuloStarterFlow.PARTIAL_LIMIT:
            account = self.application.customer.account_set.last()
            app_history = self.application.applicationhistory_set.filter(
                status_new=ApplicationStatusCodes.APPLICATION_DENIED
            ).exists()
            if account.status_id != AccountConstant.STATUS_CODE.deactivated and not app_history:
                self.action.credit_limit_generation()
                send_user_attributes_to_moengage_for_jstarter_limit_approved.delay(
                    self.application.id, JuloStarterFlow.PARTIAL_LIMIT
                )
                trigger_push_notif_check_scoring.delay(
                    self.application.id, NotificationSetJStarter.KEY_MESSAGE_FULL_LIMIT
                )

    def async_task(self):
        from juloserver.julo_starter.tasks.app_tasks import trigger_master_agreement_pn_subtask

        if self.action.has_turbo_upgrade_history():
            juloLogger.info(
                {
                    'name': 'has_turbo_downgrade_history',
                    'source': 'JuloStarter190Handler.async_task',
                    'application': self.application.id,
                }
            )
            return

        trigger_master_agreement_pn_subtask.delay(self.application.id)
        self.action.update_status_apps_flyer()
        self.action.send_application_event_by_certain_pgood(ApplicationStatusCodes.LOC_APPROVED)
        self.action.send_application_event_base_on_mycroft(ApplicationStatusCodes.LOC_APPROVED)


class JuloStarter133Handler(JuloStarterWorkflowHandler):
    def async_task(self):
        juloLogger.info(
            {
                "action": "jstarter_async_task_at_133",
                "message": "application_id: {}".format(self.application.id),
            }
        )
        trigger_push_notif_check_scoring.delay(
            self.application.id, NotificationSetJStarter.KEY_MESSAGE_REJECTED
        )
        self.action.remove_application_from_fraud_application_bucket()

    def post(self):
        self.action.process_customer_may_not_reapply_action()


class JuloStarter191Handler(JuloStarterWorkflowHandler):
    pass


class JuloStarter192Handler(JuloStarterWorkflowHandler):
    pass
