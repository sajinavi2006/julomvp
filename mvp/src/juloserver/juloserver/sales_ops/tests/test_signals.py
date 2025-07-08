
from cuser.middleware import CuserMiddleware
from django.db.transaction import get_connection
from django.test import TestCase
from unittest.mock import patch
from juloserver.account.constants import AccountConstant

from juloserver.account.tests.factories import (
    AccountLimitFactory,
    AccountFactory,
)
from juloserver.julo.statuses import JuloOneCodes
from juloserver.julo.tests.factories import AuthUserFactory, StatusLookupFactory
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.sales_ops.models import (
    SalesOpsLineupHistory,
    SalesOpsLineup,
)
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsAgentAssignmentFactory,
)
from juloserver.sales_ops.services.sales_ops_services import SalesOpsSetting


class TestStoreSalesOpsLineupHistory(TestCase):
    def tearDown(self):
        CuserMiddleware.del_user()

    def test_update_lineup(self):
        lineup = SalesOpsLineupFactory(
            latest_account_limit_id=None, latest_agent_assignment_id=None, is_active=False
        )
        account_limit = AccountLimitFactory()
        agent_assignment = SalesOpsAgentAssignmentFactory()
        lineup.update_safely(
            latest_account_limit_id=account_limit.id,
            latest_agent_assignment_id=agent_assignment.id,
            is_active=True,
        )

        histories = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).all()
        self.assertEqual(1, len(histories))
        self.assertEqual(None, histories[0].old_values['latest_account_limit_id'], histories[0].old_values)
        self.assertEqual(None, histories[0].old_values['latest_agent_assignment_id'], histories[0].old_values)
        self.assertFalse(histories[0].old_values['is_active'], histories[0].old_values)
        self.assertEqual(account_limit.id, histories[0].new_values['latest_account_limit_id'], histories[0].new_values)
        self.assertEqual(agent_assignment.id, histories[0].new_values['latest_agent_assignment_id'], histories[0].new_values)
        self.assertTrue(histories[0].new_values['is_active'], histories[0].new_values)
        self.assertIsNone(histories[0].changed_by_id)
        self.assertNotIn('udate', histories[0].old_values)
        self.assertNotIn('udate', histories[0].new_values)

    def test_create_lineup(self):
        lineup = SalesOpsLineup.objects.create(account_id=AccountFactory().id)

        histories = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).all()
        self.assertEqual(1, len(histories))
        self.assertIsNone(histories[0].old_values['id'])
        self.assertIsNone(histories[0].old_values['account_id'])
        self.assertEqual(lineup.id, histories[0].new_values['id'])
        self.assertEqual(lineup.account_id, histories[0].new_values['account_id'])


    def test_store_changed_by(self):
        user = AuthUserFactory()
        CuserMiddleware.set_user(user)

        lineup = SalesOpsLineup.objects.create(account_id=AccountFactory().id)

        histories = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).all()
        self.assertEqual(1, len(histories))
        self.assertEqual(user.id, histories[0].changed_by_id)


class TestUpdateSalesOpsActivation(TestCase):
    # signals:
    # .juloserver.account.signals.update_sales_ops_on_account_status_change
    # .juloserver.account.signals.update_sales_ops_on_account_limit_change
    def setUp(self):
        status_lookup = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        self.account = AccountFactory(status=status_lookup)
        self.limit = 500000
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=self.limit,
            available_limit=self.limit,
        )
        SalesOpsSetting.get_available_limit()

    @patch('juloserver.account.signals.execute_after_transaction_safely')
    def test_signals_account_status_change(self, mock_execute_after_transaction_safely):
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        active_account = AccountFactory(status=active_status_code)
        active_account.update_safely(status_id=410)
        self.assertEqual(mock_execute_after_transaction_safely.call_count, 1)
