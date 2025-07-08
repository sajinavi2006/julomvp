import mock
from django.db import connections
from django.test import TestCase
from django.core.management import call_command
try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3

from juloserver.centralized_migration.management.commands import CustomMigrationExecutor


class ConvertMigrationTestCase(TestCase):
    path_file = 'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations'
    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case1(self, mocked_listdir):
        mocked_listdir.return_value = ['0689_migrate_mobile_payment_method.py', 'dummy.pyc', '__init__.py']
        out = StringIO()
        with open(
                'juloserver/centralized_migration/tests/migration_file_factories/0689_migrate_mobile_payment_method.py'
        ) as f:
            migration_string = f.read()
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string), create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertIn('0689_migrate_mobile_payment_method.py', out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case2(self, mocked_listdir):
        mocked_listdir.return_value = ['0234_load_grab_food_product.py']
        out = StringIO()
        with open(
                'juloserver/centralized_migration/tests/migration_file_factories/0234_load_grab_food_product.py'
        ) as f:
            migration_string = f.read()
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string),
                        create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertIn('0234_load_grab_food_product.py', out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case3(self, mocked_listdir):
        mocked_listdir.return_value = ['0267_new_status_164.py']
        out = StringIO()
        with open(
                'juloserver/centralized_migration/tests/migration_file_factories/0267_new_status_164.py'
        ) as f:
            migration_string = f.read()
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string),
                        create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertIn('0267_new_status_164.py', out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case4(self, mocked_listdir):
        mocked_listdir.return_value = ['0444_alter_vendor_data_history_table.py']
        out = StringIO()
        with open(
                'juloserver/centralized_migration/tests/migration_file_factories/0444_alter_vendor_data_history_table.py'
        ) as f:
            migration_string = f.read()
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string),
                        create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertIn('0444_alter_vendor_data_history_table.py', out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case5(self, mocked_listdir):
        mocked_listdir.return_value = ['0148_bri_integration.py']
        out = StringIO()
        migration_string = 'juloserver/centralized_migration/tests/migration_file_factories/0148_bri_integration.py'
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string),
                        create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertNotIn('0148_bri_integration.py', out.getvalue())

    @mock.patch(
        'juloserver.centralized_migration.management.commands.centralized_convertmanualmigrations.os.listdir')
    def test_centralized_convert_migration_case6(self, mocked_listdir):
        mocked_listdir.return_value = ['0376_LoanAgentAssignModel.py']
        out = StringIO()
        with open(
                'juloserver/centralized_migration/tests/migration_file_factories/0376_LoanAgentAssignModel.py'
        ) as f:
            migration_string = f.read()
        with mock.patch('{}.open'.format(self.path_file), mock.mock_open(read_data=migration_string),
                        create=True):
            call_command(
                'centralized_convertmanualmigrations', stdout=out
            )
        self.assertIn('0376_LoanAgentAssignModel.py', out.getvalue())
