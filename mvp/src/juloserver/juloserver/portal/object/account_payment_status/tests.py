from django.core.urlresolvers import reverse
from django.test import TestCase
from datetime import timedelta, date, datetime
from django.utils import timezone

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.portal.object.account_payment_status.services import find_phone_number_from_application_table

from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             WorkflowFactory,
                                             SkiptraceFactory,
                                             LoanFactory,
                                             ApplicationHistoryFactory,
                                             PTPFactory)
from juloserver.account.tests.factories import (AccountFactory,
                                                ApplicationFactory,
                                                AccountLookupFactory)
from juloserver.grab.tests.factories import GrabSkiptraceHistoryFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from rest_framework.test import APITestCase
from juloserver.account_payment.models import AccountPayment


class TestAccountPaymentStatus(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)

    def testfind_phone_number_from_application_table(self):

        phone_number = '123123123'
        self.application.additional_contact_1_number = None
        self.application.additional_contact_2_number = None
        self.application.company_phone_number = None

        self.application.close_kin_mobile_phone = None
        self.application.mobile_phone_2 = None
        self.application.kin_mobile_phone = None

        self.application.landlord_mobile_phone = None
        self.application.new_mobile_phone = None
        self.application.spouse_mobile_phone = None


        self.application.additional_contact_1_number = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.additional_contact_1_number = None

        self.application.additional_contact_2_number = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.additional_contact_2_number = None

        self.application.company_phone_number = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.company_phone_number = None

        self.application.close_kin_mobile_phone = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.close_kin_mobile_phone = None

        self.application.mobile_phone_2 = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.mobile_phone_2 = None

        self.application.kin_mobile_phone = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.kin_mobile_phone = None

        self.application.landlord_mobile_phone = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.landlord_mobile_phone = None

        self.application.new_mobile_phone = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.new_mobile_phone = None

        self.application.spouse_mobile_phone = '123123123'
        self.application.save()
        qs = AccountPayment.objects.filter(id=self.account_payment.id)
        result = find_phone_number_from_application_table(qs, phone_number)
        self.assertEqual(result[0].id, self.account_payment.id)
        self.application.spouse_mobile_phone = None


class TestAjaxAccountPaymentListView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.client.force_login(self.user)

    def test_ajax_account_payment_list_view(self):
        AccountPaymentFactory.create_batch(10)
        url = reverse('account_payment_status:ajax_account_payment_list_view')

        params = {
            'max_per_page': 50,
            'page': 1,
            'freeday_checked': False,
            'status_code': 'whatsapp',
            'today_checked': False,
            'search_q': ''
        }

        # 1x get Session CSRF
        # 1x get auth user
        # 1x get agent
        # 1x get 3 page account_payment_ids
        # 1x get account_payments
        # Filling the extra data in the row
        #   1x get the account_payment based on the values
        #   1x List of latest_loan by account_ids
        #   1x List of latest_application by account_ids
        #   1x List of total_cashback by account_payment_ids
        #   1x List of total_loan_amount by account_ids
        # 1x list of status for filter
        # 1x list of agent for filter
        # 1x list of autodialer call status for filter
        # 1x list of partner for filter
        with self.assertNumQueries(35):
            response = self.client.get(url, data=params)

        self.assertEqual(200, response.status_code, response.json())


class TestAjaxSkiptraceHistory(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.client.force_login(self.user)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.customer = CustomerFactory()
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )
        self.application = ApplicationFactory(account=self.account, workflow=self.workflow)
        self.application_2 = ApplicationFactory(account=self.account, workflow=self.workflow)
        self.skiptrace = SkiptraceFactory(application=self.application)
        self.grab_skiptrace1 = GrabSkiptraceHistoryFactory(
            application=self.application, skiptrace=self.skiptrace)
        self.grab_skiptrace2 = GrabSkiptraceHistoryFactory(
            application=self.application, skiptrace=self.skiptrace)

    def test_ajax_get_skiptrace_history_success(self):
        url = reverse(
            'account_payment_status:ajax_get_skiptrace_history', args=[self.application.id])
        # this query params only for unit_test purpose
        query_params = {
            'unit_test': 1
        }
        response = self.client.get(url, data=query_params)
        self.assertEqual(200, response.status_code, response.json())
        self.assertEqual(len(response.json()['data']), 2)

    def test_ajax_get_skiptrace_history_failed(self):
        url = reverse(
            'account_payment_status:ajax_get_skiptrace_history', args=[self.application_2.id])
        response = self.client.get(url)
        print(response.json())
        self.assertEqual(200, response.status_code, response.json())
        self.assertEqual(response.json(), {'messages': 'more skiptrace loaded', 'result': 'success', 'data': []})


class TestSkiptraceHistory(APITestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.user_auth = AuthUserFactory()
        self.client.force_login(self.user_auth)
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date = date.today() + timedelta(days=40))
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            customer=self.customer,
        )
        self.appliaction_history = ApplicationHistoryFactory(
            application_id=self.application.id
        )
        self.ptp = PTPFactory(
            account_payment=self.account_payment,
            account=self.account,
            ptp_date=datetime.today() + timedelta(days=10),
            ptp_status=None
        )
        self.skiptrace = SkiptraceFactory(customer=self.customer)

    def test_ptp_on_going(self):
        pdp_date = self.today.date() + timedelta(days=5)
        data = dict(
            skiptrace=str(self.skiptrace.id),
            application=str(self.application.id),
            start_ts=self.today,
            end_ts=self.today,
            call_result="9",
            account_payment=str(self.account_payment.id),
            level1="CONTACTED",
            level2="RPC",
            level3="RPC+-+PTP",
            skip_ptp_amount="100",
            skip_ptp_date=str(pdp_date.strftime('%d-%m-%Y')),
            skip_note="",
            skip_time="",
            non_payment_reason="",
            spoke_with="User",
            source="CRM",
            loan_id=str(self.loan.id)
        )
        url = '/account_payment_status/skiptrace_history/'
        response = self.client.post(url, data=data)
        self.assertEqual(400, response.status_code)
        self.assertEqual(response.json(), {"status": "failed", "message": "on going ptp"})
