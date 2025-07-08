import mock
from django.test import TestCase
from juloserver.account_payment.services.gopay import *
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             ImageFactory,
                                             PaymentFactory,
                                             LoanFactory,
                                             ApplicationFactory,
                                             PaymentMethodFactory,
                                             PaybackTransactionFactory)
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.julo.models import StatusLookup
from juloserver.julo.models import CustomerWalletHistory
from juloserver.julo.statuses import LoanStatusCodes
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_201_CREATED
from juloserver.payback.services.gopay import GopayServices
from juloserver.payback.tests.factories import GopayAccountLinkStatusFactory, \
    GopayAutodebetTransactionFactory
from datetime import datetime

class TestGoPay(TestCase):
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
                                                     transaction_date=datetime.today(),
                                                     payment_method=self.payment_method,
                                                     account=self.account,
                                                     payment=self.payment)
    

    @mock.patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_process_gopay_initial_for_account(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        request = mock.MagicMock()
        request.user = self.user_auth
        request.path = 'https://julo.co.id/api/payback/v1/gopay/pay-account/init'
        mock_get_gopay_client().init_transaction.return_value = {
            'transaction_id': '2222222',
            'transaction': self.payback_trx,
            'server_res': 'test',
            'gopay': 'gopay'
        }
        response = process_gopay_initial_for_account(request, 5000, self.account, self.payment_method)
        assert response.status_code == 201

        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account, status='ENABLED')
        self.gopay_account.save()
        mock_get_gopay_client().gopay_tokenization_init_transaction.return_value = {
            "status_code": "200",
            "status_message": "Success, GoPay transaction is successful",
            "transaction_id": "00000269-7836-49e5-bc65-e592afafec14",
            "order_id": "order-1234",
            "gross_amount": "100000.00",
            "currency": "IDR",
            "payment_type": "gopay",
            "transaction_time": "2016-06-28 09:42:20",
            "transaction_status": "settlement",
            "fraud_status": "accept",
        }
        response = process_gopay_initial_for_account(request, 100000, self.account, self.payment_method, is_gopay_tokenization=True)
        assert response.status_code == 200

    @mock.patch('juloserver.account_payment.services.gopay.process_repayment_trx')
    def test_process_gopay_repayment_for_account(self, mock_process_repayment_trx):
        account_trx = AccountTransactionFactory()
        GopayAutodebetTransactionFactory(transaction_id=self.payback_trx.transaction_id)
        mock_process_repayment_trx.return_value = account_trx
        data = {
            'transaction_time' : datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
            'transaction_status': 'capture',
            'status_message' : 'Test message'
        }
        response = process_gopay_repayment_for_account(self.payback_trx, data)
        assert response == account_trx