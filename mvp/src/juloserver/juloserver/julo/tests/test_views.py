from mock import patch

from django.contrib.auth.models import Group
from django.test.testcases import TestCase
from rest_framework import status
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             ApplicationFactory,
                                             CustomerFactory,
                                             PaymentMethodFactory)
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.account.tests.factories import AccountFactory


class TestAppStatusView(TestCase):

    def setUp(self):
        group = Group(name="bo_full")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.application = ApplicationFactory()

    def test_ajax_change_email(self):
        data = {
            'application_id': self.application.id,
            'new_email': 'test@testing.com'
        }
        response = self.client.post('/app_status/ajax_change_email',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_change_email_uppercase(self):
        expected_email = 'new-email@testing.com'
        data = {
            'application_id': self.application.id,
            'new_email': 'NeW-Email@teSTing.com'
        }
        response = self.client.post('/app_status/ajax_change_email',
                                    data)

        self.application.refresh_from_db()
        self.application.customer.refresh_from_db()

        self.assertEqual(expected_email, self.application.email)
        self.assertEqual(expected_email, self.application.customer.email)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch.object(JuloEmailClient, 'send_email', return_value=['status', 'subject', {'X-Message-Id': 1}])
    def test_ajax_send_reset_pin_email(self, mock_email):
        data = {
            'application_id': self.application.id
        }
        response = self.client.post('/app_status/ajax_send_reset_pin_email',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestRepaymentChannelView(TestCase):

    def setUp(self):
        group = Group(name="collection_supervisor")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)

    def test_get_available_repaymet_channel_for_account_search(self):
        data = {
            'account_id': self.account.id,
            'submit_type': 'search',
            'bank_code': '',
            'is_primary_j1_payment_method_id': '',
            'is_shown_j1_payment_methods_id': []
        }
        response = self.client.post('/dashboard/get_available_repaymet_channel_for_account/',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_available_repaymet_channel_for_account_update(self):
        data = {
            'account_id': self.account.id,
            'submit_type': 'update',
            'bank_code': '',
            'is_primary_j1_payment_method_id': 1,
            'is_shown_j1_payment_methods_id': [1]
        }
        response = self.client.post('/dashboard/get_available_repaymet_channel_for_account/',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_available_repaymet_channel_for_account_generate_va(self):
        data = {
            'account_id': self.account.id,
            'submit_type': 'generate_va',
            'bank_code': '013',
            'is_primary_j1_payment_method_id': '',
            'is_shown_j1_payment_methods_id': []
        }
        response = self.client.post('/dashboard/get_available_repaymet_channel_for_account/',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
