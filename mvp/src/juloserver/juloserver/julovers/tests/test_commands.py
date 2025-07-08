from django.test import TestCase
from django.core.management import call_command
from unittest.mock import patch
from io import StringIO

from juloserver.julo.constants import WorkflowConst

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory
)

from juloserver.line_of_credit.tests.factories_loc import (
    VirtualAccountSuffixFactory,
    MandiriVirtualAccountSuffixFactory,
)
from juloserver.julo.services2.payment_method import generate_customer_va_for_julo_one


class TestCreatePaymentMethodJulovers(TestCase):

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULOVER,
        )
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.product_line = ProductLineFactory.julover()
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            product_line=self.product_line
        )
        VirtualAccountSuffixFactory()
        MandiriVirtualAccountSuffixFactory()

    def test_create_payment_method_for_julovers(self):
        payment_method = generate_customer_va_for_julo_one(self.application)
        self.assertIsNone(payment_method)

    @patch('juloserver.julovers.management.commands.create_payment_method_for_julovers.generate_customer_va_for_julo_one')
    def test_command(self, mock_va):
        out = StringIO()
        call_command('create_payment_method_for_julovers', stdout=out)

        out.seek(0)
        self.assertIn('Payment method has been generated for Julovers.', out.readline())
