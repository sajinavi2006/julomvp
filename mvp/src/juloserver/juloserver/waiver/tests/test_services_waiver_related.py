import mock
from django.test.testcases import TestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import (
    AccountingCutOffDateFactory,
    PaymentFactory,
    PaybackTransactionFactory,
    PaymentEventFactory,
    LoanFactory,
    StatusLookupFactory,
)
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    WaiverRecommendationFactory,
    WaiverRequestFactory,
    WaiverPaymentRequestFactory,
)
from juloserver.payback.tests.factories import (
    WaiverPaymentTempFactory,
    WaiverTempFactory,
)

from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.payback.constants import WaiverConst

from ..services.waiver_related import (
    get_j1_waiver_recommendation,
    get_partial_account_payments,
    get_existing_j1_waiver_temp,
    force_expired_j1_waiver_temp,
    j1_paid_waiver,
    j1_unpaid_waiver,
    process_j1_waiver_before_payment,
)


class TestWaiverRelatedWaiverServices(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        loan = LoanFactory(
            customer=self.account.customer,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.payment = PaymentFactory(
            account_payment=self.account_payment,
            payment_status=StatusLookupFactory(status_code=310),
            loan=loan,
        )
        self.waiver_request = WaiverRequestFactory(
            account=self.account, waiver_validity_date=timezone.localtime(timezone.now()).date()
        )
        WaiverPaymentRequestFactory(
            waiver_request=self.waiver_request,
            payment=self.payment,
            account_payment=self.account_payment,
        )
        self.waiver_temp = WaiverTempFactory(
            account=self.account,
            status=WaiverConst.ACTIVE_STATUS,
            waiver_request=self.waiver_request,
            payment=None,
        )

    def test_get_j1_waiver_recommendation(self):
        self.waiver_reco = WaiverRecommendationFactory(bucket_name="1", program_name="R4")

        waiver_reco = get_j1_waiver_recommendation(self.account.id, "R4", False, "1")
        assert self.waiver_reco.id == waiver_reco.id

        non_reco = get_j1_waiver_recommendation(self.account.id, "R5", True, "3")
        assert non_reco == None

    def test_get_existing_j1_waiver_temp(self):
        waiver_temp = get_existing_j1_waiver_temp(self.account_payment)
        assert waiver_temp == None

        WaiverPaymentTempFactory(
            waiver_temp=self.waiver_temp,
            account_payment=self.account_payment,
            payment=None
        )
        existing_waiver_temp = get_existing_j1_waiver_temp(self.account_payment)
        assert existing_waiver_temp == self.waiver_temp

    def test_force_expired_j1_waiver_temp(self):
        force_expired_j1_waiver_temp(self.account)
        self.waiver_temp.refresh_from_db()
        assert self.waiver_temp.status == WaiverConst.EXPIRED_STATUS

    @mock.patch('juloserver.account_payment.services.payment_flow.'
                'update_is_proven_account_payment_level')
    def test_j1_paid_waiver(self, mocked_is_proven):
        WaiverPaymentTempFactory(
            waiver_temp=self.waiver_temp,
            account_payment=self.account_payment,
            payment=None
        )
        mocked_is_proven.return_value = None
        status, message = j1_paid_waiver(
            "late_fee", self.account_payment, 20000, "new note", True, self.waiver_request)
        assert status == True
        assert message == "Account Transaction waive_late_fee success"

        status, message = j1_paid_waiver(
            "late_fee", self.account_payment, 20000, "new note", False, None)
        assert status == True
        assert message == "Account Transaction waive_late_fee success"

        self.account_payment.due_amount = 0
        self.account_payment.save()
        status, message = j1_paid_waiver(
            "late_fee", self.account_payment, 20000, "new note", False, None)
        assert status == True
        assert message == "Account Transaction waive_late_fee success"

        self.account_payment.paid_late_fee = self.account_payment.late_fee_amount
        self.account_payment.save()
        status, message = j1_paid_waiver(
            "late_fee", self.account_payment, 20000, "new note", False, None)
        assert status == False
        assert message == "Waive Late Fee Failed, due to 0 value"

    def test_j1_unpaid_waiver(self):
        waive_validity_date = timezone.localtime(timezone.now()).date()
        status, message = j1_unpaid_waiver(
            "late_fee", self.account_payment, 2000, "new unpaid", waive_validity_date, self.payment)
        assert status == True
        assert message == "Payment event waive_late_fee berhasil dibuat"

        WaiverPaymentTempFactory(
            waiver_temp=self.waiver_temp,
            account_payment=self.account_payment,
            payment=None
        )
        status, message = j1_unpaid_waiver(
            "late_fee", self.account_payment, 2000, "new unpaid", waive_validity_date, self.payment)
        assert status == True
        assert message == "Payment event waive_late_fee berhasil diubah"

    def test_process_j1_waiver_before_payment_normal(self):
        self.waiver_temp.status = WaiverConst.ACTIVE_STATUS
        self.waiver_temp.save()

        paid_date = timezone.localtime(timezone.now())

        waive_process = process_j1_waiver_before_payment(
            self.account_payment, self.waiver_temp.need_to_pay, paid_date + relativedelta(days=5))
        assert waive_process == None

        waive_process = process_j1_waiver_before_payment(
            self.account_payment, 100, paid_date)
        assert waive_process == None

        self.waiver_temp.waiverpaymenttemp_set.all().delete()
        WaiverPaymentTempFactory(
            waiver_temp=self.waiver_temp,
            account_payment=self.account_payment,
            payment=None
        )
        process_j1_waiver_before_payment(
            self.account_payment, self.waiver_temp.need_to_pay, paid_date)
        self.waiver_temp.refresh_from_db()
        assert self.waiver_temp.status == WaiverConst.IMPLEMENTED_STATUS

        waive_process = process_j1_waiver_before_payment(
            self.account_payment, self.waiver_temp.need_to_pay, paid_date)
        assert waive_process == None

    def test_process_j1_waiver_before_payment_partial(self):
        self.waiver_temp.status = WaiverConst.ACTIVE_STATUS
        self.waiver_temp.save()
        paid_date = timezone.localtime(timezone.now())

        account_transaction = AccountTransactionFactory(
            account=self.account,
            transaction_type="payment",
            transaction_amount=1000,
            transaction_date=timezone.localtime(timezone.now()),
            payback_transaction=PaybackTransactionFactory(),
        )
        PaymentEventFactory(
            event_type='payment',
            event_payment=1000,
            payment=self.payment,
            account_transaction=account_transaction,
        )
        self.waiver_temp.waiverpaymenttemp_set.all().delete()
        WaiverPaymentTempFactory(
            waiver_temp=self.waiver_temp,
            account_payment=self.account_payment,
            payment=None
        )
        process_j1_waiver_before_payment(
            self.account_payment, self.waiver_temp.need_to_pay, paid_date)
        self.waiver_temp.refresh_from_db()
        assert self.waiver_temp.status == WaiverConst.IMPLEMENTED_STATUS
