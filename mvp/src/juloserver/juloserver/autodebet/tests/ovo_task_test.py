from mock import ANY, patch, Mock
from django.test.testcases import TestCase
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    LoanFactory,
    DeviceFactory,
    PaybackTransactionFactory,
)
from juloserver.autodebet.tests.factories import AutodebetOvoTransactionFactory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountTransactionFactory,
)
from juloserver.autodebet.constants import (
    FeatureNameConst,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.ovo.tests.factories import OvoWalletAccountFactory
from juloserver.autodebet.tasks import (
    reinquiry_payment_autodebet_ovo,
    reinquiry_payment_autodebet_ovo_subtask,
)


class TestAutodebetOvoReinquiry(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY,
            parameters={'OVO': {'minutes': 120}},
            is_active=True,
        )
        self.account = AccountFactory()
        self.device = DeviceFactory(customer=self.account.customer)
        self.application = ApplicationFactory(account=self.account)

        today = timezone.localtime(timezone.now()).date()
        self.account_payment = AccountPaymentFactory(account=self.account, due_date=today)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.account_payment.refresh_from_db()

        self.loan = LoanFactory(
            account=self.account, customer=self.account.customer, initial_cashback=2000
        )
        self.loan.loan_status_id = 220
        self.loan.save()

        self.ovo_wallet_account = OvoWalletAccountFactory(
            account_id=self.account.id, status='ENABLED'
        )
        self.autodebet_transaction = AutodebetOvoTransactionFactory(
            account_payment_id=self.account_payment.id,
            ovo_wallet_account=self.ovo_wallet_account,
            original_partner_reference_no="123456789",
            original_reference_no="123456789",
            amount=100000,
        )
        self.payback_trx = PaybackTransactionFactory(
            customer=self.account.customer,
            amount=100000,
            transaction_id=self.autodebet_transaction.original_partner_reference_no,
            payback_service="ovo",
            is_processed=False,
        )
        self.autodebet_transaction.cdate = timezone.localtime(timezone.now()) - timedelta(hours=2)
        self.autodebet_transaction.save()
        self.autodebet_transaction.refresh_from_db()

        self.return_mock_inquiry_status_success = {
            "responseCode": "2005500",
            "responseMessage": "Successful",
            "originalPartnerReferenceNo": self.autodebet_transaction.original_partner_reference_no,
            "originalReferenceNo": self.autodebet_transaction.original_reference_no,
            "originalExternalId": "639719428470307511969472908117586067",
            "serviceCode": "55",
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "SUCCESS",
            "originalResponseCode": "2005400",
            "originalResponseMessage": "Successful",
            "paidTime": "2024-10-28T20:49:01+07:00",
            "transAmount": {"value": "10000.00", "currency": "IDR"},
            "additionalInfo": {"acquirer": {"id": "OVO"}},
        }

        self.return_mock_inquiry_status_failed = {
            "responseCode": "4045501",
            "responseMessage": "Transaction Not Found",
        }

    @patch('juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo_subtask.delay')
    def test_reinquiry_payment_autodebet_ovo_success(
        self, mock_reinquiry_payment_autodebet_ovo_subtask
    ):
        reinquiry_payment_autodebet_ovo()

        mock_reinquiry_payment_autodebet_ovo_subtask.assert_called_once()

    @patch('juloserver.autodebet.tasks.update_moengage_for_payment_received_task.delay')
    @patch('juloserver.autodebet.tasks.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.tasks.j1_refinancing_activation')
    @patch('juloserver.autodebet.tasks.process_repayment_trx')
    @patch('juloserver.autodebet.tasks.get_doku_snap_ovo_client')
    def test_reinquiry_payment_autodebet_ovo_subtask_success(
        self,
        mock_get_client,
        mock_process_repayment_trx,
        mock_j1_refinancing_activation,
        mock_process_j1_waiver_before_payment,
        mock_update_moengage_for_payment_received_task,
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.ovo_inquiry_payment.return_value = (
            self.return_mock_inquiry_status_success,
            None,
        )
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        reinquiry_payment_autodebet_ovo_subtask(
            self.autodebet_transaction.original_partner_reference_no
        )

        mock_j1_refinancing_activation.assert_called_once()
        mock_process_j1_waiver_before_payment.assert_called_once()

    @patch('juloserver.autodebet.tasks.update_moengage_for_payment_received_task.delay')
    @patch('juloserver.autodebet.tasks.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.tasks.j1_refinancing_activation')
    @patch('juloserver.autodebet.tasks.process_repayment_trx')
    @patch('juloserver.autodebet.tasks.get_doku_snap_ovo_client')
    def test_reinquiry_payment_autodebet_ovo_subtask_success(
        self,
        mock_get_client,
        mock_process_repayment_trx,
        mock_j1_refinancing_activation,
        mock_process_j1_waiver_before_payment,
        mock_update_moengage_for_payment_received_task,
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.ovo_inquiry_payment.return_value = (
            self.return_mock_inquiry_status_failed,
            None,
        )
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        reinquiry_payment_autodebet_ovo_subtask(
            self.autodebet_transaction.original_partner_reference_no
        )

        mock_j1_refinancing_activation.assert_not_called()
        mock_process_j1_waiver_before_payment.assert_not_called()
