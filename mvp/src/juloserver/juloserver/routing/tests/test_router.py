from unittest.mock import (
    MagicMock,
    patch,
)

from django.test import TestCase
from django.test.utils import override_settings

from juloserver.julo.models import (
    Application,
    Customer,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    EmailHistoryFactory,
)
from juloserver.routing.router import JuloDbReplicaDbRouter


@patch('juloserver.routing.router.get_loc_mem_cache')
class TestMasterReplicaDbRouter(TestCase):
    def setUp(self):
        self.router = JuloDbReplicaDbRouter()

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE=False)
    def test_setting_mode_false(self, *args):
        self.router.enable()
        state = self.router.db_for_write(Application)

        self.assertIsNone(state)

    @patch('juloserver.routing.router.transaction.get_connection')
    def test_no_auto_routing_if_setting_false(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = False
        instance = Application()
        instance._state.db = 'replica'
        state = self.router.db_for_write(Application)
        self.assertIsNone(state)

        instance._state.db = 'default'
        state = self.router.db_for_read(Application)
        self.assertIsNone(state)

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    def test_setting_mode_force(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = False
        read_state = self.router.db_for_read(Application)

        self.assertEqual('replica', read_state)

        instance = Application()
        instance._state.db = 'replica'
        write_state = self.router.db_for_write(Application, instance=instance)
        self.assertEqual('default', write_state)

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='partial')
    @patch('juloserver.routing.router.transaction.get_connection')
    def test_setting_mode_partial(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = False
        read_state = self.router.db_for_read(Application)
        self.assertIsNone(read_state)

        self.router.enable()
        read_state = self.router.db_for_read(Application)
        self.assertEqual('replica', read_state)

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    @patch('juloserver.routing.router.connections')
    def test_fallback_to_master_no_cache(self, mock_connections, mock_get_connection, mock_cache, *args):
        mock_connections['replica'].cursor.side_effect = Exception()
        mock_get_connection.return_value.in_atomic_block = False
        read_state = self.router.db_for_read(Application)
        self.assertEqual('default', read_state)
        mock_cache.return_value.set.assert_called_once_with(
            'JuloDbReplicaDbRouter:is_alive:replica',
            'dead',
            60
        )
        mock_connections['replica'].cursor.assert_called_once_with()

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    @patch('juloserver.routing.router.connections')
    def test_fallback_to_master_cache(self, mock_connections, mock_get_connection, mock_cache, *args):
        mock_cache.return_value.get.return_value = 'dead'
        mock_get_connection.return_value.in_atomic_block = False

        read_state = self.router.db_for_read(Application)
        self.assertEqual('default', read_state)
        mock_cache.return_value.get.assert_called_once()
        mock_cache.return_value.set.assert_not_called()
        mock_connections['replica'].cursor.assert_not_called()

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    @patch('juloserver.routing.router.connections')
    def test_db_transaction_case(self, mock_connections, mock_get_connection, mock_cache, *args):
        mock_get_connection.return_value.in_atomic_block = True

        read_state = self.router.db_for_read(Application)
        self.assertIsNone(read_state)
        mock_cache.return_value.get.assert_not_called()
        mock_connections['replica'].cursor.assert_not_called()

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    def test_not_route_read_if_not_master_connection(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = True
        instance = Application()
        instance._state.db = 'julorepayment_async_replica'
        read_state = self.router.db_for_read(Application, instance=instance)
        self.assertIsNone(read_state)

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    def test_force_route_write_if_read_from_replica(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = False
        instance = Application()
        instance._state.db = 'replica'
        write_state = self.router.db_for_write(Application, instance=instance)
        self.assertEqual('default', write_state)

    @override_settings(DATABASE_JULO_DB_REPLICA_ROUTING_MODE='force')
    @patch('juloserver.routing.router.transaction.get_connection')
    def test_allow_relation_setting_force(self, mock_get_connection, *args):
        mock_get_connection.return_value.in_atomic_block = False
        replica_instance = Application()
        replica_instance._state.db = 'replica'

        master_instance = Application()
        master_instance._state.db = 'default'

        other_instance = Application()
        other_instance._state.db = 'julorepayment_async_replica'

        ret_val = self.router.allow_relation(replica_instance, master_instance)
        self.assertTrue(ret_val)

        ret_val = self.router.allow_relation(master_instance, replica_instance)
        self.assertTrue(ret_val)

        ret_val = self.router.allow_relation(master_instance, master_instance)
        self.assertTrue(ret_val)

        ret_val = self.router.allow_relation(replica_instance, replica_instance)
        self.assertTrue(ret_val)

        ret_val = self.router.allow_relation(other_instance, replica_instance)
        self.assertIsNone(ret_val)

        ret_val = self.router.allow_relation(other_instance, master_instance)
        self.assertIsNone(ret_val)
