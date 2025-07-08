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


class MakeMigrationsTestCase(TestCase):
    def test_centralized_makemigrations(self):
        out = StringIO()
        call_command(
            'centralized_makemigrations', '--dry-run', stdout=out
        )
        self.assertIn('No changes detected', out.getvalue())

    def test_centralized_makemigrations_empty(self):
        out = StringIO()

        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makemigrations.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makemigrations', 'julo', '--empty', stdout=out
            )

        self.assertIn('auto', out.getvalue())

    def test_centralized_makemigrations_empty_with_name(self):
        migration_name = 'dummy_migration_name'
        out = StringIO()
        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makemigrations.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makemigrations', 'julo', '--empty', '-n %s' % migration_name, stdout=out)
        self.assertIn(migration_name, out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_makemigrations.CustomMigrationAutodetector',
        autospec=True)
    def test_centralized_makemigrations_create_new_table(self, mocked_autodetector):
        migration_instance = Migration(u'159963819178__loan_selloff__dummymodel', 'loan_selloff')
        migration_instance.operations = [CreateModel(
            u'DummyModel',
            [
                (u'cdate', models.DateTimeField(auto_now_add=True)),
                (u'udate', models.DateTimeField(auto_now=True)),
                (u'id', models.AutoField(db_column=u'dummy_model_id', primary_key=True, serialize=False)),
                (u'content', models.TextField())
            ],
            bases=(Model,),
            managers=[],
            options={u'abstract': False}
        )]
        migration_instance.initial = False
        return_changes = {'loan_selloff': [migration_instance]}

        autodetector_instance = mocked_autodetector.return_value
        autodetector_instance.changes.return_value = return_changes
        out = StringIO()
        with mock.\
                patch(
            'juloserver.centralized_migration.management.commands.centralized_makemigrations.open',
            mock.mock_open(), create=True
        ):
            call_command(
                'centralized_makemigrations', 'loan_selloff', stdout=out
            )
        self.assertIn('loan_selloff__dummymodel.py', out.getvalue())
