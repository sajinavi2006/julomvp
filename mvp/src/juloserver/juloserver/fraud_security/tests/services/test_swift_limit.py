import datetime
from unittest.mock import patch

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.ana_api.tests.factories import PdApplicationFraudModelResultFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.fraud_security.services import check_swift_limit_drainer
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    ApplicationHistoryFactory,
    LoanFactory,
    FeatureSettingFactory,
    CustomerFactory,
)


@patch('juloserver.fraud_security.services.logger')
class TestCheckSwiftLimitDrainer(TestCase):
    def setUp(self):
        self.mock_timezone_now = patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 1, 1, 12, 0, 0)
        )
        self.mock_timezone_now.start()

        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.mycroft_score = PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            customer_id=self.customer.id,
            pgood=0.8,
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_old=150, status_new=190
        )
        self.account_limit = AccountLimitFactory(account=self.application.account)
        self.feature_setting = FeatureSettingFactory(
            feature_name='swift_limit_drainer',
            parameters={'jail_days': 0},
        )

    def tearDown(self):
        super().tearDown()
        self.mock_timezone_now.stop()

    def test_for_mycroft_score_out_of_bounds_expect_false(self, *args):
        self.mycroft_score.update_safely(pgood=0.79)

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

    def test_for_application_status_not_x190_expect_false(self, *args):
        status_lookup_x120 = StatusLookup.objects.get(
            status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        )
        self.application.update_safely(application_status=status_lookup_x120)

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

    def test_for_multiple_loan_under_20_minutes_of_x190_expect_true(self, *args):
        for iteration in range(2):
            loan_object = LoanFactory(
                customer=self.application.customer,
                account=self.application.account,
                application=None,
                loan_amount=2000000,
            )
            loan_object.cdate = timezone.localtime(timezone.now()) + datetime.timedelta(minutes=10)
            loan_object.save()

        result = check_swift_limit_drainer(self.application, 1)
        self.assertTrue(result)

        # Transaction code should not affect result.
        result = check_swift_limit_drainer(self.application, 2)
        self.assertTrue(result)

    def test_for_multiple_loan_at_minute_11_and_21_minutes_of_x190_expect_false(self, *args):
        loan_specification = [
            {
                'cdate': timezone.localtime(timezone.now()) + datetime.timedelta(minutes=12),
            },
            {
                'cdate': timezone.localtime(timezone.now()) + datetime.timedelta(minutes=22),
            },
        ]

        for loan_fake in loan_specification:
            loan_object = LoanFactory(
                customer=self.application.customer,
                account=self.application.account,
                application=None,
                loan_amount=2000000,
            )
            loan_object.cdate = loan_fake['cdate']
            loan_object.save()

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

        # Transaction code should not affect result.
        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_first_loan_under_20_minutes_of_x190_and_heimdall_pass_and_transaction_type_pass_expect_true(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )

        result = check_swift_limit_drainer(self.application, 1)
        self.assertTrue(result)

    def test_for_first_loan_under_20_minutes_of_x190_and_heimdall_fail_and_transaction_type_pass_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.7
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

    def test_for_first_loan_under_20_minutes_of_x190_and_heimdall_pass_and_transaction_type_fail_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_first_loan_not_under_20_minutes_of_x190_and_heimdall_pass_and_transaction_type_pass_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        loan = LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )
        loan.cdate = timezone.localtime(timezone.now()) + datetime.timedelta(minutes=21)
        loan.save()

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

    def test_for_first_loan_under_10_minutes_of_x190_and_account_limit_exceed_5M_expect_true(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        self.account_limit.update_safely(set_limit=5100000)
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertTrue(result)

    def test_for_first_loan_under_10_minutes_of_x190_and_account_limit_not_exceed_5M_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        self.account_limit.update_safely(set_limit=4900000)
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_first_loan_not_under_10_minutes_of_x190_and_account_limit_exceed_5M_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        self.account_limit.update_safely(set_limit=5100000)
        loan = LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )
        loan.cdate = timezone.localtime(timezone.now()) + datetime.timedelta(minutes=11)
        loan.save()

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_first_loan_under_10_minutes_of_x190_and_loan_amount_exceed_4M_expect_true(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=4100000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertTrue(result)

    def test_for_first_loan_under_10_minutes_of_x190_and_loan_amount_not_exceed_4M_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=3900000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_first_loan_not_under_10_minutes_of_x190_and_loan_amount_exceed_4M_expect_false(
        self, *args
    ):
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.8
        )
        self.account_limit.update_safely(set_limit=5100000)
        loan = LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=41000000,
        )
        loan.cdate = timezone.localtime(timezone.now()) + datetime.timedelta(minutes=11)
        loan.save()

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)

    def test_for_feature_setting_is_inactive_expect_false(self, mock_logger, *args):
        self.feature_setting.update_safely(is_active=False)

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)
        mock_logger.info.assert_called_once_with(
            {
                'message': 'Cancel check because FeatureSetting us turned off.',
                'action': 'check_swift_limit_drainer',
                'application_id': self.application.id,
                'transaction_code': 2,
            }
        )

    def test_for_invalid_first_loan_multiple_loan_condition_skipped_expect_false(self, *args):
        loan_status_x218 = StatusLookup.objects.get(status_code=218)
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
            loan_status=loan_status_x218,
        )
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=2000000,
        )
        PdCreditModelResultFactory(
            application_id=self.application.id, customer_id=self.application.customer.id, pgood=0.7
        )

        result = check_swift_limit_drainer(self.application, 1)
        self.assertFalse(result)

    def test_for_missing_mycroft_expect_false(self, mock_logger, *args):
        self.mycroft_score.delete()
        LoanFactory(
            customer=self.application.customer,
            account=self.application.account,
            application=None,
            loan_amount=4100000,
        )

        result = check_swift_limit_drainer(self.application, 2)
        self.assertFalse(result)
        mock_logger.info.assert_called_once_with(
            {
                'message': 'Customer bypass swift limit drainer check due to missing mycroft record.',
                'action': 'check_swift_limit_drainer',
                'application_id': self.application.id,
                'transaction_code': 2,
            }
        )

    def test_for_more_than_one_mycroft_with_last_mycroft_meet_condition_expect_true(
        self, mock_logger, *args
    ):
        new_application = ApplicationJ1Factory(customer=self.customer)
        self.mycroft_score.update_safely(pgood=0.5)
        new_mycroft_score = PdApplicationFraudModelResultFactory(
            application_id=new_application.id,
            customer_id=self.customer.id,
            pgood=0.8,
        )
        new_application_history = ApplicationHistoryFactory(
            application_id=new_application.id, status_old=150, status_new=190
        )
        new_account_limit = AccountLimitFactory(account=new_application.account)

        # Meeting the condition of loan under 10 mins and loan exceed 4M amount.
        PdCreditModelResultFactory(
            application_id=new_application.id, customer_id=self.customer.id, pgood=0.8
        )
        LoanFactory(
            customer=self.customer,
            account=new_application.account,
            application=None,
            loan_amount=4100000,
        )

        result = check_swift_limit_drainer(new_application, 2)
        self.assertTrue(result)
        mock_logger.info.assert_called_once_with(
            {
                'message': 'Swift Limit Drainer detected.',
                'action': 'check_swift_limit_drainer',
                'application_id': new_application.id,
                'transaction_code': 2,
                'mycroft_score': 0.8,
                'application_status_code': 190,
                'loan_count': 1,
                'application_190_to_first_loan_time': 0.0,
                'heimdall_score': 0.8,
                'account_limit': 100000,
                'loan_amount': 4100000,
            }
        )
