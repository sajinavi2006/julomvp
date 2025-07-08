from datetime import (
    timedelta,
    datetime,
    date,
)
from time import timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from factory import Iterator

from juloserver.account.tests.factories import AccountFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.sales_ops.constants import ScoreCriteria
from juloserver.sales_ops.models import (
    SalesOpsAccountSegmentHistory,
    SalesOpsAgentAssignment,
    SalesOpsLineup,
    SalesOpsPrioritizationConfiguration,
    SalesOpsRMScoring,
    SalesOpsAutodialerSession,
    SalesOpsAutodialerActivity,
    SalesOpsAutodialerQueueSnapshot,
)
from juloserver.sales_ops.tests.factories import (
    SalesOpsAccountSegmentHistoryFactory,
    SalesOpsAgentAssignmentFactory,
    SalesOpsRMScoringFactory,
    SalesOpsLineupFactory,
    SalesOpsPrioritizationConfigurationFactory,
    SalesOpsAutodialerSessionFactory,
    SalesOpsAutodialerActivityFactory,
    SalesOpsAutodialerQueueSnapshotFactory,
)

PACKAGE_NAME = 'juloserver.sales_ops.models'


class TestAccountSegmentHistory(TestCase):
    factory_class = SalesOpsAccountSegmentHistoryFactory
    model_class = SalesOpsAccountSegmentHistory

    def test_factory(self):
        acc_seg_history = self.factory_class()

        self.assertIsNotNone(acc_seg_history)
        self.assertIsInstance(acc_seg_history, self.model_class)

    def test_create(self):
        acc_seg_history = self.model_class.objects.create(
            account_id=AccountFactory().id,
            m_score_id=SalesOpsRMScoringFactory().id,
            r_score_id=SalesOpsRMScoringFactory().id,
        )
        self.assertIsNotNone(acc_seg_history.id)

    def test_str(self):
        AccountFactory.create_batch(3)
        acc_seg_history = self.factory_class()

        expected = '{} (account:{}) (r_score:{}) (m_score:{})'.format(
            acc_seg_history.id, acc_seg_history.account_id,
            acc_seg_history.r_score_id,
            acc_seg_history.m_score_id,
        )
        self.assertEqual(str(acc_seg_history), expected)


class TestSalesOpsAgentAssignment(TestCase):
    factory_class = SalesOpsAgentAssignmentFactory
    model_class = SalesOpsAgentAssignment

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(
            agent_id=AgentFactory().id, lineup_id=SalesOpsLineupFactory().id
        )
        self.assertIsNotNone(model.id)

    def test_str(self):
        SalesOpsLineupFactory.create_batch(3)
        AgentFactory.create_batch(2)
        model = self.factory_class()

        expected = '{} (lineup:{}) (agent:{})'.format(
            model.id, model.lineup_id, model.agent_id)
        self.assertEqual(str(model), expected)


class TestSalesOpsAgentAssignmentManager(TestCase):
    def test_get_previous_assignment(self):
        lineup = SalesOpsLineupFactory()
        assignments = SalesOpsAgentAssignmentFactory.create_batch(
            4,
            completed_date=Iterator(['2020-05-01', None, '2020-05-03', '2020-05-04']),
            assignment_date=Iterator(['2020-05-01', '2020-05-02', '2020-05-03', '2020-05-04']),
            lineup=lineup
        )
        ret_vals = [SalesOpsAgentAssignment.objects.get_previous_assignment(assignment) for assignment in assignments]
        self.assertEqual(assignments[2], ret_vals[3])
        self.assertEqual(assignments[0], ret_vals[2])
        self.assertEqual(assignments[0], ret_vals[1])
        self.assertIsNone(ret_vals[0])


class TestLineup(TestCase):
    factory_class = SalesOpsLineupFactory
    model_class = SalesOpsLineup

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(account_id=AccountFactory().id, prioritization=5)
        self.assertIsNotNone(model.id)

    def test_str(self):
        AccountFactory.create_batch(3)
        model = self.factory_class(prioritization=2)

        expected = '{} (account:{}) (priority:{})'.format(
            model.id, model.account_id, 2)
        self.assertEqual(str(model), expected)


