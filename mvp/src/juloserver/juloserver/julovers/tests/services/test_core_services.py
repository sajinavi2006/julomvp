from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from factory import SubFactory

from juloserver.account.tests.factories import (
    AccountLookupFactory,
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
)
from juloserver.julo.tests.factories import (
    StatusLookupFactory,
    AccountingCutOffDateFactory,
    PaymentFactory,
    ApplicationFactory,
    CleanLoanFactory,
    WorkflowFactory,
)
from juloserver.julovers.exceptions import JuloverException
from juloserver.julovers.services.core_services import process_julovers_auto_repayment
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.constants import WorkflowConst


PACKAGE_NAME = 'juloserver.julovers.services.core_services'


class TestProcessJuloversAutoRepayment(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account_lookup = AccountLookupFactory(name='JULOVER')
        cls.status_420 = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        cls.status_310 = StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        cls.status_330 = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        AccountingCutOffDateFactory()

    def setUp(self):
        self.account = AccountFactory(
            status=self.status_420, account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=0)
        self.application = ApplicationFactory(account=self.account)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=237, status_next=250, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=220, status_next=250, workflow=self.workflow)

    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch(f'{PACKAGE_NAME}.update_moengage_for_payment_received_task')
    @patch.object(timezone, 'now')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_process_julovers_auto_repayment(
        self, mock_cashback_experiment, mock_now, _mock_moengage, mock_get_appsflyer_service
    ):
        today = datetime(2020, 1, 1)
        mock_now.return_value = today

        account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=today,
            due_amount=10000,
            principal_amount=10000,
            interest_amount=0,
            late_fee_amount=0,
            status_id=PaymentStatusCodes.PAYMENT_NOT_DUE,
            is_restructured=False
        )
        payments = PaymentFactory.create_batch(
            2,
            account_payment=account_payment,
            loan=SubFactory(CleanLoanFactory, loan_amount=5000, account=self.account),
            payment_status=self.status_310,
            due_date=today,
            due_amount=5000,
            installment_principal=5000,
            installment_interest=0,
            late_fee_amount=0,
            payment_number=0
        )
        mock_cashback_experiment.return_value = False
        is_success = process_julovers_auto_repayment(account_payment)
        account_payment.refresh_from_db()

        self.assertTrue(is_success)
        self.assertEqual(0, account_payment.due_amount)
        self.assertEquals(PaymentStatusCodes.PAID_ON_TIME, account_payment.status_id)
        for payment in payments:
            payment.refresh_from_db()
            self.assertEqual(PaymentStatusCodes.PAID_ON_TIME, payment.payment_status_id)
            self.assertEqual(0, payment.due_amount)
            # self.assertEqual(LoanStatusCodes.PAID_OFF, payment.loan.loan_status_id)

        self.account_limit.refresh_from_db()
        # self.assertEqual(10000, self.account_limit.available_limit)

    def test_process_julovers_auto_repayment_paid_status(self):
        today = datetime(2020, 1, 1)
        account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=today,
            due_amount=10000,
            principal_amount=10000,
            interest_amount=0,
            late_fee_amount=0,
            status_id=PaymentStatusCodes.PAID_ON_TIME,
            is_restructured=False
        )

        with self.assertRaises(JuloverException) as context:
            process_julovers_auto_repayment(account_payment)

        exception = context.exception
        self.assertEqual("Julover Account payment already paid", exception.args[0])
        self.assertEqual(account_payment.id, exception.args[1])
