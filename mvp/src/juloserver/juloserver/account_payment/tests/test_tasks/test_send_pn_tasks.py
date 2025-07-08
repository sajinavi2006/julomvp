from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentwithPaymentFactory
from juloserver.julo.models import Payment
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory, ApplicationFactory

from juloserver.account_payment.tasks.scheduled_tasks import send_early_repayment_experience_pn


class TestSendEarlyRepaymentCashbackPN(APITestCase):
    def setUp(self):
        today = timezone.localtime(timezone.now()).date()

        self.nemesys_payload = {}
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, fullname='customer name 1')
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentwithPaymentFactory(
            account=self.account,
            due_date=today,
            paid_date=today,
            due_amount=0
        )
        self.application = ApplicationFactory(account=self.account)

    def set_nemesys_payload(self, json_payload):
        self.nemesys_payload = json_payload

    @mock.patch('juloserver.julo.clients.pn.get_julo_nemesys_client')
    def test_send_pn_cashback_early_repayment(self, mock_nemesys):
        payments = Payment.objects.filter(account_payment=self.account_payment)
        payments.update(payment_status=330, cashback_earned=3000)

        account_payment_payments = {
            self.account_payment.id: {
                'payments': [payment.id for payment in payments]
            }
        }

        mock_nemesys.return_value.push_notification_api.side_effect = self.set_nemesys_payload
        send_early_repayment_experience_pn.delay(account_payment_payments, self.account.id)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_cashback_potential')

        send_early_repayment_experience_pn.delay(account_payment_payments, 12)
        self.assertFalse(self.nemesys_payload.get('template_code') == 'pn_cashback_claim')

