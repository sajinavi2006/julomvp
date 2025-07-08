from django.test import TestCase
from mock import patch
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    StatusLookup,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ProductLineFactory,
    ApplicationFactory,
    LoanFactory,
    PaymentFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.julo.utils import display_rupiah_skrtp
from juloserver.loan.services.agreement_related import get_riplay_template_julo_one
from juloserver.loan.services.sphp import generate_paid_off_letters
from juloserver.loan.tasks.sphp import send_sphp_email_task
from juloserver.payment_point.constants import TransactionMethodCode


class TestPaidLetter(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.product_line = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(
            account=self.account,
            product_line=self.product_line,
        )
        self.paid_status_code = StatusLookup.objects.get_or_create(
            status_code=StatusLookup.PAID_ON_TIME_CODE)
        if len(self.paid_status_code) > 1:
            self.paid_status_code = self.paid_status_code[0]

        self.loan = LoanFactory(
            account=self.account,
            loan_xid='1213214213129',
            application=self.application
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        PaymentFactory(loan=self.loan, payment_status=self.paid_status_code,
                       account_payment=self.account_payment)
        self.product_line_grab = ProductLineFactory(product_line_code=ProductLineCodes.GRAB2)
        self.grab_account_lookup = AccountLookupFactory(
            name=GRAB_ACCOUNT_LOOKUP_NAME)
        self.account_grab = AccountFactory(
            account_lookup=self.grab_account_lookup)
        self.grab_application = ApplicationFactory(
            account=self.account_grab,
            product_line=self.product_line_grab,
        )
        self.loan_grab = LoanFactory(
            account=self.account_grab,
            loan_xid='1213214213155',
            application=self.grab_application
        )
        self.account_payment_grab = AccountPaymentFactory(account=self.account_grab)
        PaymentFactory(
            loan=self.loan_grab, payment_status=self.paid_status_code,
            account_payment=self.account_payment_grab)

    @patch('juloserver.loan.services.sphp.pdfkit')
    def test_generate_paid_letter(self, pdkit_mock):
        pdkit_mock.from_string.return_value = 'paidletterpdf'
        generated_letter = generate_paid_off_letters([self.loan, self.loan_grab])
        # Now we expect only one letter since multiple loans are combined
        self.assertEqual(len(generated_letter), 1)


class TestRetrySendingEmail(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.product_line = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(
            account=self.account,
            product_line=self.product_line,
        )
        self.paid_status_code = StatusLookup.objects.get_or_create(
            status_code=StatusLookup.PAID_ON_TIME_CODE)
        if len(self.paid_status_code) > 1:
            self.paid_status_code = self.paid_status_code[0]

        self.loan = LoanFactory(
            account=self.account,
            loan_xid='1213214213129',
            application=self.application
        )

    @patch('juloserver.loan.tasks.sphp.send_sphp_email_task.apply_async')
    def test_retry_sending_email(self, mock_send_sphp_email):
        send_sphp_email_task(loan_id=self.loan.pk)
        mock_send_sphp_email.assert_called()

    @patch('juloserver.loan.tasks.sphp.send_sphp_email_task.apply_async')
    def test_retry_sending_email_second_time(self, mock_send_sphp_email):
        send_sphp_email_task(self.loan.pk, 1)
        mock_send_sphp_email.assert_called()

    @patch('juloserver.loan.tasks.sphp.julo_sentry_client')
    @patch('juloserver.loan.tasks.sphp.send_sphp_email_task.apply_async')
    def test_retry_sending_email_max_time(
        self, mock_send_sphp_email, _mock_get_julo_sentry_client):
        send_sphp_email_task(self.loan.pk, 2)
        _mock_get_julo_sentry_client.captureException.assert_called_once()


class TestRiplayJuloOneTemplate(TestCase):
    def setUp(self):
        # create loan with late fees, unpaid
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            loan_duration=1,
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            transaction_method_id=TransactionMethodCode.SELF.code,
        )

        # payments, should be only one since loan duration = 1
        self.first_payment = self.loan.payment_set.normal().order_by('payment_number').first()

    @patch("juloserver.loan.services.agreement_related.render_to_string")
    def test_loan_unpaid_no_late_fees(self, mock_render_to_string):
        get_riplay_template_julo_one(self.loan)

        mock_render_to_string.assert_called_once()
        _, kwargs = mock_render_to_string.call_args

        expected_first_month_due_amount = (
            self.first_payment.installment_interest + self.first_payment.installment_principal
        )
        self.assertEqual(
            kwargs['context']['total_due_amount'],
            display_rupiah_skrtp(expected_first_month_due_amount),
        )
        # should be 1 payment only
        self.assertEqual(len(kwargs['context']['payments']), 1)
        self.assertEqual(kwargs['context']['payments'][0], self.first_payment)

    @patch("juloserver.loan.services.agreement_related.render_to_string")
    def test_loan_late_fee_percent(self, mock_render_to_string):
        late_fee = 0.0533333
        expected_late_fee_pct = 5.333  # up to 3 decimal places
        self.loan.product.late_fee_pct = late_fee

        get_riplay_template_julo_one(self.loan)

        mock_render_to_string.assert_called_once()
        _, kwargs = mock_render_to_string.call_args

        self.assertEqual(
            kwargs['context']['late_fee_rate_per_day'],
            f"{expected_late_fee_pct}% per hari",
        )
