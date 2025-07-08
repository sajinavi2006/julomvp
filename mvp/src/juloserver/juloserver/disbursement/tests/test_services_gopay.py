from builtins import str

import pytest
from mock import patch, MagicMock
from django.test.testcases import TestCase

from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.julo.tests.factories import BankFactory
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.julo.tests.factories import CustomerWalletHistoryFactory
from juloserver.julo.tests.factories import ApplicationFactory
from juloserver.julo.tests.factories import (
    CashbackTransferTransactionFactory,
    CashbackTransferTransaction)

from juloserver.disbursement.exceptions import (
    GopayServiceError, GopayClientException, GopayInsufficientError)
from juloserver.disbursement.services.gopay import GopayService

class TestGopayService(TestCase):
    def setUp(self):
        self.bank = BankFactory()
        self.customer = CustomerFactory()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.application = ApplicationFactory()
        self.cashback_transfer_transaction = CashbackTransferTransactionFactory()

    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_init(self, mock_client):
        result = GopayService()
        assert mock_client.called


    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_check_balance_case_1(self, mock_client):
        mock_response_get_balance = {
            'balance':100
        }
        mock_client.return_value.get_balance.return_value = mock_response_get_balance

        result = GopayService()
        result = result.check_balance(100)

        assert mock_client.called
        assert result == True


    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_check_balance_case_2(self, mock_client):
        mock_client.return_value.get_balance.side_effect = GopayServiceError('test')

        result = GopayService()
        result = result.check_balance(100)

        assert mock_client.called
        assert result == ('test',False)


    @patch('juloserver.disbursement.services.gopay.notify_failure')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_check_balance_case_3(self, mock_client, mock_slack_notif):
        mock_response_get_balance = {
            'balance':99
        }
        mock_client.return_value.get_balance.return_value = mock_response_get_balance

        with self.assertRaises(GopayServiceError) as context:
            result = GopayService()
            result = result.check_balance(100)

        assert mock_client.called
        assert mock_slack_notif.called
        self.assertTrue('Tidak dapat melakukan pencairan, coba beberapa saat lagi' in str(context.exception))


    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_get_balance_case_1(self, mock_client):
        mock_response_get_balance = {
            'balance':100
        }
        mock_client.return_value.get_balance.return_value = mock_response_get_balance

        result = GopayService()
        result = result.get_balance()

        assert mock_client.called
        assert result == mock_response_get_balance['balance']


    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_create_payout_case_1(self, mock_client):
        data = [{'beneficiary_email': 'test@gmail.com', 'notes': 'test', 'beneficiary_name': 'test', 'amount': '100', 'beneficiary_bank': 'gopay', 'beneficiary_account': 'test123'}]
        mock_client.return_value.create_payouts.return_value = data

        result = GopayService()
        result = result.create_payout('test','test123','test@gmail.com',100,'test')

        assert mock_client.called
        assert result == data
        # mock_client.return_value.create_payout.assert_called_with(data)


    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_create_payout_case_2(self, mock_client):
        mock_client.return_value.create_payouts.side_effect = Exception('test')

        with self.assertRaises(GopayServiceError) as context:
            result = GopayService()
            result = result.create_payout('test','test123','test@gmail.com',100,'test')

        assert mock_client.called
        self.assertTrue('Tidak dapat melakukan Pencairan,coba beberapa saat lagi' in str(context.exception))

    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_1(self, mock_client, mock_check_balance, mock_create_payout):
        mock_check_balance.return_value = True
        mock_response_payout = {
            'payouts':[{
                'reference_no':'test123',
                'status':'success'
            }]
        }
        mock_create_payout.return_value = mock_response_payout

        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.save()

        result = GopayService()
        result = result.process_cashback_to_gopay(self.customer,111,'08123456789')
        assert mock_client.called
        assert result == mock_response_payout

    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_1(
        self, mock_client, mock_check_balance, mock_create_payout):
        mock_check_balance.return_value = True
        mock_response_payout = {
            'payouts':[{
                'reference_no':'test123',
                'status':'success'
            }]
        }
        mock_create_payout.return_value = mock_response_payout

        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.save()

        result = GopayService()
        result = result.process_cashback_to_gopay(self.customer,111,'08123456789')
        assert mock_client.called
        assert result == mock_response_payout

    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_2(self, mock_client, mock_check_balance, mock_create_payout):
        mock_check_balance.return_value = True
        mock_response_payout = {
            'payouts':[{
                'reference_no':'test123',
                'status':'success'
            }]
        }
        mock_create_payout.return_value = mock_response_payout

        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.save()

        mock_client.return_value.approve_payouts.side_effect = GopayClientException('test')
        with self.assertRaises(Exception) as context:
            result = GopayService()
            result = result.process_cashback_to_gopay(self.customer,111,'08123456789')

        assert mock_client.called
        self.assertTrue('Tidak dapat melakukan Pencairan,coba beberapa saat lagi' in str(context.exception))



    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_3(self, mock_client, mock_check_balance):
        mock_check_balance.return_value = True

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.application_status_id = 190
        self.application.save()
        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()
        with self.assertRaises(GopayInsufficientError) as context:
            result = GopayService()
            result = result.process_cashback_to_gopay(self.customer, 0, '08123456789')
        assert mock_client.called
        self.assertTrue('Jumlah cashback anda Harus melebihi minimum Biaya Admin' in str(context.exception))


    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_4(self, mock_client, mock_check_balance):
        mock_check_balance.return_value = True

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.application_status_id = 190
        self.application.save()
        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()
        with self.assertRaises(GopayInsufficientError) as context:
            result = GopayService()
            result = result.process_cashback_to_gopay(self.customer, 151, '08123456789')
        assert mock_client.called
        self.assertTrue('Jumlah cashback anda tidak mencukupi untuk melakukan pencairan' in str(context.exception))

    @patch('juloserver.disbursement.services.gopay.GopayService.create_payout')
    @patch('juloserver.julo_starter.services.services.determine_application_for_credit_info')
    @patch('juloserver.disbursement.services.gopay.GopayService.check_balance')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_cashback_to_gopay_case_5(self, mock_client, mock_check_balance,
                                                           mock_get_last_application,
                                                           mock_create_payout):
        application = ApplicationFactory()
        mock_get_last_application.return_value = application
        mock_check_balance.return_value = True
        mock_response_payout = {
            'payouts': [{
                'reference_no': 'test123',
                'status': 'completed'
            }]
        }
        mock_create_payout.return_value = mock_response_payout

        self.bank.bank_code = 'gopay'
        self.bank.bank_name = 'GO-PAY'
        self.bank.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 150
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=150)
        self.customer_wallet_history.save()

        self.application.customer = self.customer
        self.application.save()

        result = GopayService()
        result = result.process_cashback_to_gopay(self.customer, 111, '08123456789')
        assert mock_client.called
        assert result == mock_response_payout
        cashback_transfer = CashbackTransferTransaction.objects.filter(
            application_id=application.id).last()
        self.assertIsNotNone(cashback_transfer)
        self.assertIsNotNone(cashback_transfer.fund_transfer_ts)

    def test_GopayService_process_cashback_to_gopay_case_6(self):
        with self.assertRaises(GopayServiceError) as context:
            result = GopayService()
            result = result.process_cashback_to_gopay(self.customer, 151, '08123456789')
        self.assertTrue("Tidak ada pengajuan untuk customer=%s" % self.customer.id)

    @patch('juloserver.disbursement.services.gopay.CashbackRedemptionService')
    @patch('juloserver.disbursement.services.gopay.get_gopay_client')
    def test_GopayService_process_refund_cashback_gopay_case_1(self, mock_client, mock_cashback_redemption_service):
        callback_data = {
            'error_code':'test123',
            'error_message':'test'
        }
        self.cashback_transfer_transaction.customer= self.customer
        self.cashback_transfer_transaction.save()
        result = GopayService()
        result = result.process_refund_cashback_gopay('failed',self.cashback_transfer_transaction,callback_data)

        mock_cashback_redemption_service.return_value.process_transfer_addition_wallet_customer.assert_called_with(self.customer,self.cashback_transfer_transaction,reason='refunded_transfer_gopay')
