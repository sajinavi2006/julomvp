from django.test.testcases import TestCase
from django.db import DatabaseError
from mock import ANY, patch, Mock
from datetime import datetime

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
)
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
)
from juloserver.autodebet.constants import (
    AutodebetDanaResponseMessage,
    AutodebetVendorConst,
)
from juloserver.autodebet.services.dana_services import dana_autodebet_deactivation
from juloserver.autodebet.models import AutodebetAccount


class DanaDeactivationServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account,
            activation_ts=datetime(2023, 10, 10, 8, 0, 0),
            is_use_autodebet=True,
            is_deleted_autodebet=False,
            vendor=AutodebetVendorConst.DANA,
        )

    @patch(
        'juloserver.autodebet.tasks.send_slack_alert_dana_failed_subscription_and_deduction.delay'
    )
    def test_dana_deactivation_error_database(self, mock_send_slack_alert):
        # Mock the update_safely method to raise a DatabaseError
        with patch.object(
            AutodebetAccount, 'update_safely', side_effect=DatabaseError("Simulated database error")
        ):
            response, success = dana_autodebet_deactivation(self.account)

        self.assertEqual(response, AutodebetDanaResponseMessage.GENERAL_ERROR)
        self.assertFalse(success)
        mock_send_slack_alert.assert_called_once_with(
            error_message=ANY,
            account_id=self.account.id,
            application_id=self.account.last_application.id,
        )

    @patch(
        'juloserver.autodebet.tasks.send_slack_alert_dana_failed_subscription_and_deduction.delay'
    )
    def test_dana_deactivation_success(self, mock_send_slack_alert):
        response, status = dana_autodebet_deactivation(self.account)
        self.assertTrue(status)
        self.assertEqual(response, AutodebetDanaResponseMessage.SUCCESS_DEACTIVATION)
        mock_send_slack_alert.assert_not_called()

        response, status = dana_autodebet_deactivation(self.account)
        self.assertFalse(status)
        self.assertEqual(response, AutodebetDanaResponseMessage.AUTODEBET_NOT_FOUND)
        mock_send_slack_alert.assert_called_once_with(
            error_message=ANY,
            account_id=self.account.id,
            application_id=self.account.last_application.id,
        )
