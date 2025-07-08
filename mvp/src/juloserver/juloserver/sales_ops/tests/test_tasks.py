import pytz
import datetime
from datetime import timedelta
from unittest.mock import (
    patch,
    call,
    ANY,
)

import pytz
from django.utils import timezone
from django.test import TestCase
from juloserver.julo.models import FeatureSetting

from juloserver.account.tests.factories import (
    AccountFactory,
    CustomerFactory,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.sales_ops import tasks
from juloserver.sales_ops.constants import (
    ScoreCriteria,
    SalesOpsSettingConst,
)
from juloserver.sales_ops.models import (
    SalesOpsAutodialerQueueSnapshot,
    SalesOpsLineup,
    SalesOpsAccountSegmentHistory,
    SalesOpsAgentAssignment,
    SalesOpsRMScoring,
)
from juloserver.sales_ops.services.sales_ops_revamp_services import \
    filter_out_user_assigned_in_bucket, get_next_reset_bucket_date
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsRMScoringFactory,
    SalesOpsAccountSegmentHistoryFactory,
    SalesOpsPrioritizationConfigurationFactory,
    SalesOpsAgentAssignmentFactory,
    SalesOpsPrepareDataFactory, FeatureSettingSalesOpsRevampFactory,
)

PACKAGE_NAME = 'juloserver.sales_ops.tasks'


@patch(PACKAGE_NAME + '.management')
@patch(PACKAGE_NAME + '.logger')
class TestSyncSalesOpsLineup(TestCase):
    def test_run(self, mock_logger, mock_management):
        tasks.sync_sales_ops_lineup()

        mock_logger.error.assert_not_called()
        calls = [
            call('sales_ops_refresh_ranking_db', verbosity=0, stdout=ANY),
        ]
        mock_management.call_command.assert_has_calls(calls)


class TestSnapshotSalesOpsAutodialerQueue(TestCase):
    def test_save_snapshot(self):
        lineups = SalesOpsLineupFactory.create_batch(3, prioritization=1, is_active=True)
        lineups.reverse()

        # 1x query for feature setting
        # 2x query for transaction
        # 1x query to count query
        # 1x query to get all queue
        # 1x query to save
        with self.assertNumQueries(6):
            tasks.snapshot_sales_ops_autodialer_queue()

        snapshots = SalesOpsAutodialerQueueSnapshot.objects.order_by('ordering').all()
        self.assertEqual(3, len(snapshots))
        for idx, snapshot in enumerate(snapshots):
            self.assertEqual(lineups[idx].account_id, snapshot.account_id)
            self.assertEqual(idx + 1, snapshot.ordering)

    def test_no_snapshot(self):
        # 1x query for feature setting
        # 1x query to count query
        # 1x query to save empty snapshot
        with self.assertNumQueries(3):
            tasks.snapshot_sales_ops_autodialer_queue()

        snapshots = SalesOpsAutodialerQueueSnapshot.objects.order_by('ordering').all()
        self.assertEqual(1, len(snapshots))
        self.assertIsNone(snapshots[0].account_id)
        self.assertIsNone(snapshots[0].ordering)
        self.assertIsNone(snapshots[0].prioritization)


class TestDeactivateSalesOps(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.lineup = SalesOpsLineupFactory(
            is_active=True,
            account=self.account,
        )
        # Create sales ops agent assignment
        self.agent = AgentFactory()
        self.sales_ops_agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=self.lineup, agent_id=self.agent.id, is_active=True
        )


