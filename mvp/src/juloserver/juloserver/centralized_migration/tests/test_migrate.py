import mock
import pytest
from django.conf import settings
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.core.management import call_command
try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3

from juloserver.centralized_migration.management.commands import CustomMigrationExecutor


def run_sql(sql):
    conn = connections['default']
    cur = conn.cursor()
    cur.execute(sql)
    conn.close()


@pytest.mark.skip(reason="Use Memory Too much")
class MigrateTestCase(TestCase):
    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_migrate.CustomMigrationExecutor')
    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_migrate.CustomMigrationExecutor.migration_plan')
    def test_centralized_migrate(self, mocked_plan, mocked_executor):
        connection = connections['default']
        out = StringIO()
        mocked_executor.return_value = CustomMigrationExecutor(connection)
        # mocked_executor.assert_called_with('boo!')
        mocked_plan.return_value = None
        call_command(
            'centralized_migrate', stdout=out
        )
        self.assertIn('No migrations to apply', out.getvalue())

    def test_centralized_migrate_faked(self):
        out = StringIO()
        call_command(
            'centralized_migrate', '--fake', stdout=out
        )
        self.assertIn('FAKED', out.getvalue())

    def test_centralized_migrate_abc_listed(self):
        out = StringIO()
        call_command(
            'centralized_migrate', '--list', stdout=out
        )
        self.assertEqual('', out.getvalue())

    def test_centralized_migrate_app_label(self):
        out = StringIO()
        call_command(
            'centralized_migrate', 'julo', '--fake', stdout=out
        )
        self.assertIn('FAKED', out.getvalue())

    def test_centralized_migrate_app_label_and_name(self):
        out = StringIO()
        call_command(
            'centralized_migrate', 'paylater',
            '159903565864__paylater__auto_20200902_1534', '--fake', stdout=out
        )
        self.assertIn('FAKED', out.getvalue())
