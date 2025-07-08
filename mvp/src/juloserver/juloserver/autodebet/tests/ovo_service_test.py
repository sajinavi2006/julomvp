import factory

from datetime import date
from django.db.models import signals
from django.test.testcases import TestCase
from mock import patch, Mock

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    FeatureNameConst,
    AutodebetOVOPaymentResultStatusConst,
)
from juloserver.autodebet.tasks import collect_ovo_autodebet_account_collection_task
from juloserver.julo.tests.factories import CustomerFactory, FeatureSettingFactory
from juloserver.ovo.models import OvoWalletAccount
from juloserver.ovo.constants import OvoWalletAccountStatusConst, AUTODEBET_MAXIMUM_AMOUNT_PAYMENT
from juloserver.ovo.tests.factories import OvoWalletAccountFactory
from juloserver.autodebet.services.task_services import create_debit_payment_process_ovo
from juloserver.autodebet.models import AutodebetOvoTransaction
from juloserver.ovo.constants import AUTODEBET_MINIMUM_AMOUNT_PAYMENT


class TestAutodebetOvoPayment(TestCase):
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def setUp(self):
        # Normal case
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_OVO,
            parameters={
                "disable": {
                    "disable_start_date_time": "12-12-2023 09:00",
                    "disable_end_date_time": "12-12-2023 11:00",
                },
            },
            is_active=True,
            category="repayment",
            description="Autodebet OVO",
        )

        self.customer = CustomerFactory(customer_xid='1122334455')
        self.account = AccountFactory(customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False,
            vendor=AutodebetVendorConst.OVO,
        )
        self.ovo_wallet_account = OvoWalletAccountFactory(
            status=OvoWalletAccountStatusConst.ENABLED,
            account_id=self.account.id,
        )
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=date.today(),
        )
        self.response_doku_payment = {
            "responseCode": "2005400",
            "responseMessage": "Successful",
            "referenceNo": "ImHk0SRAeTtalOO0do6dq9OfQHVN5hVZ",
        }

        self.response_doku_payment_insuff_fund = {
            "responseCode": "4035414",
            "responseMessage": "Insufficient Funds",
            "referenceNo": "",
        }

        # Ovo wallet is disabled
        self.account2 = AccountFactory(customer=self.customer)
        self.ovo_wallet_account2 = OvoWalletAccountFactory(
            status=OvoWalletAccountStatusConst.DISABLED,
            account_id=self.account2.id,
        )
        self.account_payment2 = AccountPaymentFactory(
            account=self.account2,
            due_date=date.today(),
        )

        # Balance not found
        self.account3 = AccountFactory(customer=self.customer)
        self.ovo_wallet_account3 = OvoWalletAccountFactory(
            status=OvoWalletAccountStatusConst.ENABLED,
            account_id=self.account3.id,
        )
        self.account_payment3 = AccountPaymentFactory(
            account=self.account3,
            due_date=date.today(),
        )

        # Reach limit
        self.account4 = AccountFactory(customer=self.customer)
        self.ovo_wallet_account4 = OvoWalletAccountFactory(
            status=OvoWalletAccountStatusConst.ENABLED,
            account_id=self.account4.id,
            balance=10000000,
        )
        self.account_payment3 = AccountPaymentFactory(
            account=self.account4,
            due_date=date.today(),
        )
        self.account_payment4 = AccountPaymentFactory(
            account=self.account4,
            due_date=date.today(),
            due_amount=5000000,
        )
        self.response_doku_payment_reach_limit = {
            "responseCode": "4035402",
            "responseMessage": "Exceeds Transaction Amount Limit",
        }

    @patch('juloserver.autodebet.services.task_services.get_ovo_wallet_balance')
    @patch('juloserver.autodebet.services.task_services.get_doku_snap_ovo_client')
    def test_create_debit_payment_process_ovo_success(
        self, mock_get_client, mock_get_ovo_wallet_balance
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.payment.return_value = (self.response_doku_payment, None)
        mock_client.generate_reference_no.return_value = '123456'
        mock_get_ovo_wallet_balance.return_value = 1000000000, None

        account_payment_ids = [self.account_payment.id]
        create_debit_payment_process_ovo(account_payment_ids, self.account)

        mock_get_ovo_wallet_balance.assert_called_once()
        self.assertTrue(
            AutodebetOvoTransaction.objects.filter(
                ovo_wallet_account=self.ovo_wallet_account,
                account_payment_id=self.account_payment.id,
                amount=self.account_payment.due_amount,
            ).exists()
        )

    @patch('juloserver.autodebet.services.task_services.get_ovo_wallet_balance')
    @patch('juloserver.autodebet.services.task_services.get_doku_snap_ovo_client')
    def test_create_debit_payment_process_ovo_reach_limit(
        self, mock_get_client, mock_get_ovo_wallet_balance
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.payment.return_value = (
            self.response_doku_payment_reach_limit,
            'Exceeds Transaction Amount Limit',
        )
        mock_client.generate_reference_no.return_value = '123456'
        mock_get_ovo_wallet_balance.return_value = 1000000000, None

        account_payment_ids = [self.account_payment4.id]
        create_debit_payment_process_ovo(account_payment_ids, self.account4)

        mock_get_ovo_wallet_balance.assert_called_once()
        self.assertTrue(
            AutodebetOvoTransaction.objects.filter(
                ovo_wallet_account=self.ovo_wallet_account4,
                account_payment_id=self.account_payment4.id,
                amount=self.account_payment4.due_amount,
            ).exists()
        )

        self.assertTrue(
            OvoWalletAccount.objects.filter(
                id=self.ovo_wallet_account4.id, max_limit_payment=AUTODEBET_MAXIMUM_AMOUNT_PAYMENT
            ).exists()
        )

    def test_create_debit_payment_process_ovo_not_found(self):
        account_payment_ids = [self.account_payment2.id]
        create_debit_payment_process_ovo(account_payment_ids, self.account2)

        self.assertFalse(
            AutodebetOvoTransaction.objects.filter(
                ovo_wallet_account=self.ovo_wallet_account2,
                account_payment_id=self.account_payment2.id,
                amount=self.account_payment2.due_amount,
            ).exists()
        )

    @patch('juloserver.autodebet.services.task_services.get_ovo_wallet_balance')
    def test_create_debit_payment_process_ovo_balance_error(self, mock_get_ovo_wallet_balance):
        mock_get_ovo_wallet_balance.return_value = None, "Invalid Customer Token"

        account_payment_ids = [self.account_payment3.id]
        create_debit_payment_process_ovo(account_payment_ids, self.account3)

        self.assertFalse(
            AutodebetOvoTransaction.objects.filter(
                ovo_wallet_account=self.ovo_wallet_account3,
                account_payment_id=self.account_payment3.id,
                amount=self.account_payment3.due_amount,
            ).exists()
        )

    @patch('juloserver.autodebet.services.task_services.get_ovo_wallet_balance')
    @patch('juloserver.autodebet.services.task_services.get_doku_snap_ovo_client')
    def test_create_debit_payment_process_ovo_insufficient_fund(
        self, mock_get_client, mock_get_ovo_wallet_balance
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.payment.return_value = (self.response_doku_payment_insuff_fund, None)
        mock_client.generate_reference_no.return_value = '123456'
        mock_get_ovo_wallet_balance.return_value = AUTODEBET_MINIMUM_AMOUNT_PAYMENT - 1, None

        account_payment_ids = [self.account_payment3.id]
        create_debit_payment_process_ovo(account_payment_ids, self.account3)

        self.assertTrue(
            AutodebetOvoTransaction.objects.filter(
                ovo_wallet_account=self.ovo_wallet_account3,
                account_payment_id=self.account_payment3.id,
                amount=self.account_payment3.due_amount,
                status=AutodebetOVOPaymentResultStatusConst.PENDING,
            ).exists()
        )

    @patch('juloserver.autodebet.tasks.collect_ovo_autodebet_account_collection_subtask')
    def test_collect_ovo_autodebet_account_collection_task(
        self, mock_collect_ovo_autodebet_account_collection_subtask
    ):
        collect_ovo_autodebet_account_collection_task()

        mock_collect_ovo_autodebet_account_collection_subtask.delay.assert_called_once()
