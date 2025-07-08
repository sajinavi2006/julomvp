from django.test import Client
from juloserver.julo.tests.factories import (
    LoanFactory, CrmSettingFactory
)
from django.core.urlresolvers import reverse
from rest_framework import status
from django.test.testcases import TestCase
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.whatsapp.models import WhatsappTemplate

client = Client()

class TestJuloLenderTransaction(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loan = LoanFactory()
        cls.user = cls.loan.customer.user
        application = cls.loan.application
        application.product_line_id = 10
        application.save()
        CrmSettingFactory(user=cls.user)
        client.force_login(cls.user)

    def setUp(self):
        self.loan.refresh_from_db()

    def test_reversal_payment_event_check_destination_success(self):
        last_payment = self.loan.payment_set.last()

        response = client.post(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': last_payment.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['result'], 'success')

    def test_reversal_payment_event_check_destination_payment_not_found(self):
        random_id = 49746454545

        response = client.post(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': random_id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['result'], 'failed')
        self.assertEqual(response.json()['message'],
                         'Payment id %s tidak ditemukan silahkan cek kembali' % random_id)

    def test_reversal_payment_event_check_destination_already_paid_off(self):
        last_payment = self.loan.payment_set.last()
        last_payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
        last_payment.save()
        response = client.post(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': last_payment.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['result'], 'failed')
        self.assertEqual(response.json()['message'],
                         'Payment id %s sudah lunas silahkan cek kembali' % last_payment.id)

    def test_reversal_payment_event_check_destination_using_get(self):
        last_payment = self.loan.payment_set.last()
        response = client.get(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': last_payment.id}
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_reversal_payment_event_check_destination_without_csrf(self):
        last_payment = self.loan.payment_set.last()
        client.handler.enforce_csrf_checks = True
        response = client.post(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': last_payment.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reversal_payment_event_check_destination_without_login(self):
        last_payment = self.loan.payment_set.last()
        client.logout()
        response = client.post(
            reverse('payment_status:reversal_payment_event_check_destination'),
            {'payment_id': last_payment.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_payment_status_change_success_loaded(self):
        last_payment = self.loan.payment_set.last()
        WhatsappTemplate.objects.create(type='payment_collection_mtl', text_content='')
        response = client.get(
            reverse('payment_status:change_status', kwargs={'pk': last_payment.id}),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment_obj = response.context['payment_obj']
        self.assertEqual(payment_obj.id, last_payment.id)
