from django.test import TestCase
from unittest.mock import patch, call, ANY
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.autodebet.tasks import scheduled_pending_revocation_sweeper_subtask
from juloserver.autodebet.constants import AutodebetStatuses
from juloserver.autodebet.tasks import suspend_autodebet_deactivated_account_task


class TestSuspendAutodebetAccountInvalidStatus(TestCase):
    def setUp(self):
        self.account_application = AccountwithApplicationFactory()

    def test_suspend_autodebet_deactivated_account_task(self):
        # test variable
        autodebet_status = AutodebetStatuses.REGISTERED

        # testing
        autodebet_account = AutodebetAccountFactory(
            account=self.account_application,
            status=autodebet_status,
            is_use_autodebet=True,
            is_suspended=False,
        )

        account_id = self.account_application.id
        new_status_id = 431
        suspend_autodebet_deactivated_account_task(account_id, new_status_id)
        autodebet_account.refresh_from_db()

        # should be suspended
        self.assertTrue(autodebet_account.is_suspended)

    def test_suspend_autodebet_deactivated_account_task_with_pending_registration(self):
        # test variable
        autodebet_status = AutodebetStatuses.PENDING_REGISTRATION

        # testing
        autodebet_account = AutodebetAccountFactory(
            account=self.account_application,
            status=autodebet_status,
            is_use_autodebet=True,
            is_suspended=False,
        )

        account_id = self.account_application.id
        new_status_id = 431
        suspend_autodebet_deactivated_account_task(account_id, new_status_id)
        autodebet_account.refresh_from_db()

        # should be suspended
        self.assertTrue(autodebet_account.is_suspended)

    def test_suspend_autodebet_deactivated_account_task_with_failed_status(self):
        # test variable
        autodebet_status = AutodebetStatuses.FAILED_REGISTRATION

        # testing
        autodebet_account = AutodebetAccountFactory(
            account=self.account_application,
            status=autodebet_status,
            is_use_autodebet=True,
            is_suspended=False,
        )

        account_id = self.account_application.id
        new_status_id = 431
        suspend_autodebet_deactivated_account_task(account_id, new_status_id)
        autodebet_account.refresh_from_db()

        # should not be suspended
        self.assertFalse(autodebet_account.is_suspended)
