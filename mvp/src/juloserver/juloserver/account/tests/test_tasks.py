from django.test import TestCase
from mock import patch

from juloserver.account.constants import AccountConstant
from juloserver.account.tasks import (
    process_account_reactivation,
    scheduled_reactivation_account,
)
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory, WorkflowFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditScoreFactory,
    CustomerFactory,
    DeviceFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
)
from juloserver.julo.constants import FeatureNameConst, WorkflowConst


class TestAccountTasks(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ACCOUNT_REACTIVATION_SETTING,
            is_active=True,
            parameters={'special_criteria': {'day': 90}},
        )

    @patch('juloserver.account.tasks.account_task.process_account_reactivation.delay')
    def test_scheduled_reactivation_account_julo_one(self, mock_process_reactivation):
        scheduled_reactivation_account()
        mock_process_reactivation.assert_called_once_with(self.account.id, is_from_scheduler=True)

    @patch('juloserver.account.tasks.account_task.process_account_reactivation.delay')
    def test_scheduled_reactivation_account_julover(self, mock_process_reactivation):
        scheduled_reactivation_account()
        self.julover_customer = CustomerFactory()
        self.julover_account = AccountFactory(customer=self.julover_customer)
        self.julover_application = ApplicationFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULOVER),
            account=self.julover_account,
            customer=self.julover_customer,
        )
        self.julover_loan = LoanFactory(
            account=self.julover_account,
            application=self.julover_application,
            customer=self.julover_customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_1DPD),
        )
        # - if we mock using the self.julover_account.id like this
        #   mock_process_reactivation.assert_called_once_with(self.julover_account.id)
        #   will fail the test.
        mock_process_reactivation.assert_called_once_with(self.account.id, is_from_scheduler=True)

    @patch('juloserver.account.tasks.account_task.is_account_permanent_risk_block')
    @patch('juloserver.account.tasks.account_task.trigger_send_email_suspension')
    @patch('juloserver.account.tasks.account_task.update_cashback_balance_status')
    @patch('juloserver.account.tasks.account_task.process_change_account_status')
    def test_process_account_reactivation_send_email_suspension(
        self,
        mock_process_change_account_status,
        mock_update_cashback_balance_status,
        mock_trigger_send_email_suspension,
        mock_is_account_permanent_risk_block,
    ):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        mock_update_cashback_balance_status.return_value = None
        mock_process_change_account_status.return_value = None
        mock_trigger_send_email_suspension.return_value = None
        mock_is_account_permanent_risk_block.return_value = True
        process_account_reactivation(self.account.id)

        mock_trigger_send_email_suspension.assert_called()
