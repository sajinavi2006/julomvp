from builtins import object
from django.test import TestCase
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, StatusLookup
from juloserver.paylater.services import process_suspend_account
from juloserver.paylater.models import AccountCreditHistory
from mock import patch


# Create your tests here.
class TestPaylaterServices(object):
    def test_suspend_account(self):

        class MockStatusLookup(object):
            status_code = 430
            status = "Suspended"

        class MockAccountCredit(object):
            id = 1
            customer_credit_limit = None
            account_credit_limit = 1000000
            available_credit_limit = 1000000
            account_credit_status = MockStatusLookup()

            def update_safely(self, **kwargs):
                return True

        class MockFeatureSettings(object):
            is_active = True
            feature_name = FeatureNameConst.SUSPEND_ACCOUNT_PAYLATER
            parameters = dict(suspend_delay=1)

        class MockAccountCreditHistory(object):
            id = 1

            def create(self, **kwargs):
                return True

        with patch.object(FeatureSetting.objects, 'get', return_value=MockFeatureSettings()):
            with patch.object(StatusLookup.objects, 'get', return_value=MockStatusLookup()):
                with patch.object(AccountCreditHistory.objects, 'create', return_value=MockAccountCreditHistory()):
                    account_credit = MockAccountCredit()

                    # Success Suspend
                    suspend = process_suspend_account(account_credit_limit=account_credit,
                                                      late_days=10,
                                                      grace_period_days=6)
                    assert suspend is True

                    # Failed Suspend
                    suspend = process_suspend_account(account_credit_limit=account_credit,
                                                      late_days=5,
                                                      grace_period_days=6)
                    assert suspend is False



