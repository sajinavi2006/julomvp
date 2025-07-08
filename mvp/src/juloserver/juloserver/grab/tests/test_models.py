from django.test import TestCase
from django.db import connections


class GrabRestructureHistoryLogTest(TestCase):
    def setUp(self):
        from juloserver.grab.tests.utils import ensure_grab_restructure_history_log_table_exists

        self.check_query = """
        select
            exists (
            select
                *
            from
                information_schema.tables
            where
                table_name = 'grab_restructure_history_log'
        );
        """

        ensure_grab_restructure_history_log_table_exists()

    def test_model_exists(self):
        connection = connections["partnership_grab_db"]
        with connection.cursor() as cursor:
            cursor.execute(self.check_query)
            is_exists = cursor.fetchone()[0]
        self.assertTrue(is_exists, True)