class TestLineUpManager(TestCase):
    def setUp(self):
        self.utc_now = datetime(2020, 1, 31, 0, 0, 0)

    def test_autodialer_default_queue_queryset_no_assignment(self):
        """
        Test prioritization and cdate ordering
        Test `is_active` from lineup table.
        """
        SalesOpsLineupFactory.create_batch(1, is_active=False, prioritization=1)
        SalesOpsLineupFactory.create_batch(2, is_active=True, prioritization=0)
        prior_1_lineups = SalesOpsLineupFactory.create_batch(3, is_active=True, prioritization=1)
        prior_2_lineups = SalesOpsLineupFactory.create_batch(2, is_active=True, prioritization=2)
        prior_1_lineups.reverse()
        prior_2_lineups.reverse()

        with self.assertNumQueries(1):
            qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(1)

        with self.assertNumQueries(1):
            result_lineups = qs.all()
            total_queue = len(result_lineups)

        self.assertEqual(5, total_queue)
        self.assertEqual(prior_1_lineups[0], result_lineups[0])
        self.assertEqual(prior_1_lineups[1], result_lineups[1])
        self.assertEqual(prior_1_lineups[2], result_lineups[2])
        self.assertEqual(prior_2_lineups[0], result_lineups[3])
        self.assertEqual(prior_2_lineups[1], result_lineups[4])

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_active_assignment(self, mock_now):
        mock_now.return_value = self.utc_now
        today = timezone.localtime(self.utc_now)
        lineups = SalesOpsLineupFactory.create_batch(4, is_active=True, prioritization=1)
        lineups.reverse()
        agent_assignments = [
            SalesOpsAgentAssignmentFactory(lineup=lineups[0], is_active=True, completed_date=None),
            SalesOpsAgentAssignmentFactory(lineup=lineups[1], is_active=False, completed_date=None),
            SalesOpsAgentAssignmentFactory(lineup=lineups[1], is_active=True, completed_date=None),
            SalesOpsAgentAssignmentFactory(lineup=lineups[2], is_active=False, completed_date=None),
            SalesOpsAgentAssignmentFactory(lineup=lineups[3], is_active=False, completed_date=None),
        ]
        lineups[0].update_safely(latest_agent_assignment_id=agent_assignments[0].id)
        lineups[1].update_safely(latest_agent_assignment_id=agent_assignments[2].id)
        lineups[2].update_safely(latest_agent_assignment_id=agent_assignments[3].id)
        lineups[3].update_safely(latest_agent_assignment_id=agent_assignments[4].id)

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(1)

        result_lineups = qs.all()
        total_queue = len(result_lineups)

        self.assertEqual(2, total_queue, result_lineups)
        self.assertEqual(lineups[2], result_lineups[0])
        self.assertEqual(lineups[3], result_lineups[1])

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_assignment_rpc(self, mock_now):
        mock_now.return_value = self.utc_now
        rpc_assignment_delay_hours = 7
        rpc_delay_hours = 2
        today = timezone.localtime(self.utc_now)
        rpc_expire_date = today - timedelta(hours=rpc_delay_hours)
        rpc_assignment_expire_date = today - timedelta(hours=rpc_assignment_delay_hours)
        agent = AgentFactory()
        lineups = SalesOpsLineupFactory.create_batch(8, is_active=True, prioritization=1)
        lineups.reverse()
        SalesOpsAgentAssignmentFactory(
            lineup=lineups[0], is_active=False, is_rpc=True, completed_date=rpc_expire_date
        ),
        SalesOpsAgentAssignmentFactory(
            lineup=lineups[1],
            is_active=False,
            is_rpc=True,
            completed_date=rpc_expire_date,
            agent_id=agent.id,
        ),
        agent_assignments = [
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[0],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_expire_date,
                agent_id=agent.id,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[1], is_active=False, is_rpc=True, completed_date=rpc_expire_date
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[2],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_expire_date,
                agent_id=agent.id,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[3],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_expire_date + timedelta(seconds=1),
                agent_id=agent.id,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[4],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_expire_date - timedelta(seconds=1),
                agent_id=agent.id,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[5],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_assignment_expire_date,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[6],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_assignment_expire_date + timedelta(seconds=1),
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[7],
                is_active=False,
                is_rpc=True,
                completed_date=rpc_assignment_expire_date - timedelta(seconds=1),
            ),
        ]
        for idx, lineup in enumerate(lineups):
            lineup.update_safely(latest_agent_assignment_id=agent_assignments[idx].id)

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(
            agent.id,
            rpc_assignment_delay_hour=rpc_assignment_delay_hours,
            rpc_delay_hour=rpc_delay_hours,
        )

        result_lineups = qs.all()
        total_queue = len(result_lineups)

        self.assertEqual(5, total_queue, result_lineups)
        self.assertEqual(lineups[0], result_lineups[0])
        self.assertEqual(lineups[2], result_lineups[1])
        self.assertEqual(lineups[4], result_lineups[2])
        self.assertEqual(lineups[5], result_lineups[3])
        self.assertEqual(lineups[7], result_lineups[4])

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_non_rpc(self, mock_now):
        mock_now.return_value = self.utc_now
        non_rpc_delay_hour = 4
        non_rpc_final_delay_hour = 168
        non_rpc_final_attempt_count = 3
        today = timezone.localtime(self.utc_now)
        non_rpc_expire_date = today - timedelta(hours=non_rpc_delay_hour)
        non_rpc_final_expire_date = today - timedelta(hours=non_rpc_final_delay_hour)
        lineups = SalesOpsLineupFactory.create_batch(10, is_active=True, prioritization=1)
        lineups.reverse()

        agent_assignments = [
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[0], is_active=False, is_rpc=False, completed_date=today
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[1],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count,
                completed_date=non_rpc_expire_date,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[2],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count - 1,
                completed_date=non_rpc_expire_date,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[3],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count + 1,
                completed_date=non_rpc_expire_date,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[4], is_active=False, is_rpc=False, completed_date=non_rpc_expire_date
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[5],
                is_active=False,
                is_rpc=False,
                completed_date=non_rpc_expire_date + timedelta(seconds=1),
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[6],
                is_active=False,
                is_rpc=False,
                completed_date=non_rpc_expire_date - timedelta(seconds=1),
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[7],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count,
                completed_date=non_rpc_final_expire_date,
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[8],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count,
                completed_date=non_rpc_final_expire_date + timedelta(seconds=1),
            ),
            SalesOpsAgentAssignmentFactory(
                lineup=lineups[9],
                is_active=False,
                is_rpc=False,
                non_rpc_attempt=non_rpc_final_attempt_count,
                completed_date=non_rpc_final_expire_date - timedelta(seconds=1),
            ),
        ]
        for idx, lineup in enumerate(lineups):
            lineup.update_safely(latest_agent_assignment_id=agent_assignments[idx].id)

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(
            1,
            non_rpc_delay_hour=non_rpc_delay_hour,
            non_rpc_final_delay_hour=non_rpc_final_delay_hour,
            non_rpc_final_attempt_count=non_rpc_final_attempt_count,
        )

        result_lineups = qs.all()
        total_queue = len(result_lineups)

        self.assertEqual(5, total_queue, result_lineups)
        self.assertEqual(lineups[2], result_lineups[0], result_lineups)
        self.assertEqual(lineups[4], result_lineups[1], result_lineups)
        self.assertEqual(lineups[6], result_lineups[2], result_lineups)
        self.assertEqual(lineups[7], result_lineups[3], result_lineups)
        self.assertEqual(lineups[9], result_lineups[4], result_lineups)

    def test_autodialer_default_queue_queryset_ordering(self):
        agent = AgentFactory()
        agent_assignments = SalesOpsAgentAssignmentFactory.create_batch(
            2, is_active=False, completed_date='1999-01-01'
        )
        agent_assignment_ids = [assignment.id for assignment in agent_assignments]
        old_lineups = SalesOpsLineupFactory.create_batch(
            2,
            is_active=True,
            latest_agent_assignment_id=Iterator(agent_assignment_ids),
            prioritization=2,
        )
        new_lineups = SalesOpsLineupFactory.create_batch(1, is_active=True, prioritization=2)
        highest_lineups = SalesOpsLineupFactory.create_batch(1, is_active=True, prioritization=1)

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(agent.id)
        result_lineups = qs.all()

        total_queue = len(result_lineups)
        self.assertEqual(4, total_queue)
        self.assertEqual(highest_lineups[0], result_lineups[0])
        self.assertEqual(new_lineups[0], result_lineups[1])
        self.assertEqual(old_lineups[0], result_lineups[2])
        self.assertEqual(old_lineups[1], result_lineups[3])

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_none_agent(self, mock_now):
        mock_now.return_value = self.utc_now
        agent = AgentFactory()
        rpc_assignment_delay_hours = 7
        rpc_delay_hours = 2
        today = timezone.localtime(self.utc_now)
        rpc_assignment_expire_date = today - timedelta(hours=rpc_assignment_delay_hours)
        lineup = SalesOpsLineupFactory(is_active=True, prioritization=1)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=lineup,
            is_active=False,
            is_rpc=True,
            completed_date=rpc_assignment_expire_date + timedelta(seconds=1),
            agent_id=agent.id,
        )
        lineup.update_safely(latest_agent_assignment_id=agent_assignment.id)

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(
            None,
            rpc_assignment_delay_hour=rpc_assignment_delay_hours,
            rpc_delay_hour=rpc_delay_hours,
        )
        result_lineups = qs.all()

        total_queue = len(result_lineups)
        self.assertEqual(1, total_queue)
        self.assertEqual(lineup, result_lineups[0])

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_inactive_lineup(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 31, 10, 12, 13)
        lineup = SalesOpsLineupFactory(
            is_active=True,
            prioritization=1,
            inactive_until=datetime(2020, 1, 31, 10, 12, 13)
        )

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(None)
        result_lineups = qs.all()

        total_queue = len(result_lineups)
        self.assertEqual(0, total_queue)

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_autodialer_default_queue_queryset_with_old_inactive_lineup(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 31, 10, 12, 13)
        lineup = SalesOpsLineupFactory(
            is_active=True,
            prioritization=1,
            inactive_until=datetime(2020, 1, 31, 10, 12, 12)
        )

        qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(None)
        result_lineups = qs.all()

        total_queue = len(result_lineups)
        self.assertEqual(1, total_queue)


