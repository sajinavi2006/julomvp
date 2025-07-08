import csv
import io
import datetime
import json
from unittest.mock import (
    patch,
    Mock,
    call,
)

from django.contrib.auth.models import (
    Group,
    AnonymousUser,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.urlresolvers import reverse
from django.forms import model_to_dict
from django.http import JsonResponse
from django.test import TestCase, RequestFactory
from django.utils import timezone


from juloserver.account_payment.tests.factories import AccountPaymentFactory, AccountFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.collection_vendor.tests.factories import SkiptraceHistoryFactory
from juloserver.account.models import Account
from juloserver.julo.models import Skiptrace
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    SkiptraceResultChoiceFactory,
    ApplicationFactory,
    PaymentFactory,
    LoanFactory,
    VoiceCallRecordFactory,
    CootekRobocallFactory,
    SkiptraceFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.sales_ops.constants import (
    SalesOpsRoles,
    AutodialerConst, BucketCode,
)
from juloserver.sales_ops import exceptions as sales_ops_exc
from juloserver.sales_ops.exceptions import SalesOpsException
from juloserver.sales_ops.services.autodialer_services import AutodialerDelaySetting
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsAgentAssignmentFactory,
    SalesOpsAutodialerSessionFactory,
    SalesOpsAutodialerActivityFactory,
)
from juloserver.sales_ops.views import crm_views

PACKAGE_NAME = 'juloserver.sales_ops.views.crm_views'


class TestSalesOpsBucketList(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_get(self):
        url = reverse('sales_ops.crm:list')
        with self.assertTemplateUsed('sales_ops/list.html'):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('SALES OPS - ALL ACCOUNTS', str(response.content))

    def test_get_not_sales_ops_role(self):
        url = reverse('sales_ops.crm:list')
        user = AuthUserFactory()
        group = Group.objects.create(name=JuloUserRoles.BO_FULL)
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)


