import mock
from django.test import TestCase
from juloserver.account_payment.services.bca import *
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             ImageFactory,
                                             PaymentFactory,
                                             LoanFactory,
                                             PaymentMethodFactory,
                                             PaybackTransactionFactory,
                                             ApplicationFactory)
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.julo.models import StatusLookup
from juloserver.julo.models import CustomerWalletHistory
from juloserver.julo.statuses import LoanStatusCodes
from datetime import datetime

class TestBcaAccountPayment(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(customer=self.customer, account=self.account)
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
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(customer=self.customer,
                                                   virtual_account=self.virtual_account)
        self.payback_trx = PaybackTransactionFactory(customer=self.customer,
                                                     account=self.account,
                                                     transaction_date=datetime.today(),
                                                     payment_method=self.payment_method,
                                                     payment=self.payment)

    def test_get_bca_account_payment_bill(self):
        self.account_payment.refresh_from_db()
        data = {
            'RequestID' : 1
        }
        bca_bill = {}
        result = get_bca_account_payment_bill(self.account, self.payment_method, data, bca_bill)
        assert result != None
        self.account.accountpayment_set.all().delete()
        result = get_bca_account_payment_bill(self.account, self.payment_method, data, bca_bill)
        assert result != None
    
    @mock.patch('juloserver.account_payment.services.bca.process_repayment_trx')
    @mock.patch('juloserver.account.models.Account.get_oldest_unpaid_account_payment')
    def test_bca_process_account_payment(self, mock_unpaid_account_payment, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        self.account_payment.refresh_from_db()
        mock_unpaid_account_payment.return_value = self.account_payment
        data = {
            'PaidAmount': 12000,
            'TransactionDate': datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        }
        bca_process_account_payment(self.payment_method, self.payback_trx, data)