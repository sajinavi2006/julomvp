from unittest.mock import patch

import pytz
from django.test.testcases import TestCase
from django.conf import settings

from datetime import datetime

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    LoanDelayDisbursementFeeFactory,
    DeviceFactory,
)

from juloserver.account.tests.factories import (
    AccountFactory,
)

from juloserver.loan.services.delayed_disbursement_related import (
    process_delayed_disbursement_cashback, check_daily_monthly_limit, DelayedDisbursementStatus,
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.services.use_cases import send_moengage_for_cashback_delay_disbursement

class TestProcessDelayedDisbursementCashback(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

    def test_loan_does_not_have_dd(self):
        dt = '2024-10-09 10:00:00'
        fund_transfer_ts = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')

        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            fund_transfer_ts=fund_transfer_ts,
        )

        success = process_delayed_disbursement_cashback(self.loan)
        self.assertEqual(success, False)

    def test_loan_not_eligible_for_cashback(self):
        tz = pytz.timezone(settings.TIME_ZONE)

        dt = '2024-10-09 10:05:00'
        fund_transfer_ts = tz.localize(datetime.strptime(dt, '%Y-%m-%d %H:%M:%S'))

        sphp_dt = '2024-10-09 10:00:00'
        agreement_timestamp = tz.localize(datetime.strptime(sphp_dt, '%Y-%m-%d %H:%M:%S'))

        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            fund_transfer_ts=fund_transfer_ts,
        )

        self.dd = LoanDelayDisbursementFeeFactory(
            loan=self.loan,
            threshold_time=600,
            agreement_timestamp=agreement_timestamp,
        )

        success = process_delayed_disbursement_cashback(self.loan)
        self.assertEqual(success, False)

    def test_loan_cashback_disbursed(self):
        tz = pytz.timezone(settings.TIME_ZONE)

        dt = '2024-10-09 10:15:00'
        fund_transfer_ts = tz.localize(datetime.strptime(dt, '%Y-%m-%d %H:%M:%S'))

        sphp_dt = '2024-10-09 10:00:00'
        agreement_timestamp = tz.localize(datetime.strptime(sphp_dt, '%Y-%m-%d %H:%M:%S'))

        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            fund_transfer_ts=fund_transfer_ts,
        )

        self.dd = LoanDelayDisbursementFeeFactory(
            loan=self.loan,
            cashback=25_000,
            threshold_time=600,
            agreement_timestamp=agreement_timestamp,
        )

        # assert success process
        success = process_delayed_disbursement_cashback(self.loan)
        self.assertEqual(success, True)

        # assert dd status updated to claimed
        self.dd.refresh_from_db()
        self.assertEqual(self.dd.status, 'CLAIMED')

        # assert cashback balance
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.wallet_balance_available, self.dd.cashback)

class TestSendMoengageForCashbackDelayDisbursement(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(account=self.account)

    @patch('juloserver.moengage.services.data_constructors.timezone')
    @patch('juloserver.moengage.services.data_constructors.Application.objects.filter')
    @patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_moengage_for_cashback_delay_disbursement(self, mock_send_to_moengage, mock_application, mock_timezone):
        mock_application.return_value.last.return_value = self.loan.application
        mock_application.device = self.loan.application.device
        mock_application.device.gcm_reg_id = self.loan.application.device.gcm_reg_id
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.localtime.return_value = mock_now
        formatted_time = mock_now.strftime('%Y-%m-%d %H:%M:%S')

        send_moengage_for_cashback_delay_disbursement(loan_id=self.loan.id)
        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
            loan_id=self.loan.id
        ).last()

        expected_event_attribute = {
            "type": "event",
            "customer_id": self.loan.customer.id,
            "device_id": self.loan.application.device.gcm_reg_id,
            "actions": [{
                "action": MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
                "attributes": {
                    'customer_id': self.loan.customer.id,
                    'event_triggered_date': formatted_time,
                    'account_id': self.loan.account.id,
                    'loan_id': self.loan.id,
                    'cdate': datetime.strftime(self.loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ"),

                },
                "platform": "ANDROID",
                "current_time": mock_now.timestamp(),
                "user_timezone_offset": mock_now.utcoffset().seconds,

            }]
        }
        expected_user_attributes = {
            'type': 'customer',
            'customer_id': self.loan.customer.id,
            'attributes':
                {
                    'customer_id': self.loan.customer.id,
                    'platforms': [{
                        'platform': 'ANDROID',
                        'active': 'true',
                    }],
                    'fullname_with_title': self.loan.application.fullname_with_title

                }
        }
        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.id(me_upload.id,[expected_user_attributes,expected_event_attribute])

class TestCheckDailyLimitAndMonthlyLimit(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.device = DeviceFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(account=self.account)
        self.loan_delay_disbursement= LoanDelayDisbursementFeeFactory(loan=self.loan)

    @patch('django.utils.timezone.now')
    def test_monthly_limit_available(self,
                                     mock_timezone):
        monthly_limit = 3
        daily_limit = 0
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.return_value = mock_now

        self.loan_delay_disbursement.udate = mock_now
        self.loan_delay_disbursement.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
        self.loan_delay_disbursement.save()

        result = check_daily_monthly_limit(self.loan.customer.id, monthly_limit, daily_limit)
        self.assertEqual(result,True)

    @patch('django.utils.timezone.now')
    def test_monthly_limit_exceeded(self,
                                     mock_timezone,
                                     ):
        monthly_limit = 1
        daily_limit = 0
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.return_value = mock_now

        self.loan_delay_disbursement.udate = mock_now
        self.loan_delay_disbursement.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
        self.loan_delay_disbursement.save()

        result = check_daily_monthly_limit(self.loan.customer.id, monthly_limit, daily_limit)
        self.assertEqual(result, False)

    @patch('django.utils.timezone.now')
    def test_monthly_limit_and_daily_limit_zero(self,
                                         mock_timezone
                                         ):
        monthly_limit = 0
        daily_limit = 0
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.return_value = mock_now

        self.loan_delay_disbursement.udate = mock_now
        self.loan_delay_disbursement.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
        self.loan_delay_disbursement.save()

        result = check_daily_monthly_limit(self.loan.customer.id, monthly_limit, daily_limit)
        self.assertEqual(result, True)

    @patch('django.utils.timezone.now')
    def test_daily_limit_available(self,
                                     mock_timezone,

                                     ):
        monthly_limit = 0
        daily_limit = 3
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.return_value = mock_now

        self.loan_delay_disbursement.udate = mock_now
        self.loan_delay_disbursement.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
        self.loan_delay_disbursement.save()

        result = check_daily_monthly_limit(self.loan.customer.id, monthly_limit, daily_limit)
        self.assertEqual(result,True)

    @patch('django.utils.timezone.now')
    def test_daily_limit_exceeded(self,
                                     mock_timezone,
                                     ):
        monthly_limit = 0
        daily_limit = 1
        mock_now = datetime(2024, 10, 10, 12, 23, 45, tzinfo=pytz.UTC)
        mock_timezone.return_value = mock_now

        self.loan_delay_disbursement.udate = mock_now
        self.loan_delay_disbursement.status = DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_CLAIMED
        self.loan_delay_disbursement.save()

        result = check_daily_monthly_limit(self.loan.customer.id, monthly_limit, daily_limit)
        self.assertEqual(result, False)
