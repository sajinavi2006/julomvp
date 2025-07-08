from django.conf import settings
from mock import MagicMock, patch
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.utils import generate_sha512
from juloserver.payback.models import GopayAccountLinkStatus, GopayRepaymentTransaction
from juloserver.payback.services.gopay import GopayServices

from juloserver.julo.tests.factories import (
    PaymentFactory, PaymentMethodFactory, LoanFactory, StatusLookup, CustomerFactory,
    MobileFeatureSettingFactory, PaybackTransactionFactory, ApplicationFactory)
from juloserver.julo.models import PaymentEvent, PaybackTransaction
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.payback.tests.factories import GopayAccountLinkStatusFactory


class TestGopayServices(TestCase):

    def setUp(self):
        self.loan = LoanFactory()
        self.customer = CustomerFactory()
        self.status_lookup = StatusLookup.objects.all().first()
        self.payment_method = PaymentMethodFactory()
        self.account = AccountFactory(
            customer=self.customer
        )
        self.application = ApplicationFactory(
            customer=self.customer,
        )

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_init_transaction(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        payment = PaymentFactory(loan=self.loan, payment_status=self.status_lookup)
        mock_get_gopay_client().init_transaction.return_value = {
            'transaction_id': '1111111',
            'server_res': 'test'
        }
        result = gopay_service.init_transaction(payment, self.payment_method, 10000)
        transaction = PaybackTransaction.objects.filter(transaction_id='1111111').first()
        self.assertIsNotNone(transaction)
        self.assertEqual(result['gopay'], 'test')

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_init_account_payment_transaction(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        account_payment = AccountPaymentFactory()
        mock_get_gopay_client().init_transaction.return_value = {
            'transaction_id': '2222222',
            'server_res': 'test'
        }
        result = gopay_service.init_account_payment_transaction(account_payment, self.payment_method, 10000)
        transaction = PaybackTransaction.objects.filter(transaction_id='2222222').first()
        self.assertIsNotNone(transaction)
        self.assertEqual(result['gopay'], 'test')

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_get_transaction_status(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        gopay_service.get_transaction_status('11111111')
        mock_get_gopay_client().get_status.assert_called_once_with(
            {
                'transaction_id': '11111111'
            }
        )

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_gross_to_net_amount(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        result = gopay_service.gross_to_net_amount(10000)
        self.assertEqual(result, 9890)

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_gross_to_net_amount(self, mock_get_gopay_client):
        gopay_service = GopayServices()
        MobileFeatureSettingFactory(
            feature_name='gopay_admin_fee', is_active=True,
            parameters={
                'admin_percent_fee': 10
            })
        result = gopay_service.get_amount_with_fee(10000)
        self.assertEqual(result, 9890)

    @patch('juloserver.payback.services.gopay.send_sms_async')
    @patch('juloserver.payback.services.gopay.process_waiver_after_payment')
    @patch('juloserver.payback.services.gopay.process_partial_payment')
    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_process_loan(
            self, mock_get_gopay_client, mock_process_partial_payment,
            mock_process_waiver_after_payment, mock_send_sms_async):
        gopay_service = GopayServices()
        payment = self.loan.payment_set.first()
        transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            loan=self.loan,
            payment_method=self.payment_method
        )
        data = {
            'transaction_time': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
            'transaction_status': 'settlement',
            'status_message': 'nothing'
        }
        mock_process_partial_payment.return_value = True
        gopay_service.process_loan(self.loan, payment, transaction, data)
        mock_process_waiver_after_payment.assert_called()
        mock_send_sms_async.delay.assert_called()

    @patch('juloserver.payback.services.gopay.create_pbt_status_history')
    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_update_transaction_status(self, mock_get_gopay_client, mock_create_pbt_status_history):
        gopay_service = GopayServices()
        payment = self.loan.payment_set.first()
        transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            loan=self.loan,
            payment_method=self.payment_method
        )
        data = {
            'transaction_status': 'settlement',
            'status_message': 'nothing'
        }
        gopay_service.update_transaction_status(transaction, data)
        mock_create_pbt_status_history.assert_called_once()
        transaction.refresh_from_db()
        self.assertEqual(transaction.status_desc, 'nothing')
        self.assertEqual(transaction.status_code, 2)

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_create_pay_account(self, mock_get_gopay_client):
        gopay_services = GopayServices()

        mock_get_gopay_client().create_pay_account.return_value = {
          "status_code": "201",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "PENDING",
          "actions": [
            {
              "name": "activation-link-url",
              "method": "GET",
              "url": "http://api.midtrans.com/v2/gopay/redirect/gpar_6123269-1425-21e3-bc44-e592afafec14/link"
            },
            {
              "name": "activation-link-app",
              "method": "GET",
              "url": "https://simulator.sandbox.midtrans.com/gopay/partner/web/otp?id=cd965ea9-120e-441a-bddf-1d94ae4659c9"
            }
          ]
        }

        data, error = gopay_services.create_pay_account(self.customer)
        self.assertFalse(error)
        self.assertTrue('web_linking' in data)

        data, error = gopay_services.create_pay_account(self.customer)
        self.assertFalse(data)
        self.assertEqual(error, 'Akun Anda sedang dalam proses registrasi')

        GopayAccountLinkStatus.objects.all().delete()
        self.application.mobile_phone_1 = None
        self.application.save()
        self.customer.phone = None
        self.customer.save()
        data, error = gopay_services.create_pay_account(self.customer)
        self.assertFalse(data)
        self.assertEqual(error, 'Phone number not found')

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_get_pay_account(self, mock_get_gopay_client):
        gopay_services = GopayServices()
        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account)
        self.gopay_account.save()
        new_gopay_payment_method = PaymentMethodFactory(
            payment_method_code='1004', 
            customer=self.account.customer,
            payment_method_name='GoPay Tokenization'
        )
        mock_get_gopay_client().get_pay_account.return_value = {
          "status_code": "200",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "ENABLED",
          "metadata": {
            "payment_options": [
              {
                "name": "GOPAY_WALLET",
                "active": True,
                "balance": {
                  "value": "1000000.00",
                  "currency": "IDR"
                },
                "metadata": {},
                "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ=="
              },
              {
                "name": "PAY_LATER",
                "active": True,
                "balance": {
                  "value": "350000.00",
                  "currency": "IDR"
                },
                "metadata": {},
                "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
              }
            ]
          }
        }

        data, error = gopay_services.get_pay_account(self.account)
        self.assertFalse(error)
        self.assertTrue(data['account_status'] == 'ENABLED')

        new_gopay_payment_method.delete()
        data, error = gopay_services.get_pay_account(self.account)
        self.assertFalse(data)
        self.assertEqual(error, 'Payment method not found')

        PaymentMethodFactory(
            payment_method_code='1004', 
            customer=self.account.customer,
            payment_method_name='GoPay Tokenization'
        )
        self.gopay_account.delete()
        data, error = gopay_services.get_pay_account(self.account)
        self.assertFalse(error)
        self.assertTrue(data['account_status'] == 'DISABLED')

        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account)
        self.gopay_account.save()

        mock_get_gopay_client().get_pay_account.return_value = {
          "status_code": "201",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "PENDING"
        }

        data, error = gopay_services.get_pay_account(self.account)
        self.assertFalse(error)
        self.assertEqual(data['message'], 'Akun Anda sedang dalam proses registrasi')

        mock_get_gopay_client().get_pay_account.return_value = {
          "status_code": "200",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "ENABLED",
          "metadata": {
            "payment_options": [
              {
                "name": "PAY_LATER",
                "active": True,
                "balance": {
                  "value": "350000.00",
                  "currency": "IDR"
                },
                "metadata": {},
                "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
              }
            ]
          }
        }

        data, error = gopay_services.get_pay_account(self.account)
        self.assertFalse(data)
        self.assertEqual(error, 'GoPay wallet not provided')

    def test_pay_account_link_notification(self):
        gopay_services = GopayServices()
        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account)
        key = generate_sha512('{}{}{}{}'.format(
            self.gopay_account.pay_account_id,
            'ENABLED',
            '200',
            settings.GOPAY_SERVER_KEY
        ))

        data, error = gopay_services.pay_account_link_notification(
            self.gopay_account.pay_account_id,
            key,
            '200',
            'ENABLED'
        )

        self.assertTrue(data)
        self.assertFalse(error)

        key = generate_sha512('{}{}{}{}'.format(
            self.gopay_account.pay_account_id,
            'ENABLED',
            '400',
            settings.GOPAY_SERVER_KEY
        ))

        data, error = gopay_services.pay_account_link_notification(
            self.gopay_account.pay_account_id,
            key,
            '200',
            'ENABLED'
        )

        self.assertFalse(data)
        self.assertEqual(error, 'Signature doesnt match')

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_unbind_pay_account(self, mock_get_gopay_client):
        gopay_services = GopayServices()
        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account)
        self.gopay_account.status = 'ENABLED'
        self.gopay_account.save()

        mock_get_gopay_client().unbind_pay_account.return_value = {
          "status_code": "204",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "DISABLED",
          "channel_response_code": "0",
          "channel_response_message": "Process service request successfully."
        }

        data, error = gopay_services.unbind_gopay_account_linking(self.account)
        self.assertFalse(error)
        self.assertEqual(data, 'Akun Anda telah di deaktivasi')

        mock_get_gopay_client().unbind_pay_account.return_value = {
          "status_code": "204",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "PENDING",
          "channel_response_code": "0",
          "channel_response_message": "Process service request successfully."
        }

        self.gopay_account.status = 'ENABLED'
        self.gopay_account.save()
        data, error = gopay_services.unbind_gopay_account_linking(self.account)
        self.assertFalse(error)
        self.assertEqual(data, 'Akun Anda sedang dalam proses deaktivasi')

        mock_get_gopay_client().unbind_pay_account.return_value = {
          "status_code": "204",
          "payment_type": "gopay",
          "account_id": "00000269-7836-49e5-bc65-e592afafec14",
          "account_status": "EXPIRED",
          "channel_response_code": "0",
          "channel_response_message": "Process service request successfully."
        }

        data, error = gopay_services.unbind_gopay_account_linking(self.account)
        self.assertFalse(error)
        self.assertEqual(data, 'Mohon ulangi kembali proses deaktivasi')

        self.gopay_account.delete()
        data, error = gopay_services.unbind_gopay_account_linking(self.account)
        self.assertFalse(data)
        self.assertEqual(error, 'Akun GoPay Anda belum terhubung/tidak terdaftar')

    @patch('juloserver.payback.services.gopay.get_gopay_client')
    def test_gopay_tokenization_init_account_payment_transaction(self, mock_get_gopay_client):
        gopay_services = GopayServices()
        account_payment = AccountPaymentFactory(account=self.account)
        self.payment_method.customer = self.customer
        self.payment_method.save()
        self.payment_method.refresh_from_db()
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment, 
            self.payment_method, 
            100000)
        self.assertFalse(data)
        self.assertEqual(error, 'Akun GoPay Anda belum terhubung/tidak terdaftar')

        self.gopay_account = GopayAccountLinkStatusFactory(account=self.account, status='ENABLED')
        self.gopay_account.save()
        mock_get_gopay_client().gopay_tokenization_init_transaction.return_value = {
            "status_code": "201",
            "status_message": "GoPay transaction is created. Action(s) required",
            "transaction_id": "00000269-7836-49e5-bc65-e592afafec14",
            "order_id": "order-1234",
            "gross_amount": "100000.00",
            "currency": "IDR",
            "payment_type": "gopay",
            "transaction_time": "2016-06-28 09:42:20",
            "transaction_status": "pending",
            "fraud_status": "accept",
            "actions": [
              {
                "name": "verification-link-url",
                "method": "GET",
                "url": "http://api.midtrans.com/v2/gopay/redirect/gppr_6123269-1425-21e3-bc44-e592afafec14/charge"
              },
              {
                "name": "verification-link-app",
                "method": "GET",
                "url": "http://api.midtrans.com/v2/gopay/redirect/gppd_6123269-1425-21e3-bc44-e592afafec14/charge"
              }
            ]
        }
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment, 
            self.payment_method, 
            100000)
        self.assertFalse(error)
        self.assertTrue(data['gopay']['transaction_status'], 'pending')
        self.assertTrue(PaybackTransaction.objects.filter(transaction_id='order-1234').exists())
        self.assertTrue(GopayRepaymentTransaction.objects.filter(transaction_id='order-1234').exists())

        mock_get_gopay_client().gopay_tokenization_init_transaction.return_value = {
            "status_code": "201",
            "status_message": "GoPay transaction is created. Action(s) required",
            "transaction_id": "00000269-7836-49e5-bc65-e592afafec14",
            "order_id": "order-12345",
            "gross_amount": "100000.00",
            "currency": "IDR",
            "payment_type": "gopay",
            "transaction_time": "2016-06-28 09:42:20",
            "transaction_status": "pending",
            "fraud_status": "accept",
            "actions": []
        }
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment, 
            self.payment_method, 
            100000)
        self.assertFalse(data)
        self.assertEqual(error, 'Verification link not provided')

        mock_get_gopay_client().gopay_tokenization_init_transaction.return_value = {
            "status_code": "202",
            "status_message": "GoPay transaction is denied",
            "transaction_id": "a8a91ece-24f9-427d-a588-b9a2428acda0",
            "order_id": "order-123456",
            "gross_amount": "100000.00",
            "currency": "IDR",
            "payment_type": "gopay",
            "transaction_time": "2016-06-28 09:42:20",
            "transaction_status": "deny",
            "fraud_status": "accept",
        }
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment, 
            self.payment_method, 
            100000)
        self.assertFalse(data)
        self.assertEqual(error, 'GoPay transaction is denied')
        self.assertFalse(PaybackTransaction.objects.filter(transaction_id='order-123456').exists())
        self.assertTrue(GopayRepaymentTransaction.objects.filter(transaction_id='order-123456').exists())

        mock_get_gopay_client().gopay_tokenization_init_transaction.return_value = {
            "status_code": "200",
            "status_message": "Success, GoPay transaction is successful",
            "transaction_id": "00000269-7836-49e5-bc65-e592afafec14",
            "order_id": "order-1234567",
            "gross_amount": "100000.00",
            "currency": "IDR",
            "payment_type": "gopay",
            "transaction_time": "2016-06-28 09:42:20",
            "transaction_status": "settlement",
            "fraud_status": "accept",
        }
        data, error = gopay_services.gopay_tokenization_init_account_payment_transaction(
            account_payment, 
            self.payment_method, 
            100000)
        self.assertFalse(error)
        self.assertEqual(data['gopay']['status_message'], 'Success, GoPay transaction is successful')
        self.assertTrue(PaybackTransaction.objects.filter(transaction_id='order-1234567').exists())
        self.assertTrue(GopayRepaymentTransaction.objects.filter(transaction_id='order-1234567').exists())
