import mock
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.tests.factories import CheckoutRequestFactory
from juloserver.julo.models import PaymentMethod
from juloserver.julo.tests.factories import (
    StatusLookupFactory,
    DeviceFactory,
)
from juloserver.account_payment.tasks.scheduled_tasks import send_checkout_experience_pn


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCollectionPushNotification(APITestCase):
    def setUp(self):
        self.current_date = timezone.localtime(timezone.now()).date()
        self.status = StatusLookupFactory(status_code=420)
        self.nemesys_payload = {}

    def set_nemesys_payload(self, json_payload):
        self.nemesys_payload = json_payload

    @mock.patch('juloserver.julo.clients.pn.get_julo_nemesys_client')
    def test_send_pn_for_checkout_experience(self, mock_nemesys):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        DeviceFactory(customer=account.customer)
        mock_nemesys.return_value.push_notification_api.side_effect = self.set_nemesys_payload
        send_checkout_experience_pn.delay([account.customer.id], CheckoutRequestCons.EXPIRED)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_checkout_expired')
        send_checkout_experience_pn.delay([account.customer.id], CheckoutRequestCons.CANCELED)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_checkout_cancelled')
        payment_method = PaymentMethod.objects.create(
            payment_method_code=123,
            payment_method_name="Payment Method",
            bank_code=123,
            virtual_account=123456789,
            customer=account.customer,
            is_primary=True,
            is_shown = True,
            is_preferred = False,
            sequence = 1)
        checkout_request = CheckoutRequestFactory(
            account_id=account, checkout_amount=10000, total_payments=10000,
            checkout_payment_method_id=payment_method
        )
        send_checkout_experience_pn.delay(
            [account.customer.id], CheckoutRequestCons.PAID_CHECKOUT,
            actual_paid_amount=10000, checkout_request_id=checkout_request.id,
            total_payment_before_updated=10000)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_checkout_payfull')
        send_checkout_experience_pn.delay(
            [account.customer.id], CheckoutRequestCons.PAID_CHECKOUT,
            actual_paid_amount=1000, checkout_request_id=checkout_request.id,
            total_payment_before_updated=9000)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_checkout_paylessfull')
        send_checkout_experience_pn.delay(
            [account.customer.id], CheckoutRequestCons.PAID_CHECKOUT,
            actual_paid_amount=20000, checkout_request_id=checkout_request.id,
            total_payment_before_updated=10000)
        self.assertTrue(self.nemesys_payload.get('template_code') == 'pn_checkout_paymorefull')
