from __future__ import absolute_import
from django.test import TestCase
from juloserver.account.tests.factories import (
    AccountFactory
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory, AccountPaymentNoteFactory
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import StatusLookup
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    LoanFactory
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.portal.object.account_payment_status.serializers import AccountPaymentNoteSerializer


class TestAccountPaymentNoteSerializer(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='customer name 1'
        )
        active_status_code = StatusLookupFactory(status_code=320)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.product_line = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            product_line=self.product_line,
            workflow=self.workflow
        )
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
            application=self.application
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment_note = AccountPaymentNoteFactory(
            note_text='payment done',
            account_payment=self.account_payment,
            added_by=self.user,
            extra_data={
                "call_note": {
                    "contact_source": "test",
                    "call_result": "test",
                    "non_payment_reason": "test",
                }
            }
        )

    def test_basic_account_payment_note_serializer_expected_fields(self):
        serializer = AccountPaymentNoteSerializer(instance=self.account_payment_note)
        data = serializer.data
        self.assertCountEqual(set(data.keys()), set(AccountPaymentNoteSerializer.Meta.fields))

    def test_basic_account_payment_note_serializer_field_values(self):
        serializer = AccountPaymentNoteSerializer(instance=self.account_payment_note)
        data = serializer.data
        self.assertEqual(data['type_data'], 'Notes')
        self.assertEqual(data['added_by'], self.user.username)
