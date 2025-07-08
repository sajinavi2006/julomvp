from importlib import import_module
from io import StringIO
from unittest.mock import (
    patch,
    call,
    MagicMock,
    Mock,
)

from django.core.management import call_command
from django.test import TestCase


PACKAGE_NAME = 'juloserver.sales_ops.management.commands.sales_ops_refresh_ranking_db'


class TestSalesOpsRefreshRankingDb(TestCase):

    @patch(PACKAGE_NAME + '.connection')
    def test_execute(self, mock_connection):
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.__enter__.return_value = mock_cursor

        out = StringIO()
        call_command('sales_ops_refresh_ranking_db', stdout=out)

        out.seek(0)
        self.assertIn('Executing "REFRESH MATERIALIZED VIEW sales_ops_r_score"...', out.readline())
        self.assertIn('Executing "REFRESH MATERIALIZED VIEW sales_ops_m_score"...', out.readline())
        self.assertIn('Executing "REFRESH MATERIALIZED VIEW sales_ops_graduation"...', out.readline())
        self.assertIn('Refresh ranking is success.', out.readline())

        mock_cursor.execute.assert_has_calls([
            call('REFRESH MATERIALIZED VIEW sales_ops_r_score'),
            call('REFRESH MATERIALIZED VIEW sales_ops_m_score'),
            call('REFRESH MATERIALIZED VIEW sales_ops_graduation')
        ])
        mock_cursor.__enter__.assert_called_once()
        mock_cursor.__exit__.assert_called_once()
