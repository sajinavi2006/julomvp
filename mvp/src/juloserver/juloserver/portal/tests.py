from future import standard_library

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.portal.object.payment_status.utils import payment_filter_search_field

standard_library.install_aliases()
import io
from builtins import range
from urllib.parse import urlencode

from django.contrib.auth.models import Group
from django.conf import settings
from django.contrib.auth.models import User
from django.test import (
    Client,
    TestCase,
    override_settings,
    RequestFactory,
)
from mock import patch
from rest_framework import status
from rest_framework.reverse import reverse
from xlwt import Workbook

from juloserver.julo.tests.factories import (
    CustomerFactory,
    LoanFactory,
    PaymentFactory,
    PaymentMethodFactory,
    StatusLookupFactory,
    AuthUserFactory,
    CrmSettingFactory,
)
from juloserver.portal.object.lender.utils import FaspayStatementParser


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAdmin2(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_user(self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.loan = LoanFactory()
        self.locked_payment = self.loan.payment_set.first()

    def test_unlock_payment(self):
        response = self.client.get(
            '/payment_status/set_payment_unlocked/?payment_id=%d' % self.locked_payment.id
        )
        assert response.status_code == 200


class FaspayStatementParserTest(TestCase):
    def test_parse(self):
        wb = Workbook()
        Sheet1 = wb.add_sheet('Detail')
        for row in range(0, 6):
            for col in range(0, 5):
                Sheet1.write(row, col, 123)
        fast_pay = FaspayStatementParser()
        in_memory_file = io.BytesIO()
        wb.save(in_memory_file)
        response = fast_pay.parse(in_memory_file.getvalue())
        self.assertEqual(response, [])


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPaymentReminderSmsAndEmail(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.status_lookup = StatusLookupFactory()
        self.payment = PaymentFactory(loan=self.loan)

    def test_payment_remainder_sms(self):
        data = {
            'payment_id': self.payment.id,
            'sms_message': '',
            'to_number': +628159147752,
            'phone_type': 'mobile_phone_1',
            'category': 'PTP/Janji Bayar',
            'template_code': 'crm_sms_ptp',
        }
        url = '/payment_status/send_sms'
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_payment_remainder_email(self):
        data = {
            'payment_id': self.payment.id,
            'content': '',
            'to_email': 'test@gmail.com',
            'subject': 'test',
            'category': 'PTP/Janji Bayar',
            'template_code': 'crm_sms_ptp',
            'pre_header': 'test',
        }
        url = '/payment_status/send_email'
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestIdentifySearchValue(TestCase):
    def setUp(self):
        pass

    def test_input_va_number(self):
        customer = CustomerFactory()
        payment_method = PaymentMethodFactory(
            payment_method_code=100123,
            virtual_account='10012345678910',
            loan=None,
            customer=customer,
        )
        search_field, value = payment_filter_search_field(payment_method.virtual_account)
        assert search_field == 'loan__customer_id'


class TestSelectActiveRole(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.user.password = 'top secret'
        self.agent = AgentFactory(user=self.user)
        self.request_factory = RequestFactory()
        self.credentials = {
            'username': self.agent.user.username,
            'password': self.agent.user.password
        }

    def test_select_active_role_with_no_role(self):
        group = Group(name="fraudcolls")
        group.save()
        self.user.groups.add(group)
        response = self.client.post(reverse('dashboard:default'), self.credentials)
        self.assertContains(response, "Perhatian!", status_code=200)
        self.assertContains(response, "DASHBOARD UTAMA TIDAK TERSEDIA UNTUK ROLE ANDA", status_code=200)
        self.assertTemplateUsed(response, 'error/no_dashboard.html')

    def test_select_active_role_with_new_role(self):
        group = Group(name="fraudcolls")
        group.save()
        self.user.groups.add(group)
        self.crm_setting = CrmSettingFactory(
            user=self.user, role_select='fraudcolls', role_default='fraudcolls'
        )
        response = self.client.post(reverse('dashboard:default'), self.credentials)
        self.assertContains(response, "Perhatian!", status_code=200)
        self.assertContains(response, "DASHBOARD UTAMA TIDAK TERSEDIA UNTUK ROLE ANDA", status_code=200)
        self.assertTemplateUsed(response, 'error/no_dashboard.html')

    def test_select_active_role_with_existing_role(self):
        group = Group(name="admin_full")
        group.save()
        self.user.groups.add(group)
        self.crm_setting = CrmSettingFactory(user=self.user)
        response = self.client.post(reverse('dashboard:default'), self.credentials)
        self.assertNotContains(response, "Perhatian!", status_code=200)
        self.assertNotContains(response, "DASHBOARD UTAMA TIDAK TERSEDIA UNTUK ROLE ANDA", status_code=200)
        self.assertTemplateNotUsed(response, 'error/no_dashboard.html')

    def test_select_active_role_with_no_role_no_group(self):
        response = self.client.post(reverse('dashboard:default'), self.credentials)
        self.assertContains(response, "Perhatian!", status_code=200)
        self.assertContains(response, "DASHBOARD UTAMA TIDAK TERSEDIA UNTUK ROLE ANDA", status_code=200)
        self.assertTemplateUsed(response, 'error/no_dashboard.html')

