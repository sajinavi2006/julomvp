from builtins import range
import mock
from datetime import datetime, timedelta
import pytz
from django.test import TestCase, override_settings

from juloserver.account.constants import AccountConstant
from juloserver.account_payment.services.reversal import process_customer_payment_reversal
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory, AccountPropertyFactory
from juloserver.account_payment.services.reversal import (
    process_customer_payment_reversal,
    consume_reversal_for_late_fee,
    consume_reversal_for_interest,
    consume_reversal_for_principal,
    reverse_late_fee_event,
    process_late_fee_reversal,
    reverse_is_proven,
    transfer_payment_after_reversal,
    update_ptp_status_for_origin_account_transaction,
    construct_old_paid_amount_list,
    construct_loan_payments_list
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.integapiv1.services import get_bca_payment_bill, bca_process_payment
from juloserver.julo.models import StatusLookup, PaybackTransaction, PaymentMethod
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes
)
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             PaymentFactory,
                                             PaymentEventFactory,
                                             LoanFactory, AccountingCutOffDateFactory,
                                             PaymentMethodFactory, StatusLookupFactory,
                                             ApplicationFactory,
                                             PaybackTransactionFactory,
                                             PTPFactory)


@override_settings(SUSPEND_SIGNALS=True)
class TestAccountPaymentReversal(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                account=self.account)

        self.virtual_account_postfix = '223456788'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(customer=self.customer,
                                                   virtual_account=self.virtual_account)

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
        
        self.late_fee_payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan)
        self.today = pytz.utc.localize(datetime.today())
        self.account_transaction1 = AccountTransactionFactory(account=self.account,
                                                              accounting_date=self.today,
                                                              transaction_date=self.today,
                                                              transaction_type='late_fee')
        self.payment_event = PaymentEventFactory(event_type='late_fee', payment=self.late_fee_payment,
                             event_payment=1000, payment_receipt='testing', event_date=self.today.date(),
                             added_by=self.user_auth, account_transaction=self.account_transaction1)

        self.account_property = AccountPropertyFactory(account=self.account, concurrency=True, is_proven=True)
        self.origin_account_transaction = AccountTransactionFactory(account=self.account,
                                                              accounting_date=self.today,
                                                              transaction_date=self.today,
                                                              transaction_type='payment')
        self.origin_account_tx_payment_event = PaymentEventFactory(event_type='payment', payment=self.payments[0],
                                               event_payment=1000, payment_receipt='testing', event_date=self.today.date(),
                                               added_by=self.user_auth, account_transaction=self.origin_account_transaction)
        self.org_payback_trx = PaybackTransactionFactory(customer=self.customer, payment=self.payments[0],
                                                         loan=self.loan)
        self.reversal_account_transaction = AccountTransactionFactory(account=self.account,
                                                              accounting_date=self.today,
                                                              transaction_date=self.today,
                                                              transaction_type='payment')
        self.ptp_date = datetime.today() - timedelta(days=10)
        self.ptp = PTPFactory(account_payment=self.account_payment, account=self.account,
                                ptp_date=self.ptp_date.date(), ptp_status=None, payment=self.payments[0])

    def create_repayment_using_bca(self, amount='50000', request_id='45223'):
        bca_bill = {
            'DetailBills': [],
            'AdditionalData': '',
            'CustomerName': '',
            'SubCompany': '00000',
            'CurrencyCode': 'IDR',
            'FreeTexts': [],
            'InquiryStatus': None,
            'RequestID': request_id,
            'CompanyCode': u'10994',
            'TotalAmount': 0.0,
            'InquiryReason': None,
            'CustomerNumber': self.virtual_account_postfix
        }

        inquiry_data = {'CompanyCode': self.company_code,
                        'CustomerNumber': self.virtual_account_postfix,
                        'RequestID': request_id,
                        'ChannelType': u'6014',
                        'TransactionDate': u'05/11/2020 02:15:40'
                        }

        response = get_bca_payment_bill(inquiry_data, bca_bill)
        self.assertEqual('sukses', response['InquiryReason']['Indonesian'])

        payment_data = {'CompanyCode': self.company_code,
                        'CustomerNumber': self.virtual_account_postfix,
                        'RequestID': request_id,
                        'ChannelType': u'6014',
                        'CustomerName': u'Prod Only',
                        'CurrencyCode': u'IDR',
                        'PaidAmount': amount,
                        'TotalAmount': amount,
                        'SubCompany': u'00000',
                        'TransactionDate': u'07/09/2019 02:15:40',
                        'Reference': '123456789%s' % request_id,
                        'DetailBills': [],
                        'FlagAdvice': u'Y',
                        'AdditionalData': u''
                        }

        payment_method = PaymentMethod.objects.filter(
            virtual_account=self.virtual_account).last()

        request_id = payment_data['RequestID']

        payback_trx = PaybackTransaction.objects.filter(
            payment_method=payment_method,
            transaction_id=request_id).last()

        bca_process_payment(payment_method, payback_trx, payment_data)
        return self.account.accounttransaction_set.last()

    @mock.patch('juloserver.account_payment.services.'
           'earning_cashback.get_cashback_experiment')
    def test_reverse_payment(self, mock_cashback_experiment):
        first_account_trx = self.create_repayment_using_bca()
        mock_cashback_experiment.retrun_value = False
        process_customer_payment_reversal(first_account_trx)
        last_account_trx = self.account.accounttransaction_set.last()
        self.assertEqual(last_account_trx.transaction_amount, -50000)
        self.assertEqual(last_account_trx.transaction_type, 'payment_void')
    
    def test_consume_reversal_for_late_fee(self):
        self.payments[0].paid_late_fee = 20000
        self.payments[0].save()
        remaining_amount, total_reversed_late_fee = consume_reversal_for_late_fee(self.payments,
                                                                    30000, self.account_payment)
        assert remaining_amount != None
        assert total_reversed_late_fee != None

    def test_consume_reversal_for_interest(self):
        self.payments[0].paid_interest = 20000
        self.payments[0].save()
        remaining_amount, total_reversed_interest = consume_reversal_for_interest(self.payments,
                                                                    30000, self.account_payment)
        assert remaining_amount != None
        assert total_reversed_interest != None
    
    def test_consume_reversal_for_principal(self):
        remaining_amount, total_reversed_principal = consume_reversal_for_principal(self.payments,
                                                                    30000, self.account_payment)
        assert remaining_amount != None
        assert total_reversed_principal != None
    
    def test_reverse_late_fee_event(self):
        payment_event_void = reverse_late_fee_event(self.payment_event, 800)
        assert payment_event_void != None
    
    def test_process_late_fee_reversal(self):
        result = process_late_fee_reversal(self.account_transaction1)

    def test_reverse_is_proven(self):
        self.loan.loan_status_id = LoanStatusCodes.PAID_OFF
        self.loan.loan_amount = 3000000
        self.loan.save()
        reverse_is_proven(self.account)
    
    @mock.patch('juloserver.account_payment.services.payment_flow.process_repayment_trx')
    @mock.patch('juloserver.account_payment.services.reversal.update_ptp_status_for_origin_account_transaction')
    def test_transfer_payment_after_reversal(self, mock_update_ptp_status_for_origin_account_transaction, mock_process_repayment_trx):
        account_trx_destination = AccountTransactionFactory(account=self.account,
                                                              accounting_date=self.today,
                                                              transaction_date=self.today,
                                                              transaction_type='payment')
        mock_process_repayment_trx.return_value = account_trx_destination
        mock_update_ptp_status_for_origin_account_transaction.return_value = True
        self.origin_account_transaction.payback_transaction = self.org_payback_trx
        transfer_payment_after_reversal(self.origin_account_transaction, self.account, self.reversal_account_transaction)
    

    @mock.patch('juloserver.julo.models.PTP.objects')
    def test_update_ptp_status_for_origin_account_transaction(self, mock_ptp):
        mock_ptp.filter.return_value.last.return_value = self.ptp
        response = update_ptp_status_for_origin_account_transaction(self.origin_account_transaction)
        assert response == True

    def test_construct_loan_payments_list(self):
        for payment in self.payments:
            payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME 
        old_paid_amount_list = construct_old_paid_amount_list(self.payments)
        for payment in self.payments:
            payment.payment_status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
        result = construct_loan_payments_list(self.payments, old_paid_amount_list)
        assert result == [{
            'loan_id' : self.loan.id,
            'payment_ids' : [payment.id for payment in self.payments]
        }]

    def test_construct_loan_payments_list_empty(self): 
        old_paid_amount_list = construct_old_paid_amount_list(self.payments) 
        result = construct_loan_payments_list(self.payments, old_paid_amount_list)
        assert result == []
