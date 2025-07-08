from django.test.testcases import TestCase
from datetime import timedelta, date
from juloserver.grab.utils import get_grab_dpd
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account.tests.factories import (AccountFactory, AccountLookupFactory)
from juloserver.julo.tests.factories import (CustomerFactory, ApplicationFactory, PartnerFactory,
                                             StatusLookupFactory, WorkflowFactory,
                                             PaymentFactory, AuthUserFactory,
                                             LoanFactory, ProductLookupFactory, LenderFactory,
                                             ProductLineFactory, ApplicationHistoryFactory
)
from juloserver.grab.tests.factories import GrabCustomerDataFactory
from juloserver.julo.models import StatusLookup, Loan
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.grab.utils import (
    is_application_reached_180_before,
    get_grab_customer_data_anonymous_user
)
from juloserver.julo.constants import ApplicationStatusCodes


class Test_is_application_reached_180_before(TestCase):
    def setUp(self) -> None:
        self.application = ApplicationFactory()

    def test_is_application_reached_180_before_false(self):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.LOC_APPROVED,
            status_old=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        )

        self.assertFalse(is_application_reached_180_before(self.application))

    def test_is_application_reached_180_before_true(self):
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.LOC_APPROVED,
            status_old=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        )

        self.assertTrue(is_application_reached_180_before(self.application))


class Test_grab_account_payment_dpd(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow', handler='GrabWorkflowHandler')
        self.account_lookup = AccountLookupFactory(partner=self.partner, workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            application_status=StatusLookupFactory(status_code=190),
            workflow=self.workflow,
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=25000,
            first_installment_amount=25000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )
        self.payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=50000,
            installment_interest=5000,
            installment_principal=500,
            payment_number=5,
            payment_status=payment_status,
            account_payment=self.account_payment
        )

    def test_get_grab_dpd(self):
        days = get_grab_dpd(self.account_payment.id)
        self.assertGreater(days, 0)

    def test_get_grab_dpd1(self):
        self.payment.payment_status_id = 331
        self.payment.save()
        days = get_grab_dpd(self.account_payment.id)
        self.assertEqual(days, 0)


class TestGetGrabCustomerDataAnonymous(TestCase):
    def test_get_grab_customer_data_anonymous_user(self):
        anonymous_user = get_grab_customer_data_anonymous_user()
        for _ in range(5):
            self.assertEqual(anonymous_user, get_grab_customer_data_anonymous_user())