class TestPrioritizeSalesOpsLineup(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.lineup = SalesOpsLineupFactory(is_active=True, account=self.account, prioritization=1)
        self.r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=1)
        self.m_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=2)
        self.prioritization_config = SalesOpsPrioritizationConfigurationFactory(
            r_score=1, m_score=2, prioritization=6, is_active=True
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS,
            parameters={
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_DAYS: 30,
                SalesOpsSettingConst.LINEUP_MAX_USED_LIMIT_PERCENTAGE: 0.9,
                "buckets": [
                    {
                        "code": "sales_ops_a",
                        "name": "SALES OPS A",
                        "scores": [
                            2,
                            3
                        ],
                        "criteria": "recency",
                        "is_active": True,
                        "description": "Sales Ops A: R-score 2 and 3"
                    },
                    {
                        "code": "sales_ops_b",
                        "name": "SALES OPS B",
                        "scores": [
                            1,
                            4,
                            5
                        ],
                        "criteria": "recency",
                        "is_active": True,
                        "description": "Sales Ops B: R-score 1,4, and 5"
                    }
                ],
                SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
                SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
            })

    @patch('{}.sales_ops_services.bulk_create_account_segment_history'.format(PACKAGE_NAME))
    def test_success_prioritize(self, mock_bulk_create_account_segment_history):
        SalesOpsAccountSegmentHistoryFactory(
            account_id=self.account.id,
            r_score_id=self.r_score.id,
            m_score_id=self.m_score.id
        )
        mock_bulk_create_account_segment_history.return_value = {
            self.account.id: (self.m_score.score, self.r_score.score)
        }

        tasks.prioritize_sales_ops_lineups([self.lineup.id])
        lineup = SalesOpsLineup.objects.get(pk=self.lineup.id)
        account_segment = SalesOpsAccountSegmentHistory.objects.get(account_id=self.account.id)
        r_score = SalesOpsRMScoring.objects.get(id=account_segment.r_score_id).score
        self.assertEqual(r_score, 1)
        self.assertEqual(lineup.bucket_code, 'sales_ops_b')
        self.lineup.refresh_from_db()
        self.assertEqual(4, self.lineup.prioritization)

        parameters = self.feature_setting.parameters
        parameters['buckets'] = [
            {
                "code": "sales_ops_b",
                "name": "SALES OPS B",
                "scores": [4, 5],
                "criteria": "recency",
                "is_active": True
            }
        ]
        self.feature_setting.update_safely(parameters=parameters)
        tasks.prioritize_sales_ops_lineups([self.lineup.id])
        lineup = SalesOpsLineup.objects.get(pk=self.lineup.id)
        self.assertEqual(r_score, 1)
        self.assertIsNone(lineup.bucket_code)

    @patch('{}.sales_ops_services.bulk_create_account_segment_history'.format(PACKAGE_NAME))
    def test_improper_configuration(self, mock_bulk_create_account_segment_history):
        r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=3)
        SalesOpsAccountSegmentHistoryFactory(
            account_id=self.account.id,
            r_score_id=r_score.id,
            m_score_id=self.m_score.id
        )
        mock_bulk_create_account_segment_history.return_value = {
            self.account.id: (self.m_score.score, r_score.score)
        }

        tasks.prioritize_sales_ops_lineups([self.lineup.id])

        self.lineup.refresh_from_db()
        self.assertEqual(4, self.lineup.prioritization)

    def test_lineup_is_not_active(self):
        self.lineup.is_active = False
        self.lineup.save(update_fields=['is_active'])

        tasks.prioritize_sales_ops_lineups([self.lineup.id])

        self.lineup.refresh_from_db()
        self.assertEqual(1, self.lineup.prioritization)

    @patch('{}.update_vendor_bucket_lineups_logic'.format(PACKAGE_NAME))
    def test_lineup_with_vendor_logic(self, _update_vendor_bucket_task):

        tasks.prioritize_sales_ops_lineups([self.lineup.id], True)

        _update_vendor_bucket_task.delay.assert_called_once()


