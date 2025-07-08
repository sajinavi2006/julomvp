from django.test.testcases import TestCase
from juloserver.account.tests.factories import AccountFactory
from juloserver.loan_refinancing.tests.factories import WaiverRequestFactory
from django.utils import timezone
from datetime import timedelta
from ..tasks import send_slack_notification_for_j1_waiver_approver
from juloserver.loan_refinancing.constants import (
    ApprovalLayerConst,
    WAIVER_SPV_APPROVER_GROUP,
)
from ..tasks.scheduled_tasks import send_email_for_multiple_ptp_waiver_expired_plus_1
from ...account_payment.tests.factories import AccountPaymentFactory
from ...julo.models import EmailHistory
from ...julo.tests.factories import LoanFactory, PaymentFactory, CustomerFactory, ApplicationFactory, \
    PaymentMethodFactory
from ...payback.constants import WaiverConst
from ...payback.models import WaiverTemp
from ...payback.tests.factories import WaiverTempFactory
from django.test.utils import override_settings
from mock import patch


class TestTasksWaiver(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.waiver_request = WaiverRequestFactory(
            account=self.account, loan=None,
            waiver_validity_date=timezone.localtime(timezone.now()).date())

    def test_send_slack_notification_for_j1_waiver_approver(self):
        waiver_request = self.waiver_request
        today_date = timezone.localtime(timezone.now()).date()
        today_minus2 = today_date - timedelta(days=2)

        slack_notif = send_slack_notification_for_j1_waiver_approver(self.account.id)
        assert slack_notif is None

        waiver_request.waiver_validity_date = today_minus2
        waiver_request.save()
        slack_notif = send_slack_notification_for_j1_waiver_approver(self.account.id)
        assert slack_notif is None

        waiver_request.waiver_validity_date = today_date
        waiver_request.approval_layer_state = ApprovalLayerConst.TL
        waiver_request.save()
        slack_notif = send_slack_notification_for_j1_waiver_approver(self.account.id)
        assert slack_notif is None


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestWaiverScheduledTask(TestCase):
    def setUp(self):
        pass

    @patch.object(WaiverTemp.objects, 'filter')
    @patch('juloserver.waiver.services.notification_related.get_julo_email_client')
    def test_multiple_ptp_expired_plus_1_mtl(self, mocked_email_client, mock_waiver_temp):
        customer_mtl = CustomerFactory(id=1009997599, email='mtlcustomer@unitest.com')
        mtl_application = ApplicationFactory(
            id=1009997555, address_kodepos=23115, customer=customer_mtl, account=None)
        loan = LoanFactory(application=mtl_application)
        payment = PaymentFactory(loan=loan, account_payment=None)

        today = timezone.localtime(timezone.now()).date()
        expired_plus_1 = today - timedelta(days=1)

        waiver_request_mtl = WaiverRequestFactory(
            loan=loan, is_multiple_ptp_payment=True, waiver_validity_date = expired_plus_1)
        waiver_temp_mtl = WaiverTempFactory(
            loan=loan, payment=payment,
            waiver_request=waiver_request_mtl,
            valid_until=expired_plus_1,
            status=WaiverConst.EXPIRED_STATUS
        )

        PaymentMethodFactory(
            loan=loan, customer=customer_mtl, is_primary=True)

        mocked_email_client.return_value.email_multiple_ptp_and_expired_plus_1.return_value = \
            (202, {'X-Message-Id': 'multiple_ptp_after_expiry_date_mtl_123'},
             'dummy_subject', 'dummy_message')
        mock_waiver_temp.return_value.filter.return_value = [waiver_temp_mtl]
        send_email_for_multiple_ptp_waiver_expired_plus_1('WIB')
        email_history = EmailHistory.objects.filter(
            customer=customer_mtl,
            template_code='multiple_ptp_after_expiry_date')
        mock_waiver_temp.assert_called_once
        self.assertIsNotNone(email_history)

    @patch.object(WaiverTemp.objects, 'filter')
    @patch('juloserver.waiver.services.notification_related.get_julo_email_client')
    def test_multiple_ptp_expired_plus_1_j1(self, mocked_email_client, mock_waiver_temp):
        customer_j1 = CustomerFactory(
            id=1009911111,
            email='j1customer@unitest.com'
        )
        account = AccountFactory(customer=customer_j1, id=11111)
        AccountPaymentFactory(account=account)
        j1_application = ApplicationFactory(
            account=account, address_kodepos=97116,
            customer=customer_j1, email=customer_j1.email)
        account_payment = account.accountpayment_set.first()
        waiver_request_j1 = WaiverRequestFactory(
            account=account, is_multiple_ptp_payment=True,
            loan=None, is_j1=True
        )
        waiver_temp_j1 = WaiverTempFactory(
            account=account,
            loan=None, payment=None,
            waiver_request=waiver_request_j1
        )
        PaymentMethodFactory(
            customer=customer_j1, is_primary=True, loan=None)
        today = timezone.localtime(timezone.now()).date()
        expired_plus_1 = today - timedelta(days=1)
        waiver_request_j1.waiver_validity_date = expired_plus_1
        waiver_temp_j1.valid_until = expired_plus_1
        waiver_temp_j1.status = WaiverConst.EXPIRED_STATUS
        waiver_request_j1.save()
        waiver_temp_j1.save()
        mocked_email_client.return_value.email_multiple_ptp_and_expired_plus_1.return_value = \
            (202, {'X-Message-Id': 'multiple_ptp_after_expiry_date_j1_123'},
             'dummy_subject', 'dummy_message')
        mock_waiver_temp.return_value.filter.return_value = [waiver_temp_j1]
        send_email_for_multiple_ptp_waiver_expired_plus_1.delay('WIT')
        email_history = EmailHistory.objects.filter(
            customer=customer_j1,
            template_code='multiple_ptp_after_expiry_date').count()
        assert email_history > 0
