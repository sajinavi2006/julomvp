from django.db.migrations import CreateModel
from django.db.models.base import Model
from django.test import TestCase
from django.core.management import call_command
try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3
from django.db.migrations import Migration
from django.db import models
import mock


class MakeRetroloadsTestCase(TestCase):
    def test_centralized_makeretroload(self):
        out = StringIO()

        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makeretroloads.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makeretroloads', 'julo', stdout=out
            )
        self.assertIn('julo__auto', out.getvalue())

    def test_centralized_makeretroload_empty(self):
        out = StringIO()

        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makeretroloads.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makeretroloads', 'julo', '--empty', stdout=out
            )

        self.assertIn('julo__auto', out.getvalue())

    def test_centralized_makeretroload_empty_with_name(self):
        migration_name = 'dummy_migration_name'
        out = StringIO()
        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makeretroloads.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makeretroloads', 'julo', '--empty', '-n %s' % migration_name, stdout=out)
        self.assertIn(migration_name, out.getvalue())
