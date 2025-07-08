from __future__ import print_function

from builtins import str

import pytest
from django.test.testcases import override_settings
from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.julo.exceptions import (
    DuplicateCashbackTransaction,
    JuloException,
    SmsNotSent, BlockedDeductionCashback,
)
from juloserver.julo.services2.cashback import ERROR_MESSAGE_TEMPLATE_5
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CashbackTransferTransactionFactory,
    CustomerFactory,
    CustomerWalletHistoryFactory,
    LoanFactory,
    MobileOperatorFactory,
    PaymentFactory,
    ProductLineFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    FeatureSettingFactory,
)


class TestCashbackGetBalanceAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_wallet_history = CustomerWalletHistoryFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCashbackGetBalanceAPIv2_success(self):
        response = self.client.get('/api/v2/cashback/balance')
        assert response.status_code == 200
        print(response.json())


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCashbackTransactionAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_wallet_history = CustomerWalletHistoryFactory(customer=self.customer)
        self.customer_wallet_history1 = CustomerWalletHistoryFactory(customer=self.customer)
        self.sepulsa_transaction = SepulsaTransactionFactory()
        self.sepulsa_product = SepulsaProductFactory()
        self.mobile_operator = MobileOperatorFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.cashback_transfer_transaction = CashbackTransferTransactionFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCashbackTransactionAPIv2_sepulsa_purchase_case_1(self):
        self.sepulsa_product.operator = self.mobile_operator
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'sepulsa_purchase'
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_sepulsa_purchase_case_2(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'sepulsa_purchase'
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_used_on_payment(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'used_on_payment'
        self.customer_wallet_history.wallet_balance_available_old = 1
        self.customer_wallet_history.payment = self.payment
        self.customer_wallet_history.save()

        self.customer_wallet_history1.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history1.change_reason = 'used_on_payment'
        self.customer_wallet_history1.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_used_transfer_status_pending(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'PENDING'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'used_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_used_transfer_status_failed(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'FAILED'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'used_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_used_transfer_status_success(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'used_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_gopay_transfer_status_pending(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'processed'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'gopay_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_gopay_transfer_status_failed(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'failed'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'gopay_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_gopay_transfer_status_success(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'completed'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'gopay_transfer'
        self.customer_wallet_history.cashback_transfer_transaction = (
            self.cashback_transfer_transaction
        )
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_loan_paid_off(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'completed'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'loan_paid_off'
        self.customer_wallet_history.wallet_balance_available_old = 1
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200

    def test_TestCashbackTransactionAPIv2_other_change_reason(self):
        self.sepulsa_product.type = 'electricity'
        self.sepulsa_product.save()

        self.sepulsa_transaction.product = self.sepulsa_product
        self.sepulsa_transaction.save()

        self.cashback_transfer_transaction.transfer_status = 'completed'
        self.cashback_transfer_transaction.save()

        self.customer_wallet_history.sepulsa_transaction = self.sepulsa_transaction
        self.customer_wallet_history.change_reason = 'other'
        self.customer_wallet_history.wallet_balance_available_old = 1
        self.customer_wallet_history.save()

        response = self.client.get('/api/v2/cashback/transactions')
        assert response.status_code == 200


class TestSepulsaProductListAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.sepulsa_product = SepulsaProductFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestSepulsaProductListAPIv2_success(self):
        data = {'type': 'test_type', 'category': 'test_category', 'mobile_operator_id': 123}
        self.sepulsa_product.type = data['type']
        self.sepulsa_product.category = data['category']
        self.sepulsa_product.operator_id = data['mobile_operator_id']
        self.sepulsa_product.is_active = True
        self.sepulsa_product.save()
        response = self.client.get('/api/v2/cashback/offered-products', data=data)

        assert response.status_code == 200


class TestCashbackFormInfoAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_operator = MobileOperatorFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCashbackFormInfoAPIv2_success(self):
        data = {'type': 'test_type', 'category': 'test_category', 'mobile_operator_id': 123}
        self.mobile_operator.is_active = True
        self.mobile_operator.initial_numbers = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        self.mobile_operator.save()

        response = self.client.get('/api/v2/cashback/form-info', data=data)

        assert response.status_code == 200


class TestCashbackSepulsaAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.sepulsa_product = SepulsaProductFactory()
        self.sepulsa_transaction = SepulsaTransactionFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback', is_active=True, parameters={"sepulsa": {"is_active": True}}
        )

    @patch('juloserver.apiv2.views.cashback_redemption_service')
    def test_TestCashbackSepulsaAPIv2_success(self, mock_get_cashback_redemption_service):
        data = {
            'phone_number': 'test_phone_number',
            'product_id': 123,
            'meter_number': 'test_meter_number',
            'account_name': 'test_account_name',
        }

        mock_get_cashback_redemption_service.trigger_partner_purchase.return_value = (
            self.sepulsa_product,
            self.sepulsa_transaction,
            100,
        )

        response = self.client.post('/api/v2/cashback/sepulsa', data=data)
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.cashback_redemption_service')
    def test_TestCashbackSepulsaAPIv2_failed(self, mock_get_cashback_redemption_service):
        data = {
            'phone_number': 'test_phone_number',
            'product_id': 123,
            'meter_number': 'test_meter_number',
            'account_name': 'test_account_name',
        }

        mock_get_cashback_redemption_service.trigger_partner_purchase.side_effect = JuloException()

        response = self.client.post('/api/v2/cashback/sepulsa', data=data)

        assert response.status_code == 400
        assert response.json()['is_success'] == False


class TestCashbackSepulsaInqueryElectricityAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.SepulsaService')
    def test_TestCashbackSepulsaInqueryElectricityAPIv2_success(self, mock_sepulsaservice):
        data = {'product_id': 123, 'meter_number': 'test_meter_number'}
        mock_response = {'response_code': '00'}
        mock_sepulsaservice.return_value.get_account_electricity_info.return_value = mock_response
        response = self.client.get(
            '/api/v2/cashback/sepulsa/inquiry/electricity-account', data=data
        )

        assert response.status_code == 200
        assert response.json()['content'] == mock_response

    @patch('juloserver.apiv2.views.SepulsaService')
    def test_TestCashbackSepulsaInqueryElectricityAPIv2_failed_validation_electricity_account(
        self,
        mock_sepulsaservice,
    ):
        data = {'product_id': 123, 'meter_number': 'test_meter_number'}
        mock_response = {'response_code': '20'}
        mock_sepulsaservice.return_value.get_account_electricity_info.return_value = mock_response
        response = self.client.get(
            '/api/v2/cashback/sepulsa/inquiry/electricity-account', data=data
        )

        response_json = response.json()
        assert response.status_code == 400
        assert response_json['message'] == ERROR_MESSAGE_TEMPLATE_5

    @patch('juloserver.apiv2.views.SepulsaService')
    def test_TestCashbackSepulsaInqueryElectricityAPIv2_failed_with_exception(
        self, mock_sepulsaservice
    ):
        data = {'product_id': 123, 'meter_number': 'test_meter_number'}
        mock_sepulsaservice.return_value.get_account_electricity_info.return_value = Exception()
        response = self.client.get(
            '/api/v2/cashback/sepulsa/inquiry/electricity-account', data=data
        )

        assert response.status_code == 400


class TestCashbackPaymentAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.cashback_redemption_service')
    def test_TestCashbackPaymentAPIv2_success(self, mock_get_cashback_redemption_service):
        mock_get_cashback_redemption_service.return_value.pay_next_loan_payment.return_value = True
        response = self.client.post('/api/v2/cashback/payment')
        assert response.status_code == 200
        assert str(response.json()['message']) == 'create transaction successfull.'

    @patch('juloserver.apiv2.views.get_cashback_redemption_service')
    def test_TestCashbackPaymentAPIv2_failed(self, mock_get_cashback_redemption_service):
        mock_get_cashback_redemption_service.return_value.pay_next_loan_payment.return_value = None
        response = self.client.post('/api/v2/cashback/payment')
        assert response.status_code == 400
        assert (
            str(response.json()['message'])
            == 'Tidak bisa melakukan pembayaran tagihan karena belum ada jadwal pembayaran'
        )

    @patch('juloserver.apiv2.views.cashback_redemption_service')
    def test_TestCashbackPaymentAPIv2_failed_with_exception(
        self, mock_get_cashback_redemption_service
    ):
        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = Exception()
        response = self.client.post('/api/v2/cashback/payment')
        assert response.status_code == 400
        assert (
            str(response.json()['message'])
            == 'Mohon maaf, terjadi kendala dalam proses pengajuan pencairan '
            'cashback, Silakan coba beberapa saat lagi.'
        )

        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = \
            DuplicateCashbackTransaction()
        response = self.client.post('/api/v2/cashback/payment')
        assert response.status_code == 400
        assert (
                str(response.json()['message'])
                == 'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.'
        )

        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = \
            BlockedDeductionCashback()
        response = self.client.post('/api/v2/cashback/payment')
        assert response.status_code == 400
        assert (
                str(response.json()['message'])
                == 'Mohon maaf, saat ini cashback tidak bisa digunakan '
                                          'karena program keringanan'
        )


class TestCashbackTransferAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 190
        self.application.save()
        self.cashback_transfer_transaction = CashbackTransferTransactionFactory()
        self.bank = BankFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                "xendit": {"is_active": True},
            },
        )

    def test_TestCashbackTransferAPIv2_amount_lt_min_transfer(self):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 43000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=43000)
        self.customer_wallet_history.save()

        response = self.client.post('/api/v2/cashback/transfer')
        assert response.status_code == 400
        assert (
            str(response.json()['message'])
            == 'Mohon maaf, saldo cashback anda tidak cukup untuk melakukan '
            'pencairan, minimal saldo Rp 44.000'
        )

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackTransferAPIv2_have_current_cashback_transfer(
        self, mock_get_last_application
    ):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 44000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=44000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'not_final_statuses'
        self.cashback_transfer_transaction.bank_code = 'not_gopay'
        self.cashback_transfer_transaction.save()

        mock_get_last_application.return_value = self.application
        response = self.client.post('/api/v2/cashback/transfer')

        assert response.status_code == 400
        assert (
            str(response.json()['message'])
            == 'Mohon maaf, Anda tidak dapat melakukan request cashback, silahkan '
            'tunggu sampai request cashback sebelumnya berhasil diproses.'
        )

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackTransferAPIv2_success_case_1(self, mock_get_last_application):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 74000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=74000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.bank.bank_code = '014'
        self.bank.save()

        mock_get_last_application.return_value = self.application
        response = self.client.post('/api/v2/cashback/transfer')

        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackTransferAPIv2_success_case_2(self, mock_get_last_application):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        mock_get_last_application.return_value = self.application
        response = self.client.post('/api/v2/cashback/transfer')

        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_cashback_redemption_service')
    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackTransferAPIv2_cashback_transfer_failed(
        self, mock_get_last_application, mock_get_cashback_redemption_service
    ):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        mock_get_last_application.return_value = self.application
        mock_get_cashback_redemption_service.return_value.transfer_cashback.side_effect = (
            Exception()
        )
        response = self.client.post('/api/v2/cashback/transfer')

        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackTransferAPIv2_CashbackTransferTransaction_creation_failed(
        self, mock_get_last_application
    ):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 44000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=44000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        mock_get_last_application.return_value = self.application
        response = self.client.post('/api/v2/cashback/transfer')

        assert response.status_code == 400
        assert (
            str(response.json()['message'])
            == 'Mohon maaf, terjadi kendala dalam proses pengajuan pencairan '
            'cashback, Silakan coba beberapa saat lagi.'
        )

    def test_TestCashbackTransferAPIv2_list(self):
        self.cashback_transfer_transaction.customer = self.customer
        self.cashback_transfer_transaction.save()

        response = self.client.get('/api/v2/cashback/transfer')
        assert response.status_code == 200


class TestCashbackLastBankInfoAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory()
        self.bank = BankFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackLastBankInfoAPIv2_application_not_found(self, mock_get_last_application):
        mock_get_last_application.return_value = None

        response = self.client.get('/api/v2/cashback/last_bank_info')
        assert response.status_code == 400
        assert response.json()['message'] == 'customer has no active loan'

    @patch('juloserver.apiv2.views.get_last_application')
    def test_TestCashbackLastBankInfoAPIv2_success(self, mock_get_last_application):
        self.application.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.bank.bank_code = '014'
        self.bank.save()

        mock_get_last_application.return_value = self.application

        response = self.client.get('/api/v2/cashback/last_bank_info')
        assert response.status_code == 200


class TestCashbackBarAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()
        self.product_line = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCashbackBarAPIv2_application_not_found(self):
        data = {'application_id': 123123123}
        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Aplikasi tidak ditemukan'

    def test_TestCashbackBarAPIv2_product_line_not_found(self):
        data = {'application_id': self.application.id}
        self.application.product_line = None
        self.application.save()

        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Aplikasi tidak ditemukan'

    def test_TestCashbackBarAPIv2_product_line_not_mtl(self):
        data = {'application_id': self.application.id}
        self.application.product_line = self.product_line
        self.application.save()

        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Aplikasi tidak ditemukan'

    def test_TestCashbackBarAPIv2_application_loan_not_found(self):
        data = {'application_id': self.application.id}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.save()

        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Pinjaman tidak ditemukan'

    def test_TestCashbackBarAPIv2_loan_status_lt_current(self):
        data = {'application_id': self.application.id}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.loan.loan_status_id = 100
        self.loan.application = self.application
        self.loan.save()

        self.application.product_line = self.product_line
        self.application.loan = self.loan
        self.application.save()

        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 400

    def test_TestCashbackBarAPIv2_success(self):
        data = {'application_id': self.application.id}
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.loan.loan_status_id = 220
        self.loan.application = self.application
        self.loan.save()

        self.application.product_line = self.product_line
        self.application.loan = self.loan
        self.application.save()

        response = self.client.get('/api/v2/cashback/bar', data=data)
        assert response.status_code == 200
