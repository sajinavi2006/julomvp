import json
from datetime import timedelta, datetime
from unittest.mock import patch, Mock, call

from django.db import (
    OperationalError,
)
from django.forms import model_to_dict
from django.http import JsonResponse
from django.test import TestCase
from django.utils import timezone

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.collection_vendor.tests.factories import SkiptraceResultChoiceFactory
from juloserver.julo.tests.factories import AuthUserFactory, ApplicationFactory, FeatureSettingFactory
from juloserver.sales_ops.constants import AutodialerConst
from juloserver.sales_ops.exceptions import NotValidSalesOpsAutodialerOption, SalesOpsException
from juloserver.sales_ops.models import (
    SalesOpsAgentAssignment,
    SalesOpsAutodialerSession,
    SalesOpsAutodialerActivity,
    SalesOpsLineup,
)
from juloserver.sales_ops.services import autodialer_services
from juloserver.sales_ops.services.autodialer_services import AutodialerDelaySetting
from juloserver.sales_ops.tests.factories import (
    SalesOpsAgentAssignmentFactory,
    SalesOpsLineupFactory,
    SalesOpsAutodialerSessionFactory,
    SalesOpsAutodialerActivityFactory,
)
from juloserver.loan.constants import TimeZoneName

PACKAGE_NAME = 'juloserver.sales_ops.services.autodialer_services'


class TestIsSalesOpsAutodialerOption(TestCase):
    def test_success(self):
        test_values = [
            'sales_ops:bucket',
            'sales_ops:',
            'sales_ops',
            'sales_ops:bucket:',
            'sales_ops:bucket:next',
        ]
        for test_value in test_values:
            ret_val = autodialer_services.is_sales_ops_autodialer_option(test_value)
            self.assertTrue(ret_val, test_value)

    def test_false(self):
        test_values = [
            'sales_ops.bucket',
            '141',
            '111.j1',
            '1000141',
            '',
            None,
            141,
        ]
        for test_value in test_values:
            ret_val = autodialer_services.is_sales_ops_autodialer_option(test_value)
            self.assertFalse(ret_val, test_value)


class TestGetSalesOpsAutodialerOption(TestCase):
    @patch(PACKAGE_NAME + '.is_sales_ops_autodialer_option')
    def test_success(self, mock_is_sales_ops_autodialer_option):
        test_data = [
            ('sales_ops:bucket', 'bucket'),
            ('sales_ops:', None),
            ('sales_ops', None),
            ('sales_ops:bucket:', 'bucket'),
            ('sales_ops:bucket:next', 'bucket'),
        ]
        mock_is_sales_ops_autodialer_option.return_value = True
        for test_value, expected in test_data:
            ret_val = autodialer_services.get_sales_ops_autodialer_option(test_value)
            self.assertEqual(expected, ret_val, test_value)

    @patch(PACKAGE_NAME + '.is_sales_ops_autodialer_option')
    def test_failed(self, mock_is_sales_ops_autodialer_option):
        mock_is_sales_ops_autodialer_option.return_value = False
        with self.assertRaises(NotValidSalesOpsAutodialerOption):
            autodialer_services.get_sales_ops_autodialer_option('not-valid')


class TestAssignAgentToLineup(TestCase):
    def test_success(self):
        lineup = SalesOpsLineupFactory()
        user = AuthUserFactory(username='username')
        agent = AgentFactory(user=user)

        ret_val = autodialer_services.assign_agent_to_lineup(agent, lineup)

        expected_obj = SalesOpsAgentAssignment.objects.filter(
            lineup_id=lineup.id, agent_id=agent.id
        ).get()
        self.assertEqual(expected_obj, ret_val)
        self.assertEqual('username', ret_val.agent_name)

    def test_is_active(self):
        lineup = SalesOpsLineupFactory()
        agent = AgentFactory()
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=lineup, agent_id=agent.id, is_active=True
        )
        lineup.update_safely(latest_agent_assignment_id=agent_assignment.id)

        ret_val = autodialer_services.assign_agent_to_lineup(agent, lineup)

        self.assertIsNone(ret_val)

    @patch(PACKAGE_NAME + '.SalesOpsLineup.objects.select_for_update')
    def test_nowait(self, mock_select_for_update):
        lineup = SalesOpsLineupFactory()
        agent = AgentFactory()

        mock_select_for_update.side_effect = OperationalError()

        ret_val = autodialer_services.assign_agent_to_lineup(agent, lineup)

        self.assertIsNone(ret_val)
        mock_select_for_update.assert_called_once_with(nowait=True)


