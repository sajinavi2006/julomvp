from mock import patch
from django.test.testcases import TestCase
from juloserver.julo.services2.cashback import CashbackRedemptionService
from juloserver.julo.tests.factories import (
    CashbackTransferTransactionFactory, CustomerWalletHistoryFactory, CustomerFactory)


class TestCashbackRedemptionService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.cashback_service = CashbackRedemptionService()

    @patch('juloserver.julo.services2.cashback.pn_client')
    def test_action_cashback_transfer_finish(self, mock_pn_client):
        cash_back_transaction = CashbackTransferTransactionFactory(customer_id=self.customer.id)
        customer_wallet_history = CustomerWalletHistoryFactory(
            cashback_transfer_transaction=cash_back_transaction)
        result = self.cashback_service.action_cashback_transfer_finish(cash_back_transaction, True)
        mock_pn_client.inform_transfer_cashback_finish.assert_called()
        self.assertIsNotNone(cash_back_transaction.fund_transfer_ts)
