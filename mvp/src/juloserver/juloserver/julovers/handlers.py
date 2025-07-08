
from juloserver.julo.workflows2.handlers import BaseActionHandler
from juloserver.julovers.workflows import JuloverWorkflowAction


class JuloverWorkflowHandler(BaseActionHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.action = JuloverWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class Julover105Handler(JuloverWorkflowHandler):
    def post(self):
        validated = self.action.process_bank_validation()
        if validated:
            self.action.move_to_130()
        else:
            self.action.move_to_141()


class Julover130Handler(JuloverWorkflowHandler):
    def post(self):
        self.action.process_credit_score_generation()
        self.action.process_credit_limit_generation()
        self.action.generate_payment_method()
        self.action.move_to_190()


class Julover190Handler(JuloverWorkflowHandler):
    def post(self):
        # final step (activating, etc)
        self.action.populate_bank_account_destination()
        self.action.process_activate_julover_account()
        self.action.generate_referral_code()
        self.action.send_notification_email()


class Julover141Handler(JuloverWorkflowHandler):
    def post(self):
        # bank validation at 105 goes wrong
        pass