class TestGetActiveAssignment(TestCase):
    def test_success(self):
        agent = AgentFactory()
        SalesOpsAgentAssignmentFactory.create_batch(5)
        assignments = SalesOpsAgentAssignmentFactory.create_batch(
            3, agent_id=agent.id, is_active=True
        )

        ret_val = autodialer_services.get_active_assignment(agent)

        self.assertEqual(assignments[2], ret_val)

    def test_not_assignment(self):
        agent = AgentFactory()
        SalesOpsAgentAssignmentFactory.create_batch(5)

        ret_val = autodialer_services.get_active_assignment(agent)

        self.assertIsNone(ret_val)


class TestGetAutodialerSession(TestCase):
    def test_success(self):
        lineup = SalesOpsLineupFactory()
        SalesOpsAutodialerSessionFactory.create_batch(2)
        autodialer_session = SalesOpsAutodialerSessionFactory(lineup=lineup)

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_autodialer_session(lineup.id)

        self.assertEqual(autodialer_session, ret_val)

    def test_not_found(self):
        lineup = SalesOpsLineupFactory()
        SalesOpsAutodialerSessionFactory.create_batch(2)

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_autodialer_session(lineup.id)

        self.assertIsNone(ret_val)


class TestGetOrCreateAutodialerSession(TestCase):
    @patch(PACKAGE_NAME + '.get_autodialer_session')
    def test_get(self, mock_get_autodialer_session):
        lineup = SalesOpsLineupFactory()
        autodialer_session = SalesOpsAutodialerSessionFactory(lineup=lineup)
        mock_get_autodialer_session.return_value = autodialer_session

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_or_create_autodialer_session(lineup.id)

        self.assertEqual(autodialer_session, ret_val)
        mock_get_autodialer_session.assert_called_once_with(lineup.id)

    @patch(PACKAGE_NAME + '.get_autodialer_session')
    def test_create(self, mock_get_autodialer_session):
        lineup = SalesOpsLineupFactory()
        mock_get_autodialer_session.return_value = None

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_or_create_autodialer_session(lineup_id=lineup.id)

        self.assertIsInstance(ret_val, SalesOpsAutodialerSession)
        self.assertEqual(lineup.id, ret_val.lineup_id)
        self.assertEqual(1, SalesOpsAutodialerSession.objects.filter(lineup_id=lineup.id).count())

    @patch(PACKAGE_NAME + '.get_autodialer_session')
    def test_create_with_kwargs(self, mock_get_autodialer_session):
        lineup = SalesOpsLineupFactory()
        mock_get_autodialer_session.return_value = None

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_or_create_autodialer_session(lineup_id=lineup.id, total_count=10)

        self.assertEqual(10, ret_val.total_count)
        self.assertEqual(1, SalesOpsAutodialerSession.objects.filter(lineup_id=lineup.id, total_count=10).count())


