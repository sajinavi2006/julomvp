from datetime import datetime
from unittest.mock import patch
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.constants import AutodebetStatuses, AutodebetVendorConst
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)


class TestSignalsAutodebet(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, fullname='customer name 1')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, status=AutodebetStatuses.PENDING_REGISTRATION, vendor=AutodebetVendorConst.BCA
        )

    def test_signals(self):
        with patch('juloserver.cfs.tasks.execute_after_transaction_safely') as mock_1:
            self.autodebet_account.update_safely(status=AutodebetStatuses.REGISTERED,
                                                 activation_ts=datetime(2022, 9, 30))
            mock_1.assert_called()

        with patch('juloserver.cfs.tasks.execute_after_transaction_safely') as mock_2:
            self.autodebet_account.update_safely(status=AutodebetStatuses.REGISTERED,
                                                 activation_ts=datetime(2022, 9, 30))
            mock_2.assert_not_called()
