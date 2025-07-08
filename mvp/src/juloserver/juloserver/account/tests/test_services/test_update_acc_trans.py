from django.test import TestCase

from juloserver.account.models import AccountTransaction
from juloserver.account.services.account_transaction import (
    update_account_transaction_towards_late_fee,
)
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    PaymentEventFactory,
    PaymentFactory,
    StatusLookupFactory,
)


class TestUpdateAccountTransaction(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.late_fee_amount = 0
        self.account_payment.due_amount = 0
        self.account_payment.late_fee_applied = 0
        self.account_payment.save()

        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loan = LoanFactory(customer=self.customer, loan_status=self.status)
        self.status.status_code = 332
        self.status.save()

        self.event = PaymentEventFactory(
            event_type='late_fee', event_payment=-15000, added_by=self.user_auth
        )
        self.event.payment.account_payment = self.account_payment
        self.event.save()

    def test_update_account_transaction_towards_late_fee(self):
        response = update_account_transaction_towards_late_fee(self.event)
        assert response is True
        self.account_payment.refresh_from_db()
        account_transaction = AccountTransaction.objects.get(
            account=self.event.payment.account_payment.account,
            transaction_date=self.event.event_date,
            transaction_type='late_fee',
        )
        assert account_transaction.transaction_amount == self.event.event_payment
        assert account_transaction.towards_latefee == self.event.event_payment
        assert self.account_payment.late_fee_amount == abs(self.event.event_payment)
        assert self.account_payment.due_amount == abs(self.event.event_payment)
        assert self.account_payment.late_fee_applied == 1
        response_updated = update_account_transaction_towards_late_fee(self.event)
        assert response_updated is True
        self.account_payment.refresh_from_db()
        account_transaction = AccountTransaction.objects.get(
            account=self.event.payment.account_payment.account,
            transaction_date=self.event.event_date,
            transaction_type='late_fee',
        )
        assert account_transaction.transaction_amount == 2 * self.event.event_payment
        assert account_transaction.towards_latefee == 2 * self.event.event_payment
        assert self.account_payment.late_fee_amount == 2 * abs(self.event.event_payment)
        assert self.account_payment.due_amount == 2 * abs(self.event.event_payment)
        assert self.account_payment.late_fee_applied == 2
