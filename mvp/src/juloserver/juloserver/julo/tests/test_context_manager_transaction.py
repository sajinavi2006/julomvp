from django.test import TestCase
from django.db import DatabaseError
from juloserver.julocore.context_manager import db_transactions_atomic


class TestAtomicTransactionsContextManager(TestCase):

    def test_atomic_transactions_success(self):
        try:
            with self.assertRaises(DatabaseError):
                with db_transactions_atomic(['default', 'loan_db']):
                    pass
        except AssertionError as err:
            self.assertEqual(err.__str__(), 'DatabaseError not raised')

    def test_atomic_transactions_database_error(self):
        with self.assertRaises(DatabaseError):
            with db_transactions_atomic(['default', 'loan_db']):
                raise DatabaseError("Simulated database error")
