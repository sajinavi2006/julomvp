from builtins import range
from mock import patch
from django.test import TestCase, override_settings
from datetime import datetime, timedelta
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    ExperimentGroupFactory,
    AccountTransactionFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    CheckoutRequestFactory,
)
from juloserver.account_payment.services.payment_flow import (
    process_repayment_trx,
    consume_payment_for_interest,
    consume_payment_for_principal,
    consume_payment_for_late_fee,
    update_payment_paid_off_status,
    update_account_payment_paid_off_status,
    notify_account_payment_over_paid,
    update_checkout_request_by_process_repayment,
    update_collection_risk_bucket_paid_first_installment,
    reversal_update_collection_risk_bucket_paid_first_installment,
    get_and_update_latest_loan_status,
)
from juloserver.julo.models import StatusLookup, CashbackCounterHistory
from juloserver.julo.statuses import (
    LoanStatusCodes,
    ApplicationStatusCodes,
)
from juloserver.loan_refinancing.tests.factories import (WaiverRequestFactory,
                                                         WaiverApprovalFactory,
                                                         WaiverPaymentApprovalFactory,
                                                         WaiverPaymentRequestFactory)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    PaymentFactory,
    PaybackTransactionFactory,
    LoanFactory,
    AccountingCutOffDateFactory,
    FeatureSettingFactory,
    ExperimentSettingFactory,
    ProductLineFactory,
    ProductLookupFactory,
    WorkflowFactory,
    StatusLookupFactory,
)
from juloserver.account_payment.utils import get_expired_date_checkout_request
from juloserver.minisquad.tests.factories import CollectionBucketInhouseVendorFactory
from juloserver.minisquad.models import CollectionBucketInhouseVendor

