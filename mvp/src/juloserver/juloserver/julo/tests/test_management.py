from django.test import TestCase
from django.core.management import call_command
from juloserver.account.tests.factories import (
    CreditLimitGenerationFactory,
    AccountFactory,
    AccountLimitFactory
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    StatusLookupFactory,
    WorkflowFactory
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from io import StringIO


class TestUpdateLimitAdjustment(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application = ApplicationFactory(customer=self.customer,workflow=self.workflow)
        self.application.application_status = StatusLookupFactory(status_code=150)
        self.application.save()
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.pd_credit_model = PdCreditModelResultFactory(
            pgood=0.95, application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            max_limit=40000,
            set_limit=40000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
                '"limit_adjustment_factor": 0.8, "reduced_limit": 0}'
        )

    def test_update_limit_adjustment_failure(self):
        out = StringIO()
        call_command(
            'update_limit_adjustment', stdout=out
        )
        self.assertIn('Please provide new limit Adjustment Factor.', str(out.getvalue()))

    def test_update_limit_adjustment(self):
        out = StringIO()
        call_command(
            'update_limit_adjustment', '--pgood_upper', '1', '--pgood_lower',
            '0.93', '--old_limit_adjustment_factor', '0.8', '--new_limit_adjustment_factor',
            '0.9', stdout=out
        )
        self.assertIn("Successfully Triggered Update in Limit adjustment", out.getvalue())
