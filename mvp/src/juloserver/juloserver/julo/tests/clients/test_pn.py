from django.utils import timezone
from django.test.testcases import TestCase
from mock import patch

from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.constants import PushNotificationLoanEvent, PNBalanceConsolidationVerificationEvent
from juloserver.julo.tasks import send_pn_invalidate_caching_loans_android
from juloserver.julo.tests.factories import CustomerFactory, StatusLookupFactory, LoanFactory, \
    ApplicationFactory, DeviceFactory
from juloserver.streamlined_communication.constant import PageType


class TestPnTailorBackup(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountwithApplicationFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=timezone.localtime(timezone.now()).replace(day=1, month=8)
        )

    @patch('juloserver.julo.clients.pn.JuloPNClient.send_downstream_message')
    def test_pn_tailor_backup(self, mock_send_message):
        pn_client = get_julo_pn_client()
        pn_client.pn_tailor_backup('gcm_reg_id', self.account_payment, 'tailor_template_code', -4)

        mock_send_message.assert_called_once_with(
            registration_ids=['gcm_reg_id'],
            notification={
                'title': 'Bayar Lebih Awal, Untung Lebih Besar! ' + u'\U0001F4B0',
                'body': "Yuk, bayar tagihan Rp 300.000 bulan Agustus sekarang juga!"
            },
            data={
                "destination_page": PageType.LOAN,
                "account_payment_id": self.account_payment.id,
                "customer_id": self.customer.id,
                "application_id": self.account_payment.account.application_set.last().id
            },
            template_code='tailor_template_code'
        )


class TestPnLoan(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.account = AccountwithApplicationFactory(customer=self.customer)
        code = StatusLookupFactory(status_code=220)
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=code, application=self.application,
            loan_amount=10000000
        )
        self.device = DeviceFactory(customer=self.customer)

    @patch('juloserver.julo.clients.pn.JuloPNClient.send_downstream_message')
    def pn_loan_success_x220(self, mock_send_message):
        send_pn_invalidate_caching_loans_android(self.customer, self.loan.id, self.loan.loan_amount)
        mock_send_message.assert_called_once_with(
            registration_ids=[self.device.gcm_reg_id],
            notification={"title": "non-popup"},
            data={
                'event': PushNotificationLoanEvent.LOAN_SUCCESS_X220,
                'loan_xid': self.loan.loan_xid,
                'loan_amount': self.loan.loan_amount,
                'body': 'Inform loan success 220',
            },
            template_code='inform_loan_success_220'
        )


class TestPnDowngradeInfoAlert(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.account = AccountwithApplicationFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)

    @patch('juloserver.julo.clients.pn.JuloPNClient.send_downstream_message')
    def test_pn_downgrade_alert(self, mock_send_message):
        from juloserver.julo.constants import PushNotificationDowngradeAlert
        from juloserver.julo.tasks import send_pn_invalidate_caching_downgrade_alert
        send_pn_invalidate_caching_downgrade_alert(self.customer)
        mock_send_message.assert_called_once_with(
            registration_ids=[self.device.gcm_reg_id],
            notification={"title": "non-popup"},
            data={
                'event': PushNotificationDowngradeAlert.DOWNGRADE_INFO_ALERT,
                'customer_id': self.customer,
                'body': 'Invalidate downgrade alert',
            },
            template_code='pn_downgrade_alert'
        )


class TestPNBalanceConsolidationVerification(TestCase):
    def setUp(self):
        self.device = DeviceFactory()

    @patch('juloserver.julo.clients.pn.JuloPNClient.send_downstream_message')
    def test_pn_balance_consolidation_verification_approve(self, mock_send_downstream_message):
        pn_client = get_julo_pn_client()
        pn_client.pn_balance_consolidation_verification_approve(self.device.gcm_reg_id)
        mock_send_downstream_message.assert_called_once_with(
            registration_ids=[self.device.gcm_reg_id],
            notification={"title": "non-popup"},
            data={
                'event': PNBalanceConsolidationVerificationEvent.APPROVED_STATUS_EVENT,
                'body': 'The balance consolidation verification is approved',
            },
            template_code='balance_consolidation_verification_status_update'
        )