from juloserver.early_limit_release.constants import (
    FeatureNameConst,
)
from juloserver.account.models import Account
from juloserver.minisquad.constants import ExperimentConst as MinisqiadExperimentConstant
from juloserver.julo.constants import WorkflowConst
from juloserver.account.constants import AccountLookupNameConst
from juloserver.julo.tests.factories import CollectionRiskVerificationCallListFactory


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPaymentFlow(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        self.account = AccountFactory(id=12345, customer=self.customer,
                                      account_lookup=self.account_lookup)
        self.application = ApplicationFactory(account=self.account, workflow=self.workflow)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.product_line = ProductLineFactory(
            product_line_code=1,
            product_line_type='J1'
        )
        self.loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            product=ProductLookupFactory(product_line=self.product_line, cashback_payment_pct=0.01)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.save()
        self.waiver_request = WaiverRequestFactory(loan=self.loan, account=self.account,
                                                   waiver_validity_date=datetime.today() + timedelta(days=5))
        self.waiver_approval = WaiverApprovalFactory(waiver_request=self.waiver_request)
        self.waiver_payment_approval1 = WaiverPaymentApprovalFactory(waiver_approval=self.waiver_approval,
                                                                    payment=self.payments[0])
        self.waiver_payment_approval2 = WaiverPaymentApprovalFactory(waiver_approval=self.waiver_approval,
                                                                    payment=self.payments[1])
        self.waiver_payment_request1 = WaiverPaymentRequestFactory(waiver_request=self.waiver_request,
                                                                  payment=self.payments[0],
                                                                  requested_principal_waiver_amount=10000)
        self.waiver_payment_request2 = WaiverPaymentRequestFactory(waiver_request=self.waiver_request,
                                                                  payment=self.payments[1],
                                                                  requested_principal_waiver_amount=10000)
        self.checkout_request = CheckoutRequestFactory(
            account_id=self.account,
            payment_event_ids=[3],
            total_payments=20000,
            status='redeemed'
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE_REPAYMENT_SIDE, is_active=True
        )
        self.cashback_exp = ExperimentSettingFactory(
            is_active=False,
            code=MinisqiadExperimentConstant.CASHBACK_NEW_SCHEME,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control": [0, 1, 2, 3, 4],
                    "experiment": [5, 6, 7, 8, 9]
                }
            }
        )

    def test_do_partial_payment(self):
        today = datetime.today()
        payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            amount=self.account_payment.principal_amount)
        process_repayment_trx(payback_trx)
        partially_paid_account_payment = AccountPayment.objects.get(pk=self.account_payment.id)
        due_amount_after_paid = self.account_payment.due_amount - payback_trx.amount
        self.assertEqual(partially_paid_account_payment.due_amount, due_amount_after_paid)
        self.assertEqual(partially_paid_account_payment.paid_principal, payback_trx.amount)

    @patch('juloserver.account_payment.services.payment_flow.execute_after_transaction_safely')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_do_paid_off_payment(
        self, mock_cashback_experiment, mock_execute_after_transaction_safely
    ):
        today = datetime.today()
        payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            amount=self.account_payment.due_amount)
        collection_inhouse_vendor = CollectionBucketInhouseVendorFactory(
            account_payment=self.account_payment,
            bucket='JULO_B3',
            vendor=False
        )
        mock_cashback_experiment.retrun_value = False
        process_repayment_trx(payback_trx)
        result = CollectionBucketInhouseVendor.objects.get_or_none(
            account_payment=self.account_payment.id)
        self.assertIsNone(result)
        self.assertEquals(11, mock_execute_after_transaction_safely.call_count)

    @patch('juloserver.account_payment.services.payment_flow.execute_after_transaction_safely')
    def test_cashback_new_scheme(self, mock_execute_after_transaction_safely):
        self.cashback_exp.is_active = True
        self.cashback_exp.save()
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            amount=self.account_payment.due_amount)
        process_repayment_trx(payback_trx)
        account = Account.objects.get(pk=self.account.id)
        assert CashbackCounterHistory.objects.count() == 2
        # self.assertEquals(1, account.cashback_counter)
        self.assertEquals(11, mock_execute_after_transaction_safely.call_count)

    def test_consume_payment_for_interest(self):
        remaining_amount, total_paid_interest = consume_payment_for_interest(self.payments, 30000, self.account_payment)
        assert remaining_amount != None
        assert total_paid_interest != None
        remaining_amount, total_paid_interest = consume_payment_for_interest(self.payments, 30000, self.account_payment,
                                                                             self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_interest != None
        self.waiver_approval.waiver_request = None
        self.waiver_approval.save()
        remaining_amount, total_paid_interest = consume_payment_for_interest(self.payments, 30000, self.account_payment,
                                                                             self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_interest != None

    def test_consume_payment_for_late_fee(self):
        remaining_amount, total_paid_late_fee = consume_payment_for_late_fee(self.payments, 30000, self.account_payment)
        assert remaining_amount != None
        assert total_paid_late_fee != None
        remaining_amount, total_paid_late_fee = consume_payment_for_late_fee(self.payments, 30000, self.account_payment,
                                                                             self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_late_fee != None
        self.waiver_approval.waiver_request = None
        self.waiver_approval.save()
        remaining_amount, total_paid_late_fee = consume_payment_for_late_fee(self.payments, 30000, self.account_payment,
                                                                             self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_late_fee != None

    def test_consume_payment_for_principal(self):
        remaining_amount, total_paid_principal = consume_payment_for_principal(self.payments, 30000, self.account_payment,
                                                                               self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_principal != None
        self.waiver_approval.waiver_request = None
        self.waiver_approval.save()
        remaining_amount, total_paid_principal = consume_payment_for_principal(self.payments, 30000, self.account_payment,
                                                                               self.waiver_request, waiver_amount=5000)
        assert remaining_amount != None
        assert total_paid_principal != None

    def test_update_payment_paid_off_status(self):
        today = datetime.today()
        payment = self.payments[0]
        old_status = payment.status
        update_payment_paid_off_status(payment)
        payment.due_date = today - timedelta(days=3)
        payment.paid_date = today
        payment.save()
        update_payment_paid_off_status(payment)
        payment.paid_date = today + timedelta(days=4)
        payment.save()
        update_payment_paid_off_status(payment)

    def test_update_account_payment_paid_off_status(self):
        old_status = self.account_payment.status_id
        today = datetime.today()
        update_account_payment_paid_off_status(self.account_payment)
        self.account_payment.due_date = today - timedelta(days=3)
        self.account_payment.paid_date = today
        self.account_payment.save()
        update_account_payment_paid_off_status(self.account_payment)
        self.account_payment.paid_date = today + timedelta(days=4)
        self.account_payment.save()
        update_account_payment_paid_off_status(self.account_payment)

    def test_notify_account_payment_over_paid(self):
        notify_account_payment_over_paid(self.account_payment, 30000)

    def test_update_checkout_request_by_process_repayment(self):
        update_checkout_request_by_process_repayment(
            self.checkout_request,
            [1, 2],
            10000,
            10000
        )

    def test_update_checkout_request_by_process_repayment_paid_off(self):
        update_checkout_request_by_process_repayment(
            self.checkout_request,
            [1, 2],
            20000,
            20000
        )
        self.checkout_request.refresh_from_db()
        self.assertEqual(self.checkout_request.status, 'finished')
    
    def test_update_collection_risk_bucket_paid_first_installment(self):
        self.account_payment.due_amount = 0
        self.account_payment.save()
        AccountTransactionFactory(account=self.account)
        collection_risk_bucket = CollectionRiskVerificationCallListFactory(
            customer=self.customer, 
            account=self.account,
            application=self.application,
            account_payment=self.account_payment,
            is_paid_first_installment=False,
        )
        update_collection_risk_bucket_paid_first_installment(
            self.account.id, self.account_payment.id
        )
        collection_risk_bucket.refresh_from_db()
        self.assertEqual(collection_risk_bucket.is_paid_first_installment, True)

    def test_reversal_update_collection_risk_bucket_paid_first_installment(self):
        customer = CustomerFactory()
        account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        account = AccountFactory(id=100,customer=customer,
                                      account_lookup=account_lookup)
        application = ApplicationFactory(account=account)
        account_payment = AccountPaymentFactory(account=account)
        AccountTransactionFactory(account=account,transaction_type = 'payment', reversal_transaction_id=1)
        collection_risk_bucket = CollectionRiskVerificationCallListFactory(
            customer=customer, 
            account=account,
            application=application,
            account_payment=account_payment,
            is_paid_first_installment=True,
        )
        reversal_update_collection_risk_bucket_paid_first_installment(account.id)
        collection_risk_bucket.refresh_from_db()
        self.assertEqual(collection_risk_bucket.is_paid_first_installment, False)

    def test_reversal_update_collection_risk_bucket_paid_first_installment_not_found(self):
        customer = CustomerFactory()
        account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        account = AccountFactory(id=101, customer=customer,
                                      account_lookup=account_lookup)
        application = ApplicationFactory(account=account)
        account_payment = AccountPaymentFactory(account=account, due_amount=0)
        AccountTransactionFactory(account=account,transaction_type = 'payment')
        collection_risk_bucket = CollectionRiskVerificationCallListFactory(
            customer=customer, 
            account=account,
            application=application,
            account_payment=account_payment,
            is_paid_first_installment=True,
        )
        reversal_update_collection_risk_bucket_paid_first_installment(account.id)
        collection_risk_bucket.refresh_from_db()
        self.assertEqual(collection_risk_bucket.is_paid_first_installment, True)

    def test_reversal_update_collection_risk_bucket_paid_first_installment_partial(self):
        customer = CustomerFactory()
        account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        account = AccountFactory(id=102, customer=customer,
                                      account_lookup=account_lookup)
        application = ApplicationFactory(account=account)
        account_payment = AccountPaymentFactory(account=account)
        AccountTransactionFactory(account=account,transaction_type = 'payment', reversal_transaction_id=2)
        collection_risk_bucket = CollectionRiskVerificationCallListFactory(
            customer=customer, 
            account=account,
            application=application,
            account_payment=account_payment,
            is_paid_first_installment=True,
        )
        reversal_update_collection_risk_bucket_paid_first_installment(account.id)
        collection_risk_bucket.refresh_from_db()
        self.assertEqual(collection_risk_bucket.is_paid_first_installment, False)

    def test_reversal_update_collection_risk_bucket_paid_first_installment_partial_not_found(self):
        customer = CustomerFactory()
        account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=AccountLookupNameConst.JULO1)
        account = AccountFactory(id=102, customer=customer,
                                      account_lookup=account_lookup)
        application = ApplicationFactory(account=account)
        account_payment = AccountPaymentFactory(account=account, due_amount=0)
        AccountTransactionFactory(account=account,transaction_type = 'payment')
        collection_risk_bucket = CollectionRiskVerificationCallListFactory(
            customer=customer, 
            account=account,
            application=application,
            account_payment=account_payment,
            is_paid_first_installment=True,
        )
        reversal_update_collection_risk_bucket_paid_first_installment(account.id)
        collection_risk_bucket.refresh_from_db()
        self.assertEqual(collection_risk_bucket.is_paid_first_installment, True)

    @patch('juloserver.account_payment.services.payment_flow.execute_after_transaction_safely')
    def test_get_and_update_loan_statuses(self, mock_execute_after_transaction_safely):
        self.loan_2 = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            product=ProductLookupFactory(product_line=self.product_line, cashback_payment_pct=0.01),
        )
        loan_statuses = [
            {
                'loan_id': self.loan.id,
                'new_status_code': LoanStatusCodes.CURRENT,
            },
            {
                'loan_id': self.loan.id,
                'new_status_code': LoanStatusCodes.PAID_OFF,
            },
            {
                'loan_id': self.loan_2.id,
                'new_status_code': LoanStatusCodes.LOAN_8DPD,
            },
            {
                'loan_id': self.loan_2.id,
                'new_status_code': LoanStatusCodes.LOAN_150DPD,
            },
        ]
        get_and_update_latest_loan_status(loan_statuses)
        self.assertEqual(2, mock_execute_after_transaction_safely.call_count)
