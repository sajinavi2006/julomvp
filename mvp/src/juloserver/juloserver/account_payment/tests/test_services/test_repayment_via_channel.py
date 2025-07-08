from builtins import range
from django.test import TestCase, override_settings

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.integapiv1.services import get_bca_payment_bill, bca_process_payment
from juloserver.julo.models import StatusLookup, PaybackTransaction, PaymentMethod
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             PaymentFactory,
                                             LoanFactory, AccountingCutOffDateFactory,
                                             PaymentMethodFactory, StatusLookupFactory,
                                             ApplicationFactory)


@override_settings(SUSPEND_SIGNALS=True)
class TestRePaymentViaChannel(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT))

        self.virtual_account_postfix = '123456789'
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

    def test_repayment_using_bca(self):
        bca_bill = {
            'DetailBills': [],
            'AdditionalData': '',
            'CustomerName': '',
            'SubCompany': '00000',
            'CurrencyCode': 'IDR',
            'FreeTexts': [],
            'InquiryStatus': None,
            'RequestID': u'45222',
            'CompanyCode': u'10994',
            'TotalAmount': 0.0,
            'InquiryReason': None,
            'CustomerNumber': self.virtual_account_postfix
        }

        inquiry_data = {'CompanyCode': self.company_code,
                        'CustomerNumber': self.virtual_account_postfix,
                        'RequestID': u'45222',
                        'ChannelType': u'6014',
                        'TransactionDate': u'05/11/2020 02:15:40'
                        }

        response = get_bca_payment_bill(inquiry_data, bca_bill)
        self.assertEqual('sukses', response['InquiryReason']['Indonesian'])

        payment_data = {'CompanyCode': self.company_code,
                        'CustomerNumber': self.virtual_account_postfix,
                        'RequestID': u'45222',
                        'ChannelType': u'6014',
                        'CustomerName': u'Prod Only',
                        'CurrencyCode': u'IDR',
                        'PaidAmount': u'50000',
                        'TotalAmount': u'50000',
                        'SubCompany': u'00000',
                        'TransactionDate': u'07/09/2019 02:15:40',
                        'Reference': u'123456789',
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

        payback_trx.refresh_from_db()
        self.assertTrue(payback_trx.is_processed)
        self.assertNotEqual(self.account.accounttransaction_set.all(), [])

        last_account_trx = self.account.accounttransaction_set.last()
        self.assertEqual(last_account_trx.transaction_amount, 50000)
        self.assertEqual(last_account_trx.towards_principal, 50000)
