from unittest.mock import patch

from django.test import TestCase

from juloserver.routing.decorators import use_db_replica


@patch('juloserver.routing.decorators.JuloDbReplicaDbRouter')
class TestUseDbReplica(TestCase):
    @staticmethod
    @use_db_replica
    def no_exception():
        return 'success'

    @staticmethod
    @use_db_replica
    def with_exception():
        raise Exception

    def test_no_exception(self, mock_router):
        ret_val = self.no_exception()
        self.assertEqual('success', ret_val)
        mock_router.enable.assert_called_once()
        mock_router.disable.assert_called_once()

    def test_with_exception(self, mock_router):
        with self.assertRaises(Exception):
            self.with_exception()

        mock_router.enable.assert_called_once()
        mock_router.disable.assert_called_once()
