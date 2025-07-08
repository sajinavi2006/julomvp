import pytest
import socket
from test_fixtures import generate_initial_data, create_table_for_non_ops_schema
from mock import patch

def _disable_native_migrations():
    from django.conf import settings
    from pytest_django.migrations import DisableMigrations

    settings.MIGRATION_MODULES = DisableMigrations()

@pytest.fixture(scope='session')
def django_db_setup(
    request,
    django_test_environment,
    django_db_blocker,
    django_db_use_migrations,
    django_db_keepdb,
    django_db_modify_db_settings,
):
    """Top level fixture to ensure test databases are available"""
    from pytest_django.compat import setup_databases, teardown_databases
    from pytest_django.lazy_django import get_django_version

    setup_databases_args = {}

    if not django_db_use_migrations:
        _disable_native_migrations()

    if django_db_keepdb:
        if get_django_version() >= (1, 8):
            setup_databases_args['keepdb'] = True
        else:
            # Django 1.7 compatibility
            from pytest_django.db_reuse import monkey_patch_creation_for_db_reuse

            with django_db_blocker.unblock():
                monkey_patch_creation_for_db_reuse()

    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=pytest.config.option.verbose,
            interactive=False,
            **setup_databases_args
        )
        create_table_for_non_ops_schema()
        generate_initial_data()

    def teardown_database():
        with django_db_blocker.unblock():
            teardown_databases(
                db_cfg,
                verbosity=pytest.config.option.verbose,
            )

    if not django_db_keepdb:
        request.addfinalizer(teardown_database)

class BlockedSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise Exception("Network call blocked in unit tests")

@pytest.fixture(scope='session')
def pytest_configure(config):
    socket.socket = BlockedSocket


@pytest.fixture(autouse=True)
def skip_moengage_():
    with patch('juloserver.julo.signals.send_user_attributes_to_moengage_for_realtime_basis'):
        with patch('juloserver.julo.signals.'
                    'async_moengage_events_for_j1_loan_status_change'):
            with patch('juloserver.julo.signals.'
                        'update_moengage_for_application_status_change_event'):
                yield


# @pytest.fixture(autouse=True)
# def skip_pusdafil_():
#     with patch('juloserver.pusdafil.signals.bunch_of_loan_creation_tasks'):
#         with patch('juloserver.pusdafil.signals.task_report_new_loan_payment_creation'):
#             with patch('juloserver.pusdafil.signals.task_report_new_lender_registration'):
#                     yield


@pytest.fixture(autouse=True)
def skip_digisign_get_registration_status_code_request():
    with patch(
        'juloserver.digisign.services.digisign_client.DigisignClient.get_registration_status_code'
    ):
        yield {
            'success': False,
            'error': 'programming error'
        }


# for disabling signal
# @pytest.fixture(autouse=True) # Automatically use in tests.
# def mute_signals(request):
#     # Skip applying, if marked with `enabled_signals`
#     if 'enable_signals' in request.keywords:
#         return
#
#     signals = [
#         pre_save,
#         post_save,
#         pre_delete,
#         post_delete,
#         m2m_changed
#     ]
#     restore = {}
#     for signal in signals:
#         # Temporally remove the signal's receivers (a.k.a attached functions)
#         restore[signal] = signal.receivers
#         signal.receivers = []
#
#     def restore_signals():
#         # When the test tears down, restore the signals.
#         for signal, receivers in restore.items():
#             signal.receivers = receivers
#
#     # Called after a test has finished.
#     request.addfinalizer(restore_signals)
