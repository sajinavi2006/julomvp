from unittest.mock import patch
import mock
import pytest

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory, CheckoutRequestFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    LoanFactory,
    PaybackTransactionFactory,
    PaymentMethodLookupFactory,
    PaymentMethodFactory,
    CustomerFactory,
)
from juloserver.ovo.tests.factories import OvoWalletAccountFactory
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.ovo.services.ovo_push2pay_services import (
    construct_transaction_data,
    create_transaction_data,
    construct_push_to_pay_data,
    push_to_pay,
    construct_checkout_experience_transaction_data,
)
from juloserver.ovo.services.ovo_tokenization_services import request_webview_url

class TestCreateTransactionData(TestCase):
    def setUp(self):
        today = timezone.localtime(timezone.now()).date()
        self.account = AccountFactory()
        self.application = ApplicationFactory(account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=today)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.account_payment.refresh_from_db()
        self.loan = LoanFactory(account=self.account, customer=self.account.customer,
                                initial_cashback=2000)
        self.phone_number = '081234567890'
        self.virtual_account = 10036288420300020
        self.payment_method = PaymentMethodFactory(
            id=10,
            customer=self.account.customer,
            virtual_account=self.virtual_account,
            payment_method_name='test',
        )
        self.payment_method_lookup = PaymentMethodLookupFactory(
            name='test', image_logo_url='test.jpg'
        )
        self.checkout_request = CheckoutRequestFactory(
            account_id=self.account,
            total_payments=20000,
            status='active',
            account_payment_ids=[self.account_payment.id],
            checkout_payment_method_id=self.payment_method,
        )

    def test_construct_transaction_data(self):
        transaction_data, account_payment, message = construct_transaction_data(self.account)
        self.assertTrue(transaction_data)
        self.assertTrue(account_payment)
        self.assertFalse(message)

        self.account_payment.delete()
        transaction_data, account_payment, message = construct_transaction_data(self.account)
        self.assertFalse(transaction_data)
        self.assertFalse(account_payment)
        self.assertTrue(message)

    @pytest.mark.skip(reason="Flaky")
    def test_construct_checkout_experience_transaction_data(self):
        transaction_data, account_payment, message = construct_checkout_experience_transaction_data(
            self.account, self.checkout_request.id)
        self.assertTrue(transaction_data)
        self.assertTrue(account_payment)
        self.assertFalse(message)

        self.account_payment.status_id = 330
        self.account_payment.save()
        transaction_data, account_payment, message = construct_transaction_data(self.account)
        self.assertFalse(transaction_data)
        self.assertFalse(account_payment)
        self.assertTrue(message)

    @patch('juloserver.ovo.clients.OvoClient.send_request')
    def test_create_transaction_data(self, mock_ovo_request):
        mock_ovo_request.return_value = ({
            "response": "Transmisi Info Detil Pembelian",
            "trx_id": "3193281207679625",
            "merchant_id": "31932",
            "merchant": "JULO",
            "bill_no": "3864",
            "bill_items": [
                {
                    "tenor": "0"
                }
            ],
            "response_code": "00",
            "response_desc": "Sukses",
            "redirect_url": "https://debit-sandbox.faspay.co.id/pws/100003/0830000010100000/350acba245d569e6ba50c0108a07348af2eff3ee?trx_id=3193281207679625&merchant_id=31932&bill_no=3864"
        }, None)
        data, error = create_transaction_data(self.account)
        self.assertTrue(data)
        self.assertFalse(error)

        mock_ovo_request.return_value = ({}, "Failed mock response")
        data, error = create_transaction_data(self.account)
        self.assertFalse(data)
        self.assertTrue(error)

    def test_construct_push_to_pay_data(self):
        data = construct_push_to_pay_data('3193281261571437', self.phone_number)
        self.assertTrue(data)

    @patch('juloserver.ovo.clients.OvoClient.send_request')
    def test_push_to_pay(self, mock_ovo_request):
        mock_ovo_request.return_value = ({
             "response": "Transmisi Info Detil Pembelian",
             "trx_id": "3193281207679625",
             "merchant_id": "31932",
             "merchant": "JULO",
             "bill_no": "3864",
             "bill_items": [
                 {
                     "tenor": "0"
                 }
             ],
             "response_code": "00",
             "response_desc": "Sukses",
             "redirect_url": "https://debit-sandbox.faspay.co.id/pws/100003/0830000010100000/350acba245d569e6ba50c0108a07348af2eff3ee?trx_id=3193281207679625&merchant_id=31932&bill_no=3864"
         }, None)
        data, error = create_transaction_data(self.account)
        status, message = push_to_pay(data['transaction_id'], self.phone_number)
        self.assertTrue(status)

        status, message = push_to_pay('1233424432', self.phone_number)
        self.assertFalse(status)
        self.assertEqual(message, 'Transaction ID not found.')

        self.payback_transaction = PaybackTransactionFactory(transaction_id='1234567')
        status, message = push_to_pay(data['transaction_id'], self.phone_number)
        self.assertFalse(status)
        self.assertEqual(message, 'Payback transaction_id is exists.')


class TestOvoTokenizationBindingServices(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
        )
        self.ovo_wallet_account = OvoWalletAccountFactory(
            account_id=self.account.id, status='PENDING'
        )
        self.response_binding = {
            "responseCode": "2000700",
            "responseMessage": "Successful",
            "redirectUrl": "https://sandbox.doku.com/direct-debit/ui/binding/core/1234",
            "additionalInfo": {
                "custIdMerchant": "julo-cust-001",
                "accountStatus": "PENDING",
                "authCode": "1234",
            },
        }

        # for failed account
        self.account_failed = AccountFactory()

    @patch('juloserver.ovo.services.ovo_tokenization_services.get_doku_snap_ovo_client')
    def test_ovo_tokenization_binding_should_success(self, mock_get_doku_snap_ovo_client):
        mock_client = mock.Mock()
        mock_get_doku_snap_ovo_client.return_value = mock_client

        mock_client.ovo_registration_binding.return_value = (self.response_binding, None)

        phone_number = '6287711114100'
        response_data, error_message = request_webview_url(self.account, phone_number)

        self.assertIsNotNone(response_data['doku_url'])
        self.assertIsNotNone(response_data['success_url'])
        self.assertIsNotNone(response_data['failed_url'])
        self.assertIsNone(error_message)

    def test_ovo_tokenization_binding_should_failed(self):
        phone_number = '6287711114101'
        response_data, error_message = request_webview_url(self.account_failed, phone_number)

        self.assertEqual(error_message.code, 406)
        self.assertIsNone(response_data)
