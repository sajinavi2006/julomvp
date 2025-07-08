from django.test import TestCase
from unittest.mock import patch,call,ANY
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.autodebet.tasks import scheduled_pending_revocation_sweeper_subtask

class TestScheduledPendingRevocationSweeper(TestCase):
    def setUp(self): 
        self.account_application = AccountwithApplicationFactory()
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account_application,
            request_id='ATEST'
            )

    @patch('juloserver.autodebet.clients.AutodebetBCAClient.send_request')
    def test_scheduled_pending_revocation_sweeper_subtask(self,mock_send_request):
        customer_id_merchant = str(self.account_application.last_application.application_xid)
        mock_send_request_calls=[call("get", "/account-authorization/inquiry/%s" % customer_id_merchant, {},
        extra_headers={"customer_id_merchant": customer_id_merchant})]
        mock_send_request.side_effect = [(None,'Data pelanggan tidak ditemukan')]
        self.assertEqual(scheduled_pending_revocation_sweeper_subtask(self.autodebet_account.id),None)
        self.assertEqual(mock_send_request.call_count,1)
        mock_send_request.assert_has_calls(mock_send_request_calls)

    @patch('juloserver.autodebet.clients.AutodebetBCAClient.send_request')
    def test_scheduled_pending_revocation_sweeper_subtask_case_fail(self,mock_send_request):
        customer_id_merchant = str(self.account_application.last_application.application_xid)
        mock_send_request_calls=[call("get", "/account-authorization/inquiry/%s" % customer_id_merchant, {},
        extra_headers={"customer_id_merchant": customer_id_merchant}),
        call("delete", "/account-authorization/customer/%s/account-number/%s" %
        (customer_id_merchant, self.autodebet_account.db_account_no), {})]
        mock_send_request.side_effect = [({'skpr_active':[{'skpr_id':'TEST'}]},None),(None,ANY)]
        self.assertEqual(scheduled_pending_revocation_sweeper_subtask(self.autodebet_account.id),None)
        self.assertEqual(mock_send_request.call_count, 2)
        mock_send_request.assert_has_calls(mock_send_request_calls)
