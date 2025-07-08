import mock
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.referral.tasks import generate_referral_code_for_customers


class TestGenerateReferralCode(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.customer = CustomerFactory(fullname='test')
        self.app = ApplicationFactory(
            workflow=self.workflow, customer=self.customer, product_line=self.product_line
        )

    @mock.patch('juloserver.referral.tasks.generate_customer_level_referral_code')
    def test_generate_referral_code_task(self, _mock_generate_customer_level_referral_code):
        generate_referral_code_for_customers.delay([self.app.pk])
        _mock_generate_customer_level_referral_code.assert_called()