class TestGetAgentAssignment(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.lineup = SalesOpsLineupFactory()

    def test_success(self):
        agent_assignment = SalesOpsAgentAssignmentFactory(
            is_active=True, lineup_id=self.lineup.id, agent_id=self.agent.id
        )
        SalesOpsAgentAssignmentFactory.create_batch(
            3, is_active=False, lineup_id=self.lineup.id, agent_id=self.agent.id
        )
        SalesOpsAgentAssignmentFactory.create_batch(3, is_active=True, lineup_id=self.lineup.id)
        SalesOpsAgentAssignmentFactory.create_batch(3, is_active=True, agent_id=self.agent.id)

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_agent_assignment(self.agent, self.lineup.id)
        self.assertEqual(agent_assignment, ret_val)

    def test_not_found(self):
        SalesOpsAgentAssignmentFactory.create_batch(
            3, is_active=False, lineup=self.lineup, agent_id=self.agent.id
        )
        SalesOpsAgentAssignmentFactory.create_batch(3, is_active=True, lineup_id=self.lineup.id)
        SalesOpsAgentAssignmentFactory.create_batch(3, is_active=True, agent_id=self.agent.id)

        with self.assertNumQueries(0):
            ret_val = autodialer_services.get_agent_assignment(self.agent, self.lineup.id)
        self.assertIsNone(ret_val)


class TestCreateAutodialerActivity(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.lineup = SalesOpsLineupFactory()
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            agent_id=self.agent.id, lineup=self.lineup
        )

    def test_create(self):
        ret_val = autodialer_services.create_autodialer_activity(self.autodialer_session, self.agent_assignment,
                                                                    'action')

        self.assertIsInstance(ret_val, SalesOpsAutodialerActivity)
        filter_kwargs = {
            'autodialer_session_id': self.autodialer_session.id,
            'agent_id': self.agent.id,
            'action': 'action',
        }
        self.assertEqual(1, SalesOpsAutodialerActivity.objects.filter(**filter_kwargs).count())

    def test_create_with_kwargs(self):
        ret_val = autodialer_services.create_autodialer_activity(self.autodialer_session, self.agent_assignment,
                                                                    'action', phone_number='phone')

        filter_kwargs = {
            'autodialer_session_id': self.autodialer_session.id,
            'agent_id': self.agent.id,
            'action': 'action',
            'phone_number': 'phone',
        }
        self.assertEqual(1, SalesOpsAutodialerActivity.objects.filter(**filter_kwargs).count())


class TestGenerateAutodialerNextTs(TestCase):
    @patch(PACKAGE_NAME + '.sales_ops_services.SalesOpsSetting')
    @patch(PACKAGE_NAME + '.timezone.localtime')
    def test_is_rpc(self, mock_localtime, mock_sales_ops_setting):
        now = timezone.now()
        mock_localtime.return_value = now
        delay_setting = AutodialerDelaySetting(rpc_delay_hour=1)
        agent_assignment = SalesOpsAgentAssignmentFactory(is_rpc=True)
        mock_sales_ops_setting.get_autodialer_delay_setting.return_value = delay_setting

        ret_val = autodialer_services.generate_autodialer_next_ts(agent_assignment)

        expect_time = now + timedelta(hours=1)
        self.assertEqual(expect_time, ret_val)

    @patch(PACKAGE_NAME + '.sales_ops_services.SalesOpsSetting')
    @patch(PACKAGE_NAME + '.timezone.localtime')
    def test_non_rpc(self, mock_localtime, mock_sales_ops_setting):
        now = timezone.now()
        mock_localtime.return_value = now
        delay_setting = AutodialerDelaySetting(
                rpc_delay_hour=9, non_rpc_delay_hour=1, non_rpc_final_delay_hour=2, non_rpc_final_attempt_count=3
        )
        agent_assignment = SalesOpsAgentAssignmentFactory(is_rpc=False, non_rpc_attempt=1)
        mock_sales_ops_setting.get_autodialer_delay_setting.return_value = delay_setting

        ret_val = autodialer_services.generate_autodialer_next_ts(agent_assignment)

        expect_time = now + timedelta(hours=1)
        self.assertEqual(expect_time, ret_val)

    @patch(PACKAGE_NAME + '.sales_ops_services.SalesOpsSetting')
    @patch(PACKAGE_NAME + '.timezone.localtime')
    def test_non_rpc_max(self, mock_localtime, mock_sales_ops_setting):
        now = timezone.now()
        mock_localtime.return_value = now
        delay_setting = AutodialerDelaySetting(
                rpc_delay_hour=9, non_rpc_delay_hour=1, non_rpc_final_delay_hour=2, non_rpc_final_attempt_count=3
        )
        agent_assignment = SalesOpsAgentAssignmentFactory(is_rpc=False, non_rpc_attempt=3)
        mock_sales_ops_setting.get_autodialer_delay_setting.return_value = delay_setting

        ret_val = autodialer_services.generate_autodialer_next_ts(agent_assignment)

        expect_time = now + timedelta(hours=2)
        self.assertEqual(expect_time, ret_val)


@patch(PACKAGE_NAME + '.send_event_moengage_for_rpc_sales_ops')
@patch(PACKAGE_NAME + '.timezone.localtime')
@patch(PACKAGE_NAME + '.generate_autodialer_next_ts')
@patch(PACKAGE_NAME + '.SalesOpsAgentAssignment.objects.get_previous_assignment')
@patch(PACKAGE_NAME + '.SalesOpsAutodialerActivity.objects.get_latest_activity')
class TestStopAutodialerSession(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.lineup = SalesOpsLineupFactory()

    def test_success_ideal(self, mock_get_latest_activity, mock_get_previous_assignment,
                           mock_generate_autodialer_next_ts, mock_localtime, mock_sent_moengage):
        mock_localtime.return_value = self.now
        mock_is_success = Mock()
        mock_is_success.return_value = True
        latest_autodialer_activity = SalesOpsAutodialerActivityFactory()
        latest_autodialer_activity.is_success = mock_is_success
        mock_get_latest_activity.return_value = latest_autodialer_activity
        mock_get_previous_assignment.return_value = None
        mock_generate_autodialer_next_ts.return_value = self.now + timedelta(hours=10)

        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.lineup.id, is_active=True, non_rpc_attempt=2
        )
        autodialer_session = SalesOpsAutodialerSessionFactory(total_count=1, lineup=self.lineup)

        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)
        ret_agent_assignment = SalesOpsAgentAssignment.objects.get(id=agent_assignment.id)
        ret_lineup = SalesOpsLineup.objects.get(id=self.lineup.id)
        ret_autodialer_session = SalesOpsAutodialerSession.objects.get(id=autodialer_session.id)

        # Check agent_assignment data
        self.assertEqual(self.now, ret_agent_assignment.completed_date)
        self.assertFalse(ret_agent_assignment.is_active)
        self.assertEqual(0, ret_agent_assignment.non_rpc_attempt)
        self.assertTrue(ret_agent_assignment.is_rpc)

        # Check lineup data
        self.assertEqual(ret_agent_assignment.id, ret_lineup.latest_agent_assignment_id)
        self.assertEqual(ret_agent_assignment.id, ret_lineup.latest_rpc_agent_assignment_id)

        # Check autodialer session
        self.assertEqual(2, ret_autodialer_session.total_count)
        self.assertEqual(self.now + timedelta(hours=10), ret_autodialer_session.next_session_ts)

        # Check mock called
        mock_generate_autodialer_next_ts.assert_called_once_with(ret_agent_assignment)
        mock_get_latest_activity.assert_called_once_with(autodialer_session.id, agent_assignment.id)
        mock_get_previous_assignment.assert_called_once_with(agent_assignment)

    def test_session_success_with_previous_assignment(self, mock_get_latest_activity, mock_get_previous_assignment,
                                              mock_generate_autodialer_next_ts, mock_localtime, mock_sent_moengage):
        mock_localtime.return_value = self.now
        mock_is_success = Mock()
        mock_is_success.return_value = True
        latest_autodialer_activity = SalesOpsAutodialerActivityFactory()
        latest_autodialer_activity.is_success = mock_is_success
        mock_get_latest_activity.return_value = latest_autodialer_activity
        mock_get_previous_assignment.return_value = SalesOpsAgentAssignmentFactory(non_rpc_attempt=10)
        mock_generate_autodialer_next_ts.return_value = self.now + timedelta(hours=10)

        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.lineup.id, is_active=True, non_rpc_attempt=2
        )
        autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)

        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)
        ret_agent_assignment = SalesOpsAgentAssignment.objects.get(id=agent_assignment.id)

        self.assertFalse(ret_agent_assignment.is_active)
        self.assertEqual(0, ret_agent_assignment.non_rpc_attempt)
        self.assertTrue(ret_agent_assignment.is_rpc)

    def test_session_failed_ideal(self, mock_get_latest_activity, mock_get_previous_assignment,
                                  mock_generate_autodialer_next_ts, mock_localtime, mock_sent_moengage):
        mock_localtime.return_value = self.now
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=self.lineup, is_active=True, non_rpc_attempt=0)
        latest_autodialer_activity = SalesOpsAutodialerActivityFactory(
            agent_assignment_id=agent_assignment.id,
            action=AutodialerConst.SESSION_ACTION_FAIL
        )
        mock_get_latest_activity.return_value = latest_autodialer_activity
        mock_get_previous_assignment.return_value = None
        mock_generate_autodialer_next_ts.return_value = self.now + timedelta(hours=10)

        autodialer_session = SalesOpsAutodialerSessionFactory(
            failed_count=2, total_count=1, lineup=self.lineup)

        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)
        ret_agent_assignment = SalesOpsAgentAssignment.objects.get(id=agent_assignment.id)
        ret_lineup = SalesOpsLineup.objects.get(id=self.lineup.id)
        ret_autodialer_session = SalesOpsAutodialerSession.objects.get(id=autodialer_session.id)

        # Check agent_assignment data
        self.assertEqual(self.now, ret_agent_assignment.completed_date)
        self.assertFalse(ret_agent_assignment.is_active)
        self.assertEqual(1, ret_agent_assignment.non_rpc_attempt)
        self.assertFalse(ret_agent_assignment.is_rpc)

        # Check lineup data
        self.assertEqual(ret_agent_assignment.id, ret_lineup.latest_agent_assignment_id)

        # Check autodialer session
        self.assertEqual(3, ret_autodialer_session.failed_count)
        self.assertEqual(2, ret_autodialer_session.total_count)
        self.assertEqual(self.now + timedelta(hours=10), ret_autodialer_session.next_session_ts)

        # Check mock called
        mock_generate_autodialer_next_ts.assert_called_once_with(ret_agent_assignment)
        mock_get_latest_activity.assert_called_once_with(autodialer_session.id, agent_assignment.id)
        mock_get_previous_assignment.assert_called_once_with(agent_assignment)

    def test_session_failed_with_previous_assignment(
        self, mock_get_latest_activity, mock_get_previous_assignment,
        mock_generate_autodialer_next_ts, mock_localtime, mock_sent_moengage
    ):
        mock_localtime.return_value = self.now
        mock_is_success = Mock()
        mock_is_success.return_value = False
        latest_autodialer_activity = SalesOpsAutodialerActivityFactory()
        latest_autodialer_activity.is_success = mock_is_success
        mock_get_latest_activity.return_value = latest_autodialer_activity
        mock_get_previous_assignment.return_value = SalesOpsAgentAssignmentFactory(non_rpc_attempt=10)
        mock_generate_autodialer_next_ts.return_value = self.now + timedelta(hours=10)

        agent_assignment = SalesOpsAgentAssignmentFactory(lineup=self.lineup, is_active=True, non_rpc_attempt=0)
        autodialer_session = SalesOpsAutodialerSessionFactory(failed_count=2, total_count=1, lineup=self.lineup)

        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)
        ret_agent_assignment = SalesOpsAgentAssignment.objects.get(id=agent_assignment.id)

        # Check agent_assignment data
        self.assertFalse(ret_agent_assignment.is_active)
        self.assertEqual(11, ret_agent_assignment.non_rpc_attempt)
        self.assertFalse(ret_agent_assignment.is_rpc)

    def test_no_latest_activity(self, mock_get_latest_activity, mock_get_previous_assignment,
                                mock_generate_autodialer_next_ts, mock_localtime, mock_sent_moengage):
        mock_localtime.return_value = self.now
        prev_agent_assignment = SalesOpsAgentAssignmentFactory(lineup=self.lineup, is_active=False)
        mock_get_latest_activity.return_value = None
        mock_get_previous_assignment.return_value = prev_agent_assignment
        mock_generate_autodialer_next_ts.return_value = self.now + timedelta(hours=10)

        agent_assignment = SalesOpsAgentAssignmentFactory(lineup=self.lineup, is_active=True, non_rpc_attempt=0)
        autodialer_session = SalesOpsAutodialerSessionFactory(failed_count=2, total_count=1, lineup=self.lineup)

        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)
        ret_agent_assignment = SalesOpsAgentAssignment.objects.get(id=agent_assignment.id)
        ret_lineup = SalesOpsLineup.objects.get(id=self.lineup.id)
        ret_autodialer_session = SalesOpsAutodialerSession.objects.get(id=autodialer_session.id)

        # Check agent_assignment data
        self.assertIsNone(ret_agent_assignment.completed_date)
        self.assertFalse(ret_agent_assignment.is_active)
        self.assertEqual(0, ret_agent_assignment.non_rpc_attempt)
        self.assertIsNone(ret_agent_assignment.is_rpc)

        # Check lineup data
        self.assertEqual(prev_agent_assignment.id, ret_lineup.latest_agent_assignment_id)

        # Check autodialer session
        self.assertEqual(2, ret_autodialer_session.failed_count)
        self.assertEqual(1, ret_autodialer_session.total_count)
        self.assertEqual(self.now + timedelta(hours=10), ret_autodialer_session.next_session_ts)

        # Check mock called
        mock_generate_autodialer_next_ts.assert_called_once_with(ret_agent_assignment)
        mock_get_latest_activity.assert_called_once_with(autodialer_session.id, agent_assignment.id)
        mock_get_previous_assignment.assert_called_once_with(agent_assignment)


