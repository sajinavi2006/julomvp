from django.test.testcases import TestCase
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.autodebet.constants import AutodebetStatuses
from juloserver.autodebet.models import AutodebetAccount
from juloserver.julo.tests.factories import StatusLookupFactory
from juloserver.julo.management.commands.suspend_autodebet_customer_431 import (
    suspend_autodebet_for_account_431,
)


class TestCommandSuspendAutodebetAccountStatus(TestCase):
    def setUp(self):
        self.autodebet_accounts = []

        # t testing data and result mapping
        self.test_result_dict = {
            431: {
                "autodebet_status": AutodebetStatuses.REGISTERED,
                "is_use_autodebet": True,
                "is_suspended": False,
                "status_id": 431,
                "result": True,
            },
            420: {
                "autodebet_status": AutodebetStatuses.REGISTERED,
                "is_use_autodebet": True,
                "is_suspended": False,
                "status_id": 420,
                "result": False,  # status_id not met
            },
            440: {
                "autodebet_status": AutodebetStatuses.FAILED_REGISTRATION,
                "is_use_autodebet": True,
                "is_suspended": False,
                "status_id": 440,
                "result": False,  # autodebet_status not met
            },
            460: {
                "autodebet_status": AutodebetStatuses.PENDING_REGISTRATION,
                "is_use_autodebet": True,
                "is_suspended": True,
                "status_id": 460,
                "result": True,  # already suspended keeps to be True
            },
            460: {
                "autodebet_status": AutodebetStatuses.FAILED_REGISTRATION,
                "is_use_autodebet": True,
                "is_suspended": False,
                "status_id": 460,
                "result": False,  # status_id and autodebet_status not met
            },
        }

        # populate testing data
        for _, test_data in self.test_result_dict.items():
            account = AccountwithApplicationFactory(
                status=StatusLookupFactory(status_code=test_data["status_id"]),
            )
            autodebet_account = AutodebetAccountFactory(
                status=test_data["autodebet_status"],
                is_use_autodebet=test_data["is_use_autodebet"],
                is_suspended=test_data["is_suspended"],
                account=account,
            )
            self.autodebet_accounts.append(autodebet_account)

    def test_suspend_autodebet_for_account_431(self):
        # process all data
        suspend_autodebet_for_account_431()

        # assert results for all test data
        autodebet_accounts = AutodebetAccount.objects.all()
        for autodebet_account in autodebet_accounts.iterator():
            status_key = autodebet_account.account.status_id
            self.assertEqual(
                autodebet_account.is_suspended, self.test_result_dict[status_key]["result"]
            )
