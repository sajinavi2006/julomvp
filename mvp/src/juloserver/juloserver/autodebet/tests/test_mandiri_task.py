import factory
from mock import ANY, patch, Mock
from django.db.models import signals, Sum
from django.test.testcases import TestCase
from django.utils import timezone
from datetime import timedelta, date

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    LoanFactory,
    DeviceFactory,
    PaybackTransactionFactory,
    PaymentFactory,
    CustomerFactory,
)
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
    AutodebetMandiriAccountFactory,
    AutodebetMandiriTransactionFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountTransactionFactory,
)
from juloserver.autodebet.constants import (
    FeatureNameConst,
    AutodebetMandiriPaymentResultStatusConst,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.autodebet.tasks import reinquiry_payment_autodebet_mandiri
from juloserver.autodebet.services.mandiri_services import inquiry_transaction_statusv2
from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.models import AutodebetMandiriTransaction, AutodebetMandiriAccount
from juloserver.autodebet.tasks import create_debit_payment_process_mandiri_subchainv2

class TestAutodebetMandiriReinquiry(TestCase):
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY,
            parameters={'MANDIRI': {'minutes': 120}},
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

        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=today,
            paid_amount=self.account_payment.due_amount,
        )

        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True, vendor='MANDIRI'
        )
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account,
        )
        self.autodebet_transaction = AutodebetMandiriTransactionFactory(
            autodebet_mandiri_account=self.autodebet_mandiri_account,
            account_payment=self.account_payment,
            status=AutodebetMandiriPaymentResultStatusConst.PENDING,
            original_partner_reference_no="12345678910",
            original_reference_no="12345678910",
        )
        self.autodebet_transaction.cdate = timezone.localtime(timezone.now()) - timedelta(hours=2)
        self.autodebet_transaction.save()
        self.autodebet_transaction.refresh_from_db()

        self.return_mock_inquiry_status_success = {
            "responseCode": "2005500",
            "responseMessage": "SUCCESSFUL",
            "originalPartnerReferenceNo": "12345678910",
            "originalReferenceNo": "12345678910",
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "Success",
            "originalResponseCode": "2005500",
            "originalResponseMessage": "SUCCESSFUL",
            "additionalInfo": {"approvalCode": "780909"},
        }
        self.return_mock_inquiry_status_insuff_funds = {
            "responseCode": "2005500",
            "responseMessage": "SUCCESSFUL",
            "originalPartnerReferenceNo": "12345678911",
            "originalReferenceNo": "12345678911",
            "latestTransactionStatus": "06",
            "transactionStatusDesc": "Failed",
            "originalResponseCode": "4035514",
            "originalResponseMessage": "INSUFFICIENT FUNDS",
        }

    @patch('juloserver.autodebet.tasks.reinquiry_payment_autodebet_mandiri_subtask.si')
    def test_reinquiry_payment_autodebet_mandiri_success(
        self,
        mock_reinquiry_payment_autodebet_mandiri_subtask,
    ):
        reinquiry_payment_autodebet_mandiri()

        mock_reinquiry_payment_autodebet_mandiri_subtask.assert_called_once()

    @patch('juloserver.autodebet.services.mandiri_services.send_sms_async.delay')
    @patch(
        'juloserver.autodebet.services.mandiri_services.update_moengage_for_payment_received_task.delay'
    )
    @patch('juloserver.autodebet.services.mandiri_services.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.services.mandiri_services.j1_refinancing_activation')
    @patch('juloserver.autodebet.services.mandiri_services.process_repayment_trx')
    @patch('juloserver.autodebet.services.mandiri_services.get_mandiri_autodebet_client')
    def test_reinquiry_payment_autodebet_mandiri_subtask_success(
        self,
        mock_get_client,
        mock_process_repayment_trx,
        mock_j1_refinancing_activation,
        mock_process_j1_waiver_before_payment,
        mock_update_moengage_for_payment_received_task,
        mock_send_sms_async,
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.inquiry_purchase.return_value = (
            self.return_mock_inquiry_status_success,
            None,
        )
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        inquiry_transaction_statusv2(self.autodebet_transaction.original_partner_reference_no)

        mock_j1_refinancing_activation.assert_called_once()
        mock_process_j1_waiver_before_payment.assert_called_once()

    @patch('juloserver.autodebet.services.mandiri_services.suspend_autodebet_insufficient_balance')
    @patch(
        'juloserver.autodebet.services.mandiri_services.send_event_autodebit_failed_deduction_task.delay'
    )
    @patch('juloserver.autodebet.services.mandiri_services.send_sms_async.delay')
    @patch(
        'juloserver.autodebet.services.mandiri_services.update_moengage_for_payment_received_task.delay'
    )
    @patch('juloserver.autodebet.services.mandiri_services.process_j1_waiver_before_payment')
    @patch('juloserver.autodebet.services.mandiri_services.j1_refinancing_activation')
    @patch('juloserver.autodebet.services.mandiri_services.process_repayment_trx')
    @patch('juloserver.autodebet.services.mandiri_services.get_mandiri_autodebet_client')
    def test_reinquiry_payment_autodebet_mandiri_subtask_insuff_fund(
        self,
        mock_get_client,
        mock_process_repayment_trx,
        mock_j1_refinancing_activation,
        mock_process_j1_waiver_before_payment,
        mock_update_moengage_for_payment_received_task,
        mock_send_sms_async,
        mock_send_event_autodebit_failed_deduction_task,
        mock_suspend_autodebet_insufficient_balance,
    ):
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.inquiry_purchase.return_value = (
            self.return_mock_inquiry_status_insuff_funds,
            None,
        )
        mock_process_repayment_trx.return_value = AccountTransactionFactory()

        inquiry_transaction_statusv2(self.autodebet_transaction.original_partner_reference_no)

        mock_j1_refinancing_activation.assert_not_called()
        mock_process_j1_waiver_before_payment.assert_not_called()
        mock_send_event_autodebit_failed_deduction_task.assert_called_once()
        mock_suspend_autodebet_insufficient_balance.assert_called_once()


class TestAutodebetMandiriPurchaseSubmitChainV2(TestCase):
    @factory.django.mute_signals(signals.pre_save, signals.post_save)
    def setUp(self):
        self.customer = CustomerFactory(customer_xid='56338192560570')
        self.account = AccountFactory(customer=self.customer)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True, vendor='MANDIRI'
        )
        AccountPaymentFactory(account=self.account, due_date=date.today(), due_amount=1000000)
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=30), due_amount=1000000
        )
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=60), due_amount=1000000
        )
        AccountPaymentFactory(
            account=self.account, due_date=date.today() - timedelta(days=90), due_amount=1000000
        )
        self.autodebet_mandiri_account = AutodebetMandiriAccountFactory()

        self.customer2 = CustomerFactory(customer_xid='56338192560570')
        self.account2 = AccountFactory(customer=self.customer2)
        self.autodebet_account2 = AutodebetAccountFactory(
            account=self.account2, is_use_autodebet=True, vendor='MANDIRI'
        )
        self.autodebet_mandiri_account2 = AutodebetMandiriAccountFactory(
            autodebet_account=self.autodebet_account2,
        )
        self.account_payment1 = AccountPaymentFactory(
            account=self.account2, due_date=date.today(), due_amount=2000000
        )
        self.account_payment2 = AccountPaymentFactory(
            account=self.account2,
            due_date=date.today() - timedelta(days=30),
            due_amount=0,
            paid_amount=2000000,
        )
        AutodebetMandiriTransactionFactory(
            autodebet_mandiri_account=self.autodebet_mandiri_account2,
            amount=2000000,
            account_payment=self.account_payment2,
            status=AutodebetMandiriPaymentResultStatusConst.SUCCESS,
        )

        self.max_limit_settings = FeatureSettingFactory(
            feature_name='autodebet_mandiri_max_limit_deduction_day',
            parameters={
                'maximum_amount': 3500000,
            },
        )
        FeatureSettingFactory(feature_name='autodebet_mandiri', is_active=True)

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_error(
        self, mock_access_token, mock_create_payment_purchase_submit
    ):
        account_payments = AccountPayment.objects.filter(account=self.account).order_by('due_date')
        for account_payment in account_payments.iterator():
            create_debit_payment_process_mandiri_subchainv2(True, account_payment.id)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            0,
        )

        self.autodebet_mandiri_account.autodebet_account = self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_create_payment_purchase_submit.return_value = (
            {
                'responseCode': '505400',
                'responseMessage': 'GENERAL ERROR',
            },
            'GENERAL ERROR',
        )
        for account_payment in account_payments.iterator():
            create_debit_payment_process_mandiri_subchainv2(True, account_payment.id)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            0,
        )

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_success_first_deduction(
        self, mock_access_token, mock_create_payment_purchase_submit
    ):
        account_payments = AccountPayment.objects.filter(account=self.account).order_by('due_date')

        self.autodebet_mandiri_account.autodebet_account = self.autodebet_account
        self.autodebet_mandiri_account.save()
        mock_create_payment_purchase_submit.return_value = (
            {'responseCode': '2025400', 'responseMessage': 'SUCCESSFUL'},
            None,
        )
        for account_payment in account_payments.iterator():
            create_debit_payment_process_mandiri_subchainv2(True, account_payment.id)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
            ).count(),
            4,
        )
        total_amount_deducted = (
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account,
                status__in=(
                    AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                    AutodebetMandiriPaymentResultStatusConst.PENDING,
                ),
                cdate__date=date.today(),
            ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
            or 0
        )
        self.assertEqual(total_amount_deducted, 3500000)

    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.create_payment_purchase_submit')
    @patch('juloserver.autodebet.clients.AutodebetMandiriClient.get_access_token')
    def test_create_debit_payment_process_mandiri_success_second_deduction(
        self, mock_access_token, mock_create_payment_purchase_submit
    ):
        account_payments = AccountPayment.objects.filter(account=self.account2).order_by('due_date')

        mock_create_payment_purchase_submit.return_value = (
            {'responseCode': '2025400', 'responseMessage': 'SUCCESSFUL'},
            None,
        )
        for account_payment in account_payments.iterator():
            create_debit_payment_process_mandiri_subchainv2(True, account_payment.id)
        self.assertEqual(
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account2,
            ).count(),
            2,
        )

        total_amount_deducted = (
            AutodebetMandiriTransaction.objects.filter(
                autodebet_mandiri_account=self.autodebet_mandiri_account2,
                status__in=(
                    AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                    AutodebetMandiriPaymentResultStatusConst.PENDING,
                ),
                cdate__date=date.today(),
            ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
            or 0
        )
        self.assertEqual(total_amount_deducted, 3500000)
