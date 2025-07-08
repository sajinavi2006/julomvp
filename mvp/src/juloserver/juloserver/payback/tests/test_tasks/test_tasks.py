from mock import patch
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.account.tests.factories import AccountFactory

from juloserver.payback.tests.factories import GopayAccountLinkStatusFactory
from juloserver.payback.tasks.gopay_tasks import update_gopay_balance_subtask
from juloserver.payback.models import GopayCustomerBalance


class TestUpdateGopayBalance(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

    @patch('juloserver.payback.tasks.gopay_tasks.get_gopay_client')
    def test_update_gopay_balance_status_enabled_success(self, mock_gopay_client):
        pay_account_id = "00000269-7836-49e5-bc65-e592afafec14"
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            pay_account_id=pay_account_id,
            account=self.account,
        )
        mock_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": pay_account_id,
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {"value": "1000000.00", "currency": "IDR"},
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==",
                    }
                ]
            },
        }
        update_gopay_balance_subtask(self.gopay_account_link_status.id)
        mock_gopay_client().get_pay_account.assert_called_once_with(pay_account_id)
        gopay_wallet = GopayCustomerBalance.objects.filter(
            gopay_account=self.gopay_account_link_status, account=self.account
        ).last()
        self.assertEqual(gopay_wallet.balance, 1000000)

    @patch('juloserver.payback.tasks.gopay_tasks.logger')
    def test_update_gopay_balance_account_not_found(self, mock_logger):
        pay_account_id = "00000269-7836-49e5-bc65-e592afafec14"
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            id=1,
            pay_account_id=pay_account_id,
            account=self.account,
        )
        update_gopay_balance_subtask(2)
        mock_logger.error.assert_called_once_with(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'gopay_account_id is not found',
                'gopay_account_id': 2,
            }
        )

    @patch('juloserver.payback.tasks.gopay_tasks.logger')
    @patch('juloserver.payback.tasks.gopay_tasks.get_gopay_client')
    def test_update_gopay_balance_status_not_enabled_failed(self, mock_gopay_client, mock_logger):
        pay_account_id = "00000269-7836-49e5-bc65-e592afafec14"
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            pay_account_id=pay_account_id,
            account=self.account,
        )
        mock_gopay_client().get_pay_account.return_value = {
            "status_code": "201",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "PENDING",
        }
        update_gopay_balance_subtask(self.gopay_account_link_status.id)
        mock_gopay_client().get_pay_account.assert_called_once_with(pay_account_id)
        mock_logger.error.assert_called_once_with(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'account_status is not enabled',
                'data': mock_gopay_client().get_pay_account.return_value,
            }
        )
        gopay_wallet = GopayCustomerBalance.objects.filter(
            gopay_account=self.gopay_account_link_status, account=self.account
        ).last()
        self.assertIsNone(gopay_wallet)

    @patch('juloserver.payback.tasks.gopay_tasks.logger')
    @patch('juloserver.payback.tasks.gopay_tasks.get_gopay_client')
    def test_update_gopay_balance_status_enabled_wallet_not_found(
        self, mock_gopay_client, mock_logger
    ):
        pay_account_id = "00000269-7836-49e5-bc65-e592afafec14"
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            pay_account_id=pay_account_id,
            account=self.account,
        )
        mock_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": pay_account_id,
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {"value": "350000.00", "currency": "IDR"},
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ==",
                    }
                ]
            },
        }
        update_gopay_balance_subtask(self.gopay_account_link_status.id)
        mock_gopay_client().get_pay_account.assert_called_once_with(pay_account_id)
        mock_logger.error.assert_called_once_with(
            {
                'action': 'juloserver.payback.tasks.gopay_tasks.update_gopay_balance_subtask',
                'error': 'Gopay wallet not provided',
                'data': mock_gopay_client().get_pay_account.return_value,
            }
        )
        gopay_wallet = GopayCustomerBalance.objects.filter(
            gopay_account=self.gopay_account_link_status, account=self.account
        ).last()
        self.assertIsNone(gopay_wallet)