class TestAutoDialerDueCallingTime(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.agent = AgentFactory()
        self.lineup = SalesOpsLineupFactory(latest_application_id=self.application.id)
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name='sales_ops',
            parameters={'autodial_end_call_hour': 18},
        )

    def test_get_timezone_and_queue_name(self):
        wit_postcode = 98787
        timezone = autodialer_services.get_customer_timezone(wit_postcode)
        self.assertEqual(timezone, TimeZoneName.WIT)

        wita_postcode = 75641
        timezone = autodialer_services.get_customer_timezone(wita_postcode)
        self.assertEqual(timezone, TimeZoneName.WITA)

        wib_postcode = 24104
        timezone = autodialer_services.get_customer_timezone(wib_postcode)
        self.assertEqual(timezone, TimeZoneName.WIB)

        # default
        postcode = None
        timezone = autodialer_services.get_customer_timezone(postcode)
        self.assertEqual(timezone, TimeZoneName.WIT)

    @patch.object(timezone, 'now')
    def test_check_autodialer_due_calling_time_1(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 29, 15, 25, 40)

        # 15:25:40 WIB -> 17:25:40 WIT
        self.application.update_safely(address_kodepos='98787')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 15:25:40 WIB -> 16:25:40 WITA
        self.application.update_safely(address_kodepos='75641')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 15:25:40 WIB
        self.application.update_safely(address_kodepos='24104')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

    @patch.object(timezone, 'now')
    def test_check_autodialer_due_calling_time_2(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 29, 16, 55, 10)

        # 16:55:10 WIB -> 18:55:10 WIT
        self.application.update_safely(address_kodepos='98787')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 16:55:10 WIB -> 17:55:10 WITA
        self.application.update_safely(address_kodepos='75641')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 16:55:10 WIB
        self.application.update_safely(address_kodepos='24104')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

    @patch.object(timezone, 'now')
    def test_check_autodialer_due_calling_time_3(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 29, 17, 42, 18)

        # 17:42:18 WIB -> 19:42:18 WIT
        self.application.update_safely(address_kodepos='98787')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 17:42:18 WIB -> 18:42:18 WITA
        self.application.update_safely(address_kodepos='75641')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 17:42:18 WIB
        self.application.update_safely(address_kodepos='24104')
        self.assertTrue(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

    @patch.object(timezone, 'now')
    def test_check_autodialer_due_calling_time_4(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 29, 18, 30, 25)

        # 18:30:25 WIB -> 20:30:25 WIT
        self.application.update_safely(address_kodepos='98787')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 18:30:25 WIB -> 19:30:25 WITA
        self.application.update_safely(address_kodepos='75641')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))

        # 18:30:25 WIB
        self.application.update_safely(address_kodepos='24104')
        self.assertFalse(autodialer_services.check_autodialer_due_calling_time(self.lineup.id))
