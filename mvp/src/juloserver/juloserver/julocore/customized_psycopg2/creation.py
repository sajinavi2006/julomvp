from django.conf import settings
from django.db.backends.postgresql_psycopg2.creation import (
    DatabaseCreation as BaseDatabaseCreation,
)
from django.db.backends.postgresql_psycopg2.creation import *  # NOQA


class CustomDatabaseCreation(BaseDatabaseCreation):
    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        """
        Internal implementation - creates the test db tables.
        """
        super(CustomDatabaseCreation, self)._create_test_db(verbosity, autoclobber, keepdb)
        self._create_test_schema_for_non_ops_schema()

    def _create_test_schema_for_non_ops_schema(self):
        test_database_name = self._get_test_db_name()
        settings.DATABASES[self.connection.alias]["NAME"] = test_database_name
        self.connection.settings_dict["NAME"] = test_database_name

        with self.connection.cursor() as c:
            c.execute(
                '''
                CREATE SCHEMA IF NOT EXISTS ana;
                CREATE SCHEMA IF NOT EXISTS msg;
                CREATE SCHEMA IF NOT EXISTS sb;
                CREATE SCHEMA IF NOT EXISTS hst;
                '''
            )
