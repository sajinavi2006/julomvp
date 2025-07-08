from juloserver.julo.workflows2.handlers import BaseActionHandler
from juloserver.merchant_financing.workflows import MerchantFinancingWorkflowAction


class MerchantFinancingWorkflowHandler(BaseActionHandler):
    def __init__(self, *arg, **kwargs):
        super(MerchantFinancingWorkflowHandler, self).__init__(*arg, **kwargs)
        self.action = MerchantFinancingWorkflowAction(
            self.application, self.new_status_code, self.change_reason,
            self.note, self.old_status_code
        )


class MerchantFinancing130Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        self.action.process_credit_limit_generation()


class MerchantFinancing135Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        self.action.process_reapply_merchant_application()


class MerchantFinancing160Handler(MerchantFinancingWorkflowHandler):
    def async_task(self):
        self.action.send_email_sign_sphp_general()


class MerchantFinancing190Handler(MerchantFinancingWorkflowHandler):
    def post(self):
        self.action.process_activate_account()
        self.action.populate_payment_method()
