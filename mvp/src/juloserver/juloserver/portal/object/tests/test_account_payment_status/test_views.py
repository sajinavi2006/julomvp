from unittest.mock import patch
from django.test import TestCase
from django.test import Client
from django.test import override_settings
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.julo.tests.factories import ApplicationFactory, AuthUserFactory, CustomerFactory, LoanFactory, PaymentFactory, PaymentMethodFactory, ProductLineFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

testing_middleware = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware',
    'juloserver.routing.middleware.CustomReplicationMiddleware']


@override_settings(MIDDLEWARE=testing_middleware)
class TestPaymentEvent(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.client = Client()
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000, application=self.application
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
        )
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer,
            virtual_account=self.virtual_account
        )

    @patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    def test_input_negative_number(self, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        data = {
            'account_payment_id': self.account_payment.id,
            'partial_payment': '-300.000',
            'paid_date': '02-08-2022',
            'notes': "sadasdasd",
            'use_credits': "false",
            'payment_method_id': self.payment_method.id,
            'payment_receipt': "123123",
            'event_type': "payment"
        }
        response = self.client.post(
            '/account_payment_status/add_account_transaction/?account_payment_id=%s' %
            self.account_payment.id,
            data)
        result = ({
            'messages': "Can not input negative value",
            'result': 'failed'
        })
        self.assertEqual(response.json(), result)

    @patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    def test_payment_for_j1(self, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        data = {
            'account_payment_id' : self.account_payment.id,
            'partial_payment' : '300.000',
            'paid_date': '02-08-2022',
            'notes': "sadasdasd",
            'use_credits': "false",
            'payment_method_id': self.payment_method.id,
            'payment_receipt': "123123",
            'event_type': "payment"
        }
        response = self.client.post('/account_payment_status/add_account_transaction/?account_payment_id=%s' %
                                    self.account_payment.id,
                                    data)
        result = ({
                    'messages': "payment event success",
                    'result': 'success'
                })
        self.assertEqual(response.json(), result)

    @patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    def test_payment_for_julover(self, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth)
        account = AccountFactory(customer=customer)
        Client()
        account_payment = AccountPaymentFactory(account=account)
        virtual_account_postfix = '123456789'
        company_code = '10994'
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=product_line
        )
        loan = LoanFactory(
            account=account,
            customer=customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000, application=application
        )
        PaymentFactory(
            payment_status=account_payment.status,
            due_date=account_payment.due_date,
            account_payment=account_payment,
            loan=loan,
            change_due_date_interest=0,
        )
        virtual_account = '{}{}'.format(company_code, virtual_account_postfix)
        payment_method = PaymentMethodFactory(
            customer=customer,
            virtual_account=virtual_account
        )

        data = {
            'account_payment_id' : account_payment.id,
            'partial_payment' : '300.000',
            'paid_date': '02-08-2022',
            'notes': "sadasdasd",
            'use_credits': "false",
            'payment_method_id': payment_method.id,
            'payment_receipt': "123123",
            'event_type': "payment"
        }
        response = self.client.post('/account_payment_status/add_account_transaction/?account_payment_id=%s' %
                                    account_payment.id,
                                    data)
        result = ({
                    'messages': "payment event success",
                    'result': 'success'
                })
        self.assertEqual(response.json(), result)

    @patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    def test_payment_for_overpaid_j1(self, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        data = {
            'account_payment_id' : self.account_payment.id,
            'partial_payment' : '10.000.000',
            'paid_date': '02-08-2022',
            'notes': "sadasdasd",
            'use_credits': "false",
            'payment_method_id': self.payment_method.id,
            'payment_receipt': "123123",
            'event_type': "payment"
        }
        response = self.client.post('/account_payment_status/add_account_transaction/?account_payment_id=%s' %
                                    self.account_payment.id,
                                    data)
        result = ({
                    'messages': "payment event success",
                    'result': 'success'
                })
        self.assertEqual(response.json(), result)

    @patch('juloserver.account_payment.services.manual_transaction.process_repayment_trx')
    def test_payment_for_overpaid_julover(self, mock_process_repayment_trx):
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth)
        account = AccountFactory(customer=customer)
        Client()
        account_payment = AccountPaymentFactory(account=account)
        virtual_account_postfix = '123456789'
        company_code = '10994'
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=product_line
        )
        loan = LoanFactory(
            account=account,
            customer=customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000, application=application
        )
        PaymentFactory(
            payment_status=account_payment.status,
            due_date=account_payment.due_date,
            account_payment=account_payment,
            loan=loan,
            change_due_date_interest=0,
            paid_amount=10000
        )
        virtual_account = '{}{}'.format(company_code, virtual_account_postfix)
        payment_method = PaymentMethodFactory(
            customer=customer,
            virtual_account=virtual_account
        )

        data = {
            'account_payment_id' : account_payment.id,
            'partial_payment' : '1.000.000',
            'paid_date': '02-08-2022',
            'notes': "sadasdasd",
            'use_credits': "false",
            'payment_method_id': payment_method.id,
            'payment_receipt': "123123",
            'event_type': "payment"
        }
        response = self.client.post('/account_payment_status/add_account_transaction/?account_payment_id=%s' %
                                    account_payment.id,
                                    data)
        result = ({
                    "messages": 'payment cannot be overpaid',
                    "result": 'failed'
                })
        self.assertEqual(response.json(), result)