class TestPrioritizationConfiguration(TestCase):
    factory_class = SalesOpsPrioritizationConfigurationFactory
    model_class = SalesOpsPrioritizationConfiguration

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(
            segment_name='segment name',
            prioritization=5,
            r_score=2,
            m_score=3,
        )
        self.assertIsNotNone(model.id)

    def test_str(self):
        model = self.factory_class(prioritization=2, r_score=3, m_score=4)

        expected = '{} (priority:{}) (r:{}) (m:{})'.format(
            model.id, 2, 3, 4)
        self.assertEqual(str(model), expected)


class TestRMScoring(TestCase):
    factory_class = SalesOpsRMScoringFactory
    model_class = SalesOpsRMScoring

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(
            criteria=ScoreCriteria.MONETARY,
            top_percentile=0.80,
            bottom_percentile=0.20,
            score=3,
        )
        self.assertIsNotNone(model.id)

    def test_str(self):
        model = self.factory_class(
            criteria=ScoreCriteria.MONETARY, top_percentile=0.312, score=4)

        expected = '{} (criteria:{}) (score:{}) (top:{})'.format(
            model.id, ScoreCriteria.MONETARY, 4, 0.312)
        self.assertEqual(str(model), expected)


class TestSalesOpsAutodialerSession(TestCase):
    factory_class = SalesOpsAutodialerSessionFactory
    model_class = SalesOpsAutodialerSession

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(lineup_id=SalesOpsLineupFactory().id)
        self.assertIsNotNone(model.id)


class TestSalesOpsAutodialerActivity(TestCase):
    factory_class = SalesOpsAutodialerActivityFactory
    model_class = SalesOpsAutodialerActivity

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(
            agent_id=AgentFactory().id,
            autodialer_session_id=SalesOpsAutodialerSessionFactory().id
        )
        self.assertIsNotNone(model.id)


class TestSalesOpsAutodialerQueueSnapshot(TestCase):
    factory_class = SalesOpsAutodialerQueueSnapshotFactory
    model_class = SalesOpsAutodialerQueueSnapshot

    def setUp(self):
        self.account = AccountFactory()

    def test_factory(self):
        model = self.factory_class()

        self.assertIsNotNone(model)
        self.assertIsInstance(model, self.model_class)

    def test_create(self):
        model = self.model_class.objects.create(
            account_id=self.account.id,
            snapshot_at=timezone.now(),
            ordering=1,
            prioritization=2
        )
        self.assertIsNotNone(model.id)
        self.assertEqual(1, model.ordering)
        self.assertEqual(2, model.prioritization)