class TestDashboardBoDataVerifier(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_as_sales_ops(self):
        group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(group)

        url = reverse('dashboard:bo_data_verifier')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('test_id="sales_ops.bucket_count"', str(response.content))


class TestSalesOpsBucketDetailView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(self.group)
        self.loan = LoanFactory()
        self.client.force_login(self.user)

    def test_get(self):
        lineup = SalesOpsLineupFactory()
        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        with self.assertTemplateUsed('sales_ops/detail.html'):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Detail Lineup: {}'.format(lineup.id), str(response.content))

    def test_get_has_last_sales_ops_call_rpc(self):
        now = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        SalesOpsAgentAssignmentFactory(
            lineup=lineup, completed_date=now, is_rpc=True, is_active=False
        )
        url = reverse('sales_ops.crm:detail', args=[lineup.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('(RPC)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    def test_get_has_last_sales_ops_call_non_rpc(self):
        now = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        SalesOpsAgentAssignmentFactory(
            lineup=lineup, completed_date=now, is_rpc=False, is_active=False
        )
        url = reverse('sales_ops.crm:detail', args=[lineup.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('(NON-RPC)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    def test_get_has_last_sales_ops_call_active(self):
        now = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        SalesOpsAgentAssignmentFactory(
            lineup=lineup, assignment_date=now, is_active=True
        )
        url = reverse('sales_ops.crm:detail', args=[lineup.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('(Calling)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    def test_get_has_last_call_collection_intelix(self):
        now = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        account = Account.objects.get(pk=lineup.account_id)
        payment = PaymentFactory(account_payment=AccountPaymentFactory(account=account))
        SkiptraceHistoryFactory(
            call_result=SkiptraceResultChoiceFactory(name='call result'),
            payment=payment,
            application=ApplicationFactory(account_id=lineup.account_id),
            end_ts=now,
            source='Intelix'
        )

        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('(call result)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    def test_get_has_last_call_collection_crm(self):
        now = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        account = Account.objects.get(pk=lineup.account_id)
        payment = PaymentFactory(account_payment=AccountPaymentFactory(account=account))
        SkiptraceHistoryFactory(
            call_result=SkiptraceResultChoiceFactory(name='call result'),
            payment=payment,
            application=ApplicationFactory(account_id=lineup.account_id),
            end_ts=now,
            source='CRM'
        )

        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('(call result)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    @patch('django.utils.timezone.now')
    def test_get_has_last_call_collection_nexmo(self, mock_now):
        import django.utils.timezone   # To mock timezone.now() in django library
        mock_now.return_value = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        VoiceCallRecordFactory(
            application=ApplicationFactory(account_id=lineup.account_id),
            event_type='event 1',
            status='status'
        )

        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('(event 1 - status)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    @patch('django.utils.timezone.now')
    def test_get_has_last_call_collection_cootek(self, mock_now):
        import django.utils.timezone   # To mock timezone.now() in django library
        mock_now.return_value = datetime.datetime(2020, 1, 1, 0, 0, 0)
        lineup = SalesOpsLineupFactory()
        account = Account.objects.get(pk=lineup.account_id)
        CootekRobocallFactory(
            account_payment=AccountPaymentFactory(account=account),
            call_status='completed',
            task_status='finished',
        )

        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('(finished - completed)', str(response.content))
        self.assertIn('1 Jan 2020 00:00:00', str(response.content))

    def test_get_has_form(self):
        lineup = SalesOpsLineupFactory(
            inactive_until=datetime.date(2020, 1, 1),
            reason='random'
        )

        url = reverse('sales_ops.crm:detail', args=[lineup.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('test-id="sales-ops-form"', str(response.content))
        self.assertIn('name="inactive_until"', str(response.content))
        self.assertIn('name="inactive_note"', str(response.content))
        self.assertIn('2020-01-01', str(response.content))
        self.assertIn('random', str(response.content))

    def test_post(self):
        lineup = SalesOpsLineupFactory(
            inactive_until=datetime.datetime(2020, 1, 1, 0, 0, 0),
            reason='random'
        )
        url = reverse('sales_ops.crm:detail', args=[lineup.id])

        post_data = {
            'inactive_until': '2021-01-31 12:13:14',
            'inactive_note': 'test reason',
        }
        response = self.client.post(url, data=post_data)

        self.assertEqual(response.status_code, 302)
        lineup.refresh_from_db()

        localtime = timezone.localtime(datetime.datetime(2021, 1, 31, 12, 13, 14))
        self.assertEqual(localtime, lineup.inactive_until)
        self.assertEqual('test reason', lineup.reason)


class TestPrivateGetAutodialerAgent(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.request_factory = RequestFactory()
        self.request = self.request_factory.get('/url')

    def test_success(self):
        self.request.user = self.user
        ret_agent = crm_views._get_autodialer_agent(self.request)
        self.assertEqual(self.agent, ret_agent)

    def test_fail_no_user(self):
        self.request.user = AnonymousUser()
        with self.assertRaises(SalesOpsException):
            crm_views._get_autodialer_agent(self.request)

    def test_fail_no_agent(self):
        with self.assertRaises(SalesOpsException):
            user = AuthUserFactory()
            self.request.user = user
            crm_views._get_autodialer_agent(self.request)


@patch(PACKAGE_NAME + '.julo_services')
class TestPrivateParseAgentAssignmentAutodialerData(TestCase):
    def setUp(self):
        ApplicationFactory.create_batch(10)

    def test_success(self, mock_julo_services):
        agent = AgentFactory()
        application = ApplicationFactory(email='testing@email.com', fullname="Application Name", gender='Wanita')
        lineup = SalesOpsLineupFactory(latest_application_id=application.id)
        agent_assignment = SalesOpsAgentAssignmentFactory(agent_id=agent.id, lineup=lineup)

        mock_julo_services.get_application_skiptrace_phone.return_value = ['phone']
        mock_julo_services.get_promo_code_agent_offer.return_value = None

        ret_val = crm_views._parse_agent_assignment_autodialer_data(agent_assignment, 'subject')

        expected_result = {
            'status': 'success',
            'message': 'Success get Sales Ops Lineup',
            'app_id': lineup.latest_application_id,
            'object_id': agent_assignment.lineup_id,
            'object_name': 'Ibu Application Name',
            'promo_code': {},
            'object_type': 'sales_ops',
            'email': 'testing@email.com',
            'subject': 'subject',
            'telphone': ['phone'],
            'session_delay': 0,
            'account_id': lineup.account_id,
        }
        self.assertEqual(expected_result, ret_val)

    def test_no_skiptrace(self, mock_julo_services):
        agent = AgentFactory()
        application = ApplicationFactory(email='testing@email.com', fullname="Application Name", gender='Wanita')
        lineup = SalesOpsLineupFactory(latest_application_id=application.id)
        agent_assignment = SalesOpsAgentAssignmentFactory(agent_id=agent.id, lineup=lineup)

        mock_julo_services.get_application_skiptrace_phone.return_value = []
        mock_julo_services.get_promo_code_agent_offer.return_value = None

        ret_val = crm_views._parse_agent_assignment_autodialer_data(agent_assignment, 'subject')

        expected_result = {
            'status': 'success',
            'message': 'Success get Sales Ops Lineup',
            'app_id': lineup.latest_application_id,
            'object_id': agent_assignment.lineup_id,
            'object_name': 'Ibu Application Name',
            'promo_code': {},
            'object_type': 'sales_ops',
            'email': 'testing@email.com',
            'subject': 'subject',
            'telphone': [],
            'session_delay': 0,
            'account_id': lineup.account_id,
        }
        self.assertEqual(expected_result, ret_val)


@patch(PACKAGE_NAME + '.autodialer_services.check_autodialer_due_calling_time')
@patch(PACKAGE_NAME + '.sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting')
@patch(PACKAGE_NAME + '.autodialer_services.get_active_assignment')
@patch(PACKAGE_NAME + '.SalesOpsLineup.objects')
@patch(PACKAGE_NAME + '._parse_agent_assignment_autodialer_data')
@patch(PACKAGE_NAME + '.autodialer_services.assign_agent_to_lineup')
@patch(PACKAGE_NAME + '._get_autodialer_agent')
@patch(PACKAGE_NAME + '.autodialer_services.get_sales_ops_autodialer_option')
class TestAjaxGetApplicationAutodialer(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.agent_assignment = SalesOpsAgentAssignmentFactory(agent_id=self.agent.id)
        self.delay_setting = AutodialerDelaySetting(1, 2, 3, 4, 5)

        self.url = reverse('dashboard:ajax_get_application_autodialer')
        data = {'options': 'sales_ops:bucket'}
        self.default_request = self.request_factory.get(self.url, data)
        self.default_request.user = self.user

    def test_success(
            self, mock_get_sales_ops_autodialer_option, mock__get_autodialer_agent,
            mock_assign_agent_to_lineup, mock__parse_agent_assignment_autodialer_data,
            mock_sales_ops_lineup_objects, mock_get_active_assignment, mock_get_autodialer_delay_setting,
            mock_check_due_calling_time,
    ):
        lineups = SalesOpsLineupFactory.create_batch(size=10)

        mock_get_sales_ops_autodialer_option.return_value = None
        mock__get_autodialer_agent.return_value = self.agent
        mock_assign_agent_to_lineup.return_value = self.agent_assignment
        mock_qs = Mock()
        mock_qs.all.return_value = lineups
        mock_sales_ops_lineup_objects.autodialer_default_queue_queryset.return_value = mock_qs
        mock__parse_agent_assignment_autodialer_data.return_value = {'message': 'success'}
        mock_get_active_assignment.return_value = None
        mock_get_autodialer_delay_setting.return_value = self.delay_setting
        mock_check_due_calling_time.return_value = True

        ret_val = crm_views.ajax_get_application_autodialer(self.default_request)

        self.assertIsInstance(ret_val, JsonResponse)
        self.assertEqual({'message': 'success'}, json.loads(ret_val.content))
        mock_get_sales_ops_autodialer_option.assert_called_once_with('sales_ops:bucket')
        mock__get_autodialer_agent.assert_called_once_with(self.default_request)

        mock_assign_agent_to_lineup.assert_called_once_with(self.agent, lineups[0])
        mock_sales_ops_lineup_objects.autodialer_default_queue_queryset.assert_called_once_with(
            self.agent.id, None, exclude_buckets=[BucketCode.GRADUATION], **vars(self.delay_setting)
        )
        mock__parse_agent_assignment_autodialer_data.assert_called_once_with(self.agent_assignment, AutodialerConst.SUBJECT)
        mock_get_autodialer_delay_setting.assert_called_once()

    def test_failed_retry(
            self, mock_get_sales_ops_autodialer_option, mock__get_autodialer_agent,
            mock_assign_agent_to_lineup, mock__parse_agent_assignment_autodialer_data,
            mock_sales_ops_lineup_objects, mock_get_active_assignment, mock_get_autodialer_delay_setting,
            mock_check_due_calling_time,
    ):
        lineups = SalesOpsLineupFactory.create_batch(size=101)

        mock_get_sales_ops_autodialer_option.return_value = None
        mock__get_autodialer_agent.return_value = self.agent
        mock_assign_agent_to_lineup.side_effect = [None] * 100
        mock_qs = Mock()
        mock_qs.all.return_value = lineups
        mock_sales_ops_lineup_objects.autodialer_default_queue_queryset.return_value = mock_qs
        mock_get_active_assignment.return_value = None
        mock_check_due_calling_time.return_value = True

        ret_val = crm_views.ajax_get_application_autodialer(self.default_request)

        self.assertIsInstance(ret_val, JsonResponse)
        self.assertEqual({
            'message': 'Tidak ada Sales Ops Lineup yang tersedia',
            'status': 'failed'
        }, json.loads(ret_val.content))
        mock_assign_agent_to_lineup.assert_has_calls([call(self.agent, lineups[idx]) for idx in range(3)])
        mock__parse_agent_assignment_autodialer_data.assert_not_called()

    def test_success_retry(
            self, mock_get_sales_ops_autodialer_option, mock__get_autodialer_agent,
            mock_assign_agent_to_lineup, mock__parse_agent_assignment_autodialer_data,
            mock_sales_ops_lineup_objects, mock_get_active_assignment, mock_get_autodialer_delay_setting,
            mock_check_due_calling_time,
    ):
        lineups = SalesOpsLineupFactory.create_batch(size=10)

        mock_get_sales_ops_autodialer_option.return_value = None
        mock__get_autodialer_agent.return_value = self.agent
        mock_assign_agent_to_lineup.side_effect = [None, None, self.agent_assignment]
        mock_qs = Mock()
        mock_qs.all.return_value = lineups
        mock_sales_ops_lineup_objects.autodialer_default_queue_queryset.return_value = mock_qs
        mock__parse_agent_assignment_autodialer_data.return_value = {'message': 'success'}
        mock_get_active_assignment.return_value = None
        mock_check_due_calling_time.return_value = True

        ret_val = crm_views.ajax_get_application_autodialer(self.default_request)
        self.assertIsInstance(ret_val, JsonResponse)
        self.assertEqual({'message': 'success'}, json.loads(ret_val.content))
        mock_assign_agent_to_lineup.assert_has_calls([call(self.agent, lineups[idx]) for idx in range(3)])
        mock__parse_agent_assignment_autodialer_data.assert_called_once_with(self.agent_assignment,
                                                                             AutodialerConst.SUBJECT)

    def test_wrong_option(
        self, mock_get_sales_ops_autodialer_option, mock__get_autodialer_agent,
        mock_assign_agent_to_lineup, mock__parse_agent_assignment_autodialer_data,
        mock_sales_ops_lineup_objects, mock_get_active_assignment, mock_get_autodialer_delay_setting,
        mock_check_due_calling_time,
    ):
        mock_get_sales_ops_autodialer_option.return_value = 'wrong-option'
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_active_assignment.return_value = None
        mock_check_due_calling_time.return_value = True

        ret_val = crm_views.ajax_get_application_autodialer(self.default_request)

        self.assertIsInstance(ret_val, JsonResponse)
        self.assertEqual({
            'message': 'Tidak ada Sales Ops Lineup yang tersedia',
            'status': 'failed'
        }, json.loads(ret_val.content))
        mock_assign_agent_to_lineup.assert_not_called()
        mock__parse_agent_assignment_autodialer_data.assert_not_called()

    def test_has_active_assignment(
            self, mock_get_sales_ops_autodialer_option, mock__get_autodialer_agent,
            mock_assign_agent_to_lineup, mock__parse_agent_assignment_autodialer_data,
            mock_sales_ops_lineup_objects, mock_get_active_assignment, mock_get_autodialer_delay_setting,
            mock_check_due_calling_time,
    ):
        mock_get_sales_ops_autodialer_option.return_value = None
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_active_assignment.return_value = self.agent_assignment
        mock__parse_agent_assignment_autodialer_data.return_value = {'message': 'success'}
        mock_check_due_calling_time.return_value = True

        ret_val = crm_views.ajax_get_application_autodialer(self.default_request)

        self.assertIsInstance(ret_val, JsonResponse)
        self.assertEqual({'message': 'success'}, json.loads(ret_val.content))
        mock_sales_ops_lineup_objects.autodialer_default_queue_queryset.assert_not_called()
        mock_assign_agent_to_lineup.assert_not_called()
        mock__parse_agent_assignment_autodialer_data.assert_called_once_with(self.agent_assignment,
                                                                             AutodialerConst.SUBJECT)


@patch(PACKAGE_NAME + '.autodialer_services.stop_autodialer_session')
@patch(PACKAGE_NAME + '.autodialer_services.create_autodialer_activity')
@patch(PACKAGE_NAME + '.julo_services')
@patch(PACKAGE_NAME + '.autodialer_services.get_or_create_autodialer_session')
@patch(PACKAGE_NAME + '.autodialer_services.get_agent_assignment')
@patch(PACKAGE_NAME + '._get_autodialer_agent')
class TestAjaxAutodialerSessionStatus(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.lineup = SalesOpsLineupFactory()
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            agent_id=self.agent.id, lineup=self.lineup
        )
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        self.autodialer_activity = SalesOpsAutodialerActivityFactory(
            autodialer_session_id=self.autodialer_session.id
        )
        self.rpc_skiptrace_result = SkiptraceResultChoiceFactory(weight=1)
        self.non_rpc_skiptrace_result = SkiptraceResultChoiceFactory(weight=-1)
        self.url = reverse('dashboard:ajax_autodialer_session_status')

    def test_session_start(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                           mock_get_or_create_autodialer_session, mock_julo_services,
                           mock_create_autodialer_activity, mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity

        post_data = {
            'session_start': '1',
            'object_id': str(self.lineup.id),
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        with self.assertNumQueries(0):
            ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'], ret_json)
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Session', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_julo_services.get_skiptrace_result_choice.assert_not_called()
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(
                self.autodialer_session, self.agent_assignment, AutodialerConst.SESSION_START,
                phone_number=None, skiptrace_result_choice_id=None
        )

    def test_session_stop(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                          mock_get_or_create_autodialer_session, mock_julo_services, mock_create_autodialer_activity,
                          mock_stop_autodialer_session):

        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity

        post_data = {
            'session_stop': '1',
            'object_id': str(self.lineup.id)
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'], ret_json)
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Session', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_julo_services.get_skiptrace_result_choice.assert_not_called()
        mock_stop_autodialer_session.assert_called_once_with(self.autodialer_session, self.agent_assignment)
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(
                self.autodialer_session, self.agent_assignment, AutodialerConst.SESSION_STOP,
                phone_number=None, skiptrace_result_choice_id=None
        )

    def test_rpc(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                 mock_get_or_create_autodialer_session, mock_julo_services, mock_create_autodialer_activity,
                 mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity
        mock_julo_services.get_skiptrace_result_choice.return_value = self.rpc_skiptrace_result

        post_data = {
            'object_id': str(self.lineup.id),
            'is_failed': '1',
            'hashtag': '1',
            'call_result': '6',
            'phone_number': 'phone-number',
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'])
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Session', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_julo_services.get_skiptrace_result_choice.assert_called_once_with(6)
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(
                self.autodialer_session, self.agent_assignment, AutodialerConst.SESSION_ACTION_SUCCESS,
                phone_number='phone-number', skiptrace_result_choice_id=self.rpc_skiptrace_result.id
        )

    def test_non_rpc(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                     mock_get_or_create_autodialer_session, mock_julo_services, mock_create_autodialer_activity,
                     mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity
        mock_julo_services.get_skiptrace_result_choice.return_value = self.non_rpc_skiptrace_result

        post_data = {
            'object_id': str(self.lineup.id),
            'is_failed': '1',
            'hashtag': '1',
            'call_result': '4',
            'phone_number': 'phone-number',
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'], ret_json)
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Session', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_julo_services.get_skiptrace_result_choice.assert_called_once_with(4)
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(
                self.autodialer_session, self.agent_assignment, AutodialerConst.SESSION_ACTION_FAIL,
                phone_number='phone-number', skiptrace_result_choice_id=self.non_rpc_skiptrace_result.id
        )

    def test_invalid_call_result(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                                 mock_get_or_create_autodialer_session, mock_julo_services,
                                 mock_create_autodialer_activity, mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity
        mock_julo_services.get_skiptrace_result_choice.return_value = None

        post_data = {
            'object_id': str(self.lineup.id),
            'is_failed': '1',
            'hashtag': '1',
            'call_result': '4',
            'phone_number': 'phone-number',
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('failed', ret_json['status'])
        self.assertEqual('Call action "4" tidak valid.', ret_json['message'])

        mock_julo_services.get_skiptrace_result_choice.assert_called_once_with(4)
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_not_called()

    def test_no_call_result_and_status(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                                       mock_get_or_create_autodialer_session, mock_julo_services,
                                       mock_create_autodialer_activity, mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_get_or_create_autodialer_session.return_value = self.autodialer_session
        mock_create_autodialer_activity.return_value = self.autodialer_activity
        mock_julo_services.get_skiptrace_result_choice.return_value = None

        post_data = {
            'object_id': str(self.lineup.id),
            'phone_number': 'phone-number',
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'])
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Session', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_julo_services.get_skiptrace_result_choice.assert_not_called()
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_called_once_with(self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(
                self.autodialer_session, self.agent_assignment, AutodialerConst.SESSION_ACTION,
                phone_number='phone-number', skiptrace_result_choice_id=None
        )

    def test_no_agent_assignment(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                                 mock_get_or_create_autodialer_session, mock_julo_services,
                                 mock_create_autodialer_activity, mock_stop_autodialer_session):
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = None
        mock_create_autodialer_activity.return_value = self.autodialer_activity
        mock_julo_services.get_skiptrace_result_choice.return_value = None

        post_data = {
            'object_id': str(self.lineup.id),
            'session_start': '1',
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_session_status(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('failed', ret_json['status'])
        self.assertEqual(f'Anda belum di-assign ke Lineup ini. {self.lineup.id}', ret_json['message'])

        mock_julo_services.get_skiptrace_result_choice.assert_not_called()
        mock_stop_autodialer_session.assert_not_called()
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_get_or_create_autodialer_session.assert_not_called()
        mock_create_autodialer_activity.assert_not_called()


@patch(PACKAGE_NAME + '.autodialer_services.create_autodialer_activity')
@patch(PACKAGE_NAME + '.autodialer_services.get_autodialer_session')
@patch(PACKAGE_NAME + '.autodialer_services.get_agent_assignment')
@patch(PACKAGE_NAME + '._get_autodialer_agent')
class TestAjaxAutodialerHistoryRecord(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.lineup = SalesOpsLineupFactory()
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            agent_id=self.agent.id, lineup=self.lineup
        )
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        self.autodialer_activity = SalesOpsAutodialerActivityFactory(
            autodialer_session_id=self.autodialer_session.id
        )
        self.url = reverse('dashboard:ajax_autodialer_history_record')

    def test_success_ideal(self, mock__get_autodialer_agent, mock_get_agent_assignment, mock_get_autodialer_session,
                           mock_create_autodialer_activity):
        mock_get_autodialer_session.return_value = self.autodialer_session
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_create_autodialer_activity.return_value = self.autodialer_activity

        post_data = {
            'object_id': str(self.lineup.id),
            'action': 'this button is clicked'
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_history_record(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'])
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Activity', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])

        mock_get_autodialer_session.assert_called_once_with(self.lineup.id)
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(self.autodialer_session, self.agent_assignment,
                'this button is clicked')

    def test_no_action(self, mock__get_autodialer_agent, mock_get_agent_assignment, mock_get_autodialer_session,
                       mock_create_autodialer_activity):
        mock_get_autodialer_session.return_value = self.autodialer_session
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = self.agent_assignment
        mock_create_autodialer_activity.return_value = self.autodialer_activity

        post_data = {
            'object_id': str(self.lineup.id),
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_history_record(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('success', ret_json['status'])
        self.assertEqual('Berhasil rekam Sales Ops Autodialer Activity', ret_json['message'])
        self.assertEqual(model_to_dict(self.autodialer_activity), ret_json['activity'])
        mock_get_autodialer_session.assert_called_once_with(self.lineup.id)
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_create_autodialer_activity.assert_called_once_with(self.autodialer_session, self.agent_assignment,
                AutodialerConst.ACTION_UNKNOWN)

    def test_no_autodialer_session(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                                   mock_get_autodialer_session, mock_create_autodialer_activity):
        mock_get_autodialer_session.return_value = None

        post_data = {
            'object_id': str(self.lineup.id),
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_history_record(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('failed', ret_json['status'])
        self.assertEqual(f'Sales Ops session is not found for lineup "{self.lineup.id}"', ret_json['message'])
        mock_get_autodialer_session.assert_called_once_with(self.lineup.id)
        mock__get_autodialer_agent.assert_not_called()
        mock_get_agent_assignment.assert_not_called()
        mock_create_autodialer_activity.assert_not_called()

    def test_no_agent_assignment(self, mock__get_autodialer_agent, mock_get_agent_assignment,
                                 mock_get_autodialer_session, mock_create_autodialer_activity):
        mock_get_autodialer_session.return_value = self.autodialer_session
        mock__get_autodialer_agent.return_value = self.agent
        mock_get_agent_assignment.return_value = None

        post_data = {
            'object_id': str(self.lineup.id),
        }
        request = self.request_factory.post(self.url, post_data)
        request.user = self.user
        ret_val = crm_views.ajax_autodialer_history_record(request)
        ret_json = json.loads(ret_val.content)

        self.assertEqual('failed', ret_json['status'])
        self.assertEqual(f'Anda belum di-assign ke Lineup ini. {self.lineup.id}', ret_json['message'])
        mock_get_autodialer_session.assert_called_once_with(self.lineup.id)
        mock__get_autodialer_agent.assert_called_once_with(request)
        mock_get_agent_assignment.assert_called_once_with(self.agent, self.lineup.id)
        mock_create_autodialer_activity.assert_not_called()


class TestAjaxSkiptraceSalesOps(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.agent = AgentFactory(user=self.user)
        self.application = ApplicationFactory()
        self.lineup = SalesOpsLineupFactory(latest_application_id=self.application.id)
        self.call_result = SkiptraceResultChoiceFactory(name="RPC")

    def test_add_skiptrace(self):
        url = reverse('sales_ops.crm:add_skiptrace')
        data = {
            'application': self.application.id,
            'contact_name': 'Test name',
            'contact_source': 'Sale Ops - CRM',
            'phone_number': '086672309419',
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)
        skiptrace = Skiptrace.objects.filter(application=self.application).last()
        self.assertEqual(skiptrace.phone_number.national_number, 86672309419)

    def test_update_skiptrace(self):
        skiptrace = SkiptraceFactory(application=self.application)
        url = reverse('sales_ops.crm:update_skiptrace')
        data = {
            'skiptrace_id': skiptrace.id,
            'application': self.application.id,
            'contact_name': 'Test name',
            'contact_source': 'Sale Ops - CRM',
            'phone_number': '086672309420',
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)
        skiptrace = Skiptrace.objects.filter(application=self.application).last()
        self.assertEqual(skiptrace.phone_number.national_number, 86672309420)

    def test_skiptrace_history(self):
        skiptrace = SkiptraceFactory(application=self.application)
        url = reverse('sales_ops.crm:skiptrace_history')
        data = {
            'lineup_id': self.lineup.id,
            'skiptrace_id': skiptrace.id,
            'skiptrace_result_id': -1,
            'notes': 'test notes'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 400)  # serializers invalid

        data['skiptrace_result_id'] = self.call_result.id
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)

    def test_skiptrace_history_double_rpc(self):
        skiptrace = SkiptraceFactory(application=self.application)
        url = reverse('sales_ops.crm:skiptrace_history')
        data = {
            'lineup_id': self.lineup.id,
            'skiptrace_id': skiptrace.id,
            'skiptrace_result_id': self.call_result.id,
            'notes': 'test notes',
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Lineup sudah RPC atau sedang di-call', str(response.content))

    def test_skiptrace_history_non_rpc_then_rpc(self):
        skiptrace = SkiptraceFactory(application=self.application)
        url = reverse('sales_ops.crm:skiptrace_history')
        data = {
            'lineup_id': self.lineup.id,
            'skiptrace_id': skiptrace.id,
            'skiptrace_result_id': (SkiptraceResultChoiceFactory(name="Non-RPC", weight=-1)).id,
            'notes': 'test notes',
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)

        data['skiptrace_result_id'] = self.call_result.id
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)


class TestSalesOpsBlockFeature(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.agent = AgentFactory(user=self.user)
        self.lineup = SalesOpsLineupFactory(
            is_active=True,
        )

    def test_ajax_block(self):
        url = reverse(f'sales_ops.crm:ajax-block', kwargs={'lineup_id': self.lineup.id})

        data = {}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 400)

        data = {
            'days': 90,
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)
        self.lineup.refresh_from_db()
        self.assertEqual(self.lineup.is_active, False)


class TestVendorRPCCreateView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group.objects.create(name=SalesOpsRoles.SALES_OPS)
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.url = reverse('sales_ops.crm:vendor_rpc')

    def gen_upload_file(self):
        csv_data = [
            ['account_id', 'vendor_id', 'agent_id', 'completed_date', 'is_rpc', 'bucket_code'],
            ['12', '22', '33', '4/7/2023 13:45:9', 'true', 'bucket_a'],
            ['1112', '45622', '657833', '14/7/2023 3:4:9', 'False', 'bucket_b']
        ]
        with open('vendor_rpc.csv', 'w') as file:
            writter = csv.writer(file, delimiter=',')
            writter.writerows(csv_data)
        req_file = open('vendor_rpc.csv', 'rb')
        data = SimpleUploadedFile(
            content=req_file.read(), name='vendor_rpc.csv', content_type='application/csv'
        )
        return {
            'csv_file': data
        }

    @patch('juloserver.sales_ops.views.crm_views.save_vendor_rpc_csv')
    @patch('juloserver.sales_ops.views.crm_views.check_vendor_rpc_csv_format')
    def test_message_vendor_rpc(self, mock_checking, mock_store_csv):
        post_data = {
            'csv_file': SimpleUploadedFile(
                content=None, name='vendor_rpc.csv', content_type='application/csv'
            )
        }
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'CSV file is empty')

        post_data = self.gen_upload_file()
        mock_checking.side_effect = sales_ops_exc.MissingCSVHeaderException()
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Headers in file does not match with setting')

        post_data = self.gen_upload_file()
        mock_checking.side_effect = sales_ops_exc.MissingFeatureSettingVendorRPCException()
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Missing setting vendor RPC')

        post_data = self.gen_upload_file()
        mock_checking.side_effect = sales_ops_exc.InvalidBooleanValueException()
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Invalid boolean values')

        post_data = self.gen_upload_file()
        mock_checking.side_effect = sales_ops_exc.InvalidDatetimeValueException()
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Invalid date time values')

        post_data = self.gen_upload_file()
        mock_checking.side_effect = sales_ops_exc.InvalidDigitValueException()
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Invalid digit values')

        post_data = self.gen_upload_file()
        mock_checking.return_value = True
        mock_checking.side_effect = None
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Agent not found')

        post_data = self.gen_upload_file()
        AgentFactory(user=self.user)
        response = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        mess = response.context[0].get('messages')._loaded_data[0].message
        self.assertEquals(mess, 'Upload csv successfully')
        mock_store_csv.assert_called_once()
