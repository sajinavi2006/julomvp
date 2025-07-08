import mock
from django.db import connections
from django.test import TestCase
from django.core.management import call_command
try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3

from juloserver.centralized_migration.management.commands import CustomRetroloadExecutor


class RetroloadTestCase(TestCase):
    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_retroload.CustomRetroloadExecutor')
    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_retroload.CustomRetroloadExecutor.migration_plan')
    def test_centralized_retroload(self, mocked_plan, mocked_executor):
        connection = connections['default']
        out = StringIO()
        mocked_executor.return_value = CustomRetroloadExecutor(connection)
        # mocked_executor.assert_called_with('boo!')
        mocked_plan.return_value = None
        call_command(
            'centralized_retroload', stdout=out
        )
        self.assertIn('No retroloads to apply.', out.getvalue())

    def test_centralized_retroload_faked(self):
        out = StringIO()
        call_command(
            'centralized_retroload', '--fake', stdout=out
        )
        self.assertIn('FAKED', out.getvalue())

    def test_centralized_retroload_listed(self):
        out = StringIO()
        call_command(
            'centralized_retroload', '--list', stdout=out
        )
        self.assertEqual('', out.getvalue())
