from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from juloserver.julo.tests.factories import (
    PaymentFactory,
    LoanFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestUnavailableDueDate(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)

    def test_unavailable_due_date(self):
        data = {'loan_id': self.loan.id}
        res = self.client.get('/loan_status/ajax_unavailable_due_dates/', data=data)
        self.assertEqual(res.status_code, 200)
