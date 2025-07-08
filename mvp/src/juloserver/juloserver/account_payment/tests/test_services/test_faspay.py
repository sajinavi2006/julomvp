import mock
from django.test import TestCase
from juloserver.account_payment.services.faspay import *
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
from juloserver.loan_refinancing.tests.factories import WaiverRequestFactory
from juloserver.julo.statuses import LoanStatusCodes
from datetime import datetime, timedelta

class TestFasPay(TestCase):
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
                                                     payment=self.payment,
                                                     account=self.account)
        self.waiver_request = WaiverRequestFactory(loan=self.loan, account=self.account,
                                                   waiver_validity_date=datetime.today() + timedelta(days=5))

    # @patch('juloserver.account.models.Account.get_oldest_unpaid_account_payment')
    def test_faspay_payment_inquiry_account(self):
        self.account_payment.refresh_from_db()
        result = faspay_payment_inquiry_account(self.account, self.payment_method)
        assert result != None


    @mock.patch('juloserver.account_payment.services.faspay.process_j1_waiver_before_payment')
    @mock.patch('juloserver.account_payment.services.faspay.process_repayment_trx')
    def test_faspay_payment_process_account(
        self, mock_process_repayment_trx, mock_process_j1_waiver_before_payment):
        data = {
            'payment_status_code' : 330,
            'payment_status_desc' : 'Paid On Time',
            'payment_date' : datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        }
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        mock_process_j1_waiver_before_payment.return_value = True
        result = faspay_payment_process_account(self.payback_trx, data, note='test note')
        assert result == True


class TestFaspaySnap(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.due_amount = 5000000
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
                                                     payment=self.payment,
                                                     account=self.account)
        self.waiver_request = WaiverRequestFactory(loan=self.loan, account=self.account,
                                                   waiver_validity_date=datetime.today() + timedelta(days=5))
        

    def test_faspay_snap_inquiry_success(self):
        faspay_bill = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "partnerServiceId": "   10994",
                "customerNo": "",
                "virtualAccountNo": "   10994123456789",
                "virtualAccountName": "",
                "virtualAccountEmail": "",
                "virtualAccountPhone": "",
                "inquiryRequestId": "",
                "totalAmount": {
                    "value": "",
                    "currency": ""
                },
            }
        }
        self.account_payment.refresh_from_db()
        faspay_bill, due_amount = faspay_snap_payment_inquiry_account(self.account, self.payment_method, faspay_bill)

        self.assertEqual(due_amount, 5000000)
        self.assertEqual(faspay_bill['virtualAccountData']['totalAmount']['value'], '5000000.00')
        self.assertEqual(faspay_bill['virtualAccountData']['virtualAccountNo'], '   10994123456789')
