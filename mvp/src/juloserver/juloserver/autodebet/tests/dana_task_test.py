from mock import ANY, patch, MagicMock
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    AccountingCutOffDateFactory,
    PaymentFactory,
    LoanFactory,
    DeviceFactory,
)
from juloserver.autodebet.tests.factories import AutodebetDanaTransactionFactory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountTransactionFactory,
)
from juloserver.autodebet.constants import (
    FeatureNameConst,
    AutodebetDANAPaymentResultStatusConst,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.dana_linking.tests.factories import DanaWalletAccountFactory
from juloserver.autodebet.clients import AutodebetDanaClient
from juloserver.autodebet.tasks import reinquiry_payment_autodebet_dana


class TestAutodebetDanaReinquiry(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY,
            parameters={'DANA': {'minutes': 120}},
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

        self.dana_wallet_account = DanaWalletAccountFactory(
            account=self.account,
        )
        self.autodebet_transaction = AutodebetDanaTransactionFactory(
            account_payment=self.account_payment,
            dana_wallet_account=self.dana_wallet_account,
        )
        self.return_mock_inquiry_status_success = {
            "amount": {"currency": "IDR", "value": "100000.00"},
            "serviceCode": "55",
            "transactionStatusDesc": "SUCCESS",
            "originalPartnerReferenceNo": "2024052010440001",
            "paidTime": "2024-05-21T17:42:33+07:00",
            "title": "autodebet",
            "responseCode": "2005500",
            "transAmount": {"currency": "IDR", "value": "100000.00"},
            "feeAmount": {"currency": "IDR", "value": "0.00"},
            "originalReferenceNo": "20240521111212800100166744501948943",
            "latestTransactionStatus": "00",
            "additionalInfo": {
                "seller": {},
                "timeDetail": {
                    "expiryTime": "2024-05-21T20:42:32+07:00",
                    "createdTime": "2024-05-21T17:42:32+07:00",
                    "paidTimes": ["2024-05-21T17:42:33+07:00"],
                },
                "paymentViews": [
                    {
                        "payOptionInfos": [
                            {
                                "transAmount": {"currency": "IDR", "value": "100000.00"},
                                "payAmount": {"currency": "IDR", "value": "100000.00"},
                                "payMethod": "BALANCE",
                                "chargeAmount": {"currency": "IDR", "value": "0.00"},
                                "payOptionBillExtendInfo": "{}",
                            }
                        ],
                        "cashierRequestId": "20240521111212800100166744501948943",
                        "paidTime": "2024-05-21T17:42:33+07:00",
                        "extendInfo": "{\"topupAndPay\":\"false\",\"paymentStatus\":\"SUCCESS\"}",
                    }
                ],
                "amountDetail": {
                    "confirmAmount": {"currency": "IDR", "value": "0.00"},
                    "orderAmount": {"currency": "IDR", "value": "100000.00"},
                    "payAmount": {"currency": "IDR", "value": "100000.00"},
                    "chargeAmount": {"currency": "IDR", "value": "0.00"},
                    "voidAmount": {"currency": "IDR", "value": "0.00"},
                    "refundAmount": {"currency": "IDR", "value": "0.00"},
                    "chargebackAmount": {"currency": "IDR", "value": "0.00"},
                },
                "statusDetail": {"frozen": "false", "acquirementStatus": "SUCCESS"},
                "buyer": {"userId": "216610000002255667746"},
            },
            "responseMessage": "Successful",
        }, None

        self.return_mock_inquiry_status_failed = {
            "amount": {"currency": "IDR", "value": "100000.00"},
            "serviceCode": "55",
            "transactionStatusDesc": "CANCELLED",
            "originalPartnerReferenceNo": "2024052010440001",
            "paidTime": "2024-05-21T17:42:33+07:00",
            "title": "autodebet",
            "responseCode": "2005500",
            "transAmount": {"currency": "IDR", "value": "100000.00"},
            "feeAmount": {"currency": "IDR", "value": "0.00"},
            "originalReferenceNo": "20240521111212800100166744501948943",
            "latestTransactionStatus": "05",
            "additionalInfo": {
                "seller": {},
                "timeDetail": {
                    "expiryTime": "2024-05-21T20:42:32+07:00",
                    "createdTime": "2024-05-21T17:42:32+07:00",
                    "paidTimes": ["2024-05-21T17:42:33+07:00"],
                },
                "paymentViews": [
                    {
                        "payOptionInfos": [
                            {
                                "transAmount": {"currency": "IDR", "value": "100000.00"},
                                "payAmount": {"currency": "IDR", "value": "100000.00"},
                                "payMethod": "BALANCE",
                                "chargeAmount": {"currency": "IDR", "value": "0.00"},
                                "payOptionBillExtendInfo": "{}",
                            }
                        ],
                        "cashierRequestId": "20240521111212800100166744501948943",
                        "paidTime": "2024-05-21T17:42:33+07:00",
                        "extendInfo": "{\"topupAndPay\":\"false\",\"paymentStatus\":\"SUCCESS\"}",
                    }
                ],
                "amountDetail": {
                    "confirmAmount": {"currency": "IDR", "value": "0.00"},
                    "orderAmount": {"currency": "IDR", "value": "100000.00"},
                    "payAmount": {"currency": "IDR", "value": "100000.00"},
                    "chargeAmount": {"currency": "IDR", "value": "0.00"},
                    "voidAmount": {"currency": "IDR", "value": "0.00"},
                    "refundAmount": {"currency": "IDR", "value": "0.00"},
                    "chargebackAmount": {"currency": "IDR", "value": "0.00"},
                },
                "statusDetail": {"frozen": "false", "acquirementStatus": "SUCCESS"},
                "buyer": {"userId": "216610000002255667746"},
            },
            "responseMessage": "Successful",
        }, None

    @patch('juloserver.autodebet.clients.AutodebetDanaClient.inquiry_autodebet_status')
    @patch('juloserver.autodebet.tasks.j1_refinancing_activation')
    @patch('juloserver.autodebet.tasks.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.tasks.process_repayment_trx')
    @patch('juloserver.autodebet.tasks.update_moengage_for_payment_received_task.delay')
    def test_reinquiry_payment_autodebet_dana_failed(
        self,
        mock_update_moengage_for_payment_received_task,
        mock_process_repayment_trx,
        mock_process_j1_waiver_before_payment,
        mock_j1_refinancing_activation,
        mock_dana_request: MagicMock,
    ):
        mock_dana_request.return_value = self.return_mock_inquiry_status_failed
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        reinquiry_payment_autodebet_dana()

        self.autodebet_transaction.refresh_from_db()
        assert self.autodebet_transaction.status == AutodebetDANAPaymentResultStatusConst.FAILED

    @patch('juloserver.autodebet.clients.AutodebetDanaClient.inquiry_autodebet_status')
    @patch('juloserver.autodebet.tasks.j1_refinancing_activation')
    @patch('juloserver.autodebet.tasks.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.tasks.process_repayment_trx')
    @patch('juloserver.autodebet.tasks.update_moengage_for_payment_received_task.delay')
    def test_reinquiry_payment_autodebet_dana_success(
        self,
        mock_update_moengage_for_payment_received_task,
        mock_process_repayment_trx,
        mock_process_j1_waiver_before_payment,
        mock_j1_refinancing_activation,
        mock_dana_request: MagicMock,
    ):
        mock_dana_request.return_value = self.return_mock_inquiry_status_success
        mock_process_repayment_trx.return_value = AccountTransactionFactory()
        reinquiry_payment_autodebet_dana()

        self.autodebet_transaction.refresh_from_db()
        assert self.autodebet_transaction.status == AutodebetDANAPaymentResultStatusConst.SUCCESS