class TestInitSalesOpsLineupNewFlow(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.customer = CustomerFactory(account=self.account)
        self.sales_ops_prepare_data = SalesOpsPrepareDataFactory(
            account=self.account,
            customer=self.customer,
            available_limit=500_000,
            customer_type='ftc',
            application_history_x190_cdate=datetime.datetime(2024, 8, 2, 12, 23, 34, tzinfo=pytz.UTC),
            latest_loan_fund_transfer_ts=datetime.datetime(2024, 7, 25, 12, 23, 34, tzinfo=pytz.UTC),
        )
        FeatureSettingFactory(feature_name='sales_ops_revamp', is_active=True)

    @patch('{}.process_generate_lineup_task'.format(PACKAGE_NAME))
    def test_call_init_sales_ops_lineup_new_flow_task(self, process_generate_lineup_task):
        tasks.init_sales_ops_lineup_new_flow()
        process_generate_lineup_task.delay.assert_called_once()

class TestSalesOpsLineupFunctions(TestCase):
    def setUp(self):
        # Set current time and mock the feature setting
        self.now = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        FeatureSettingSalesOpsRevampFactory()

    def create_lineup(self, account, bucket_code=None, next_reset_bucket_date=None):
        """
        Helper method to create SalesOpsLineup entries for test accounts.
        """
        return SalesOpsLineup.objects.create(
            account_id=account.id,
            bucket_code=bucket_code,
            next_reset_bucket_date=next_reset_bucket_date
        )

    @patch('juloserver.sales_ops.utils.timezone.now')
    def test_filter_out_user_assigned_in_bucket_case_1(self, mock_now):
        # case 1, today__day = 1
        mock_now.return_value = timezone.datetime(2024, 10, 1, 0, 0, 0, tzinfo=pytz.UTC)

        # Mock the next reset bucket date
        next_reset_date = timezone.datetime(2024, 10, 1, 0, 0, 0, tzinfo=pytz.UTC)

        # Create test accounts
        accounts = AccountFactory.create_batch(5)

        # Create test data
        self.create_lineup(accounts[0], bucket_code='sales_ops_a', next_reset_bucket_date=next_reset_date)
        self.create_lineup(accounts[1], bucket_code='sales_ops_b', next_reset_bucket_date=next_reset_date + timedelta(days=50))  # Invalid
        self.create_lineup(accounts[2], bucket_code=None, next_reset_bucket_date=None)  # valid
        self.create_lineup(accounts[3], bucket_code='sales_ops_c', next_reset_bucket_date=next_reset_date)
        # accounts[4] has no lineup, should be valid

        # Prepare account IDs for the filter function
        account_ids = [account.id for account in accounts]

        # Call the function to filter out invalid accounts
        result = filter_out_user_assigned_in_bucket(account_ids)

        # Define expected account IDs that should pass the filter (valid accounts)
        expected_account_ids = {accounts[0].id, accounts[2].id, accounts[3].id, accounts[4].id}

        # Assert the results are as expected
        self.assertEqual(result, expected_account_ids)

        # Assert the account with a non-matching next_reset_bucket_date (account[1]) is filtered out
        self.assertNotIn(accounts[1].id, result)

        # Assert the account with no lineup (account[4]) is included
        self.assertIn(accounts[4].id, result)

    @patch('juloserver.sales_ops.utils.timezone.now')
    def test_filter_out_user_assigned_in_bucket_case_2(self, mock_now):
        # case 1, today__day = 1
        mock_now.return_value = timezone.datetime(2024, 9, 15, 0, 0, 0, tzinfo=pytz.utc)

        # Mock the next reset bucket date
        next_reset_date = timezone.datetime(2024, 10, 1, 0, 0, 0, tzinfo=pytz.utc)

        accounts = AccountFactory.create_batch(5)

        self.create_lineup(accounts[0], bucket_code='sales_ops_a',
                           next_reset_bucket_date=next_reset_date)
        self.create_lineup(accounts[1], bucket_code='sales_ops_b',
                           next_reset_bucket_date=next_reset_date- timedelta(days=20))  # Invalid
        self.create_lineup(accounts[2], bucket_code=None,
                           next_reset_bucket_date=next_reset_date)  # Should be valid
        self.create_lineup(accounts[3], bucket_code='sales_ops_c',
                           next_reset_bucket_date=next_reset_date)
        # accounts[4] has no lineup, should be valid

        # Prepare account IDs for the filter function
        account_ids = [account.id for account in accounts]

        # Call the function to filter out invalid accounts
        result = filter_out_user_assigned_in_bucket(account_ids)

        expected_account_ids = {accounts[1].id, accounts[4].id}

        # Assert the results are as expected
        self.assertEqual(result, expected_account_ids)

        self.assertNotIn(accounts[0].id, result)
        self.assertNotIn(accounts[2].id, result)
        self.assertNotIn(accounts[3].id, result)
