import mock
from django.test import TestCase
from juloserver.account_payment.services.use_cashback import (
    cashback_payment_process_account,
    cashback_payment_process_checkout_experience
)
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             PaymentFactory,
                                             LoanFactory,
                                             ApplicationFactory,
                                             CustomerWalletHistoryFactory)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from datetime import datetime, timedelta
from juloserver.julo.models import StatusLookup


class TestUseCashback(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.ptp_date = datetime.today() - timedelta(days=10)
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000)
        self.payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
                paid_date=datetime.today().date(),
                paid_amount=10000
            )

    @mock.patch('juloserver.account_payment.services.use_cashback.process_repayment_trx')
    @mock.patch('juloserver.account_payment.services.use_cashback.get_paid_amount_and_wallet_amount')
    @mock.patch('juloserver.account.models.Account.get_oldest_unpaid_account_payment')
    def test_cashback_payment_process_account(self, mock_unpaid_account_payment, mock_paid_amount, mock_process_repayment_trx):
        mock_unpaid_account_payment.return_value = self.account_payment
        mock_paid_amount.return_value = (0, 0, 0, 10000)
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        response = cashback_payment_process_account(
            self.account, 'testing', CashbackChangeReason.USED_TRANSFER
        )
        assert response == True

    @mock.patch('juloserver.account_payment.services.use_cashback.process_repayment_trx')
    @mock.patch('juloserver.account_payment.services.use_cashback.get_used_wallet_customer_for_paid_checkout_experience')
    def test_cashback_payment_process_checkout_experience(self, mock_paid_amount, mock_process_repayment_trx):
        mock_paid_amount.return_value = (10000)
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        response = cashback_payment_process_checkout_experience(self.account, 'testing', [self.account_payment.id])
        assert response == True

    def test_cashback_payment_process_with_account_payment_paid_off(self):
        self.account_payment.status_id = 330
        self.account_payment.save()
        response = cashback_payment_process_account(
            self.account, 'testing', CashbackChangeReason.USED_TRANSFER
        )
        assert response == False
