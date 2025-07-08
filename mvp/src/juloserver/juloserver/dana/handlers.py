from juloserver.fdc.services import check_fdc_inquiry
from juloserver.julo.workflows2.handlers import BaseActionHandler
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.dana.workflows import DanaWorkflowAction
from juloserver.dana.tasks import (
    generate_dana_skiptrace_task,
    process_completed_application_data_task,
)
from typing import Any


class DanaWorkflowHandler(BaseActionHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.action = DanaWorkflowAction(
            self.application,
            self.new_status_code,
            self.change_reason,
            self.note,
            self.old_status_code,
        )


class Dana105Handler(DanaWorkflowHandler):
    def async_task(self) -> None:
        if check_fdc_inquiry(self.application.id) and self.application.ktp:
            self.action.process_dana_fdc_result_as_init()
            self.action.set_creditor_check_as_init()
            self.action.run_fdc_task()


class Dana130Handler(DanaWorkflowHandler):
    def post(self) -> None:
        # self.action.generate_dana_credit_score() -> Disable in card PARTNER-3575
        self.action.generate_dana_credit_limit()
        execute_after_transaction_safely(
            lambda: generate_dana_skiptrace_task.delay(self.application.id)
        )


class Dana190Handler(DanaWorkflowHandler):
    def post(self) -> None:
        self.action.activate_dana_account()
        execute_after_transaction_safely(
            lambda: process_completed_application_data_task.delay(self.application.id)
        )


class Dana133Handler(DanaWorkflowHandler):
    def post(self) -> None:
        self.action.mark_user_as_fraud_account()


class Dana135Handler(DanaWorkflowHandler):
    def post(self) -> None:
        """
        Currently this will be handlers if user
        - Blacklisted
        - Delinquent
        """
        self.action.mark_user_as_delinquent()
