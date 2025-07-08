from django.test import TestCase

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.models import VendorDataHistory
from juloserver.julo.services2.reminders import Reminder
from juloserver.julo.tests.factories import (
    CustomerFactory,
    PaymentFactory,
)


class TestReminder(TestCase):
    def test_create_reminder_history(self):
        payment = PaymentFactory()
        customer = CustomerFactory()
        reminder = Reminder()
        reminder.create_reminder_history(
            payment=payment,
            customer=customer,
            template="random-template",
            vendor="random-vendor",
            reminder_type="random-reminder-type",
        )

        hist = VendorDataHistory.objects.get(payment_id=payment.id)
        self.assertEqual(hist.customer_id, customer.id)
        self.assertEqual(hist.vendor, "random-vendor")
        self.assertEqual(hist.reminder_type, "random-reminder-type")
        self.assertEqual(hist.template_code, "random-template")

    def test_create_reminder_history_with_customer_id(self):
        payment = PaymentFactory()
        customer = CustomerFactory()
        reminder = Reminder()
        reminder.create_reminder_history(
            payment=payment,
            customer=customer.id,
            template="random-template",
            vendor="random-vendor",
            reminder_type="random-reminder-type",
        )

        hist = VendorDataHistory.objects.get(payment_id=payment.id)
        self.assertEqual(hist.customer_id, customer.id)

    def test_create_j1_reminder_history(self):
        account_payment = AccountPaymentFactory(status_id=320)
        customer = CustomerFactory()
        reminder = Reminder()
        reminder.create_j1_reminder_history(
            account_payment=account_payment,
            customer=customer,
            template="random-template",
            vendor="random-vendor",
            reminder_type="random-reminder-type",
        )

        hist = VendorDataHistory.objects.get(account_payment_id=account_payment.id)
        self.assertEqual(hist.customer_id, customer.id)
        self.assertEqual(hist.account_payment_status_code, account_payment.status_id)
        self.assertEqual(hist.vendor, "random-vendor")
        self.assertEqual(hist.reminder_type, "random-reminder-type")
        self.assertEqual(hist.template_code, "random-template")

    def test_create_j1_reminder_history_with_customer_id(self):
        account_payment = AccountPaymentFactory()
        customer = CustomerFactory()
        reminder = Reminder()
        reminder.create_j1_reminder_history(
            account_payment=account_payment,
            customer=customer.id,
            template="random-template",
            vendor="random-vendor",
            reminder_type="random-reminder-type",
        )

        hist = VendorDataHistory.objects.get(account_payment_id=account_payment.id)
        self.assertEqual(hist.customer_id, customer.id)
