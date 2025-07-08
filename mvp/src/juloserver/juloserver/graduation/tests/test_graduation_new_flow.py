import datetime
from unittest.mock import patch, call

import pytz
from django.utils import timezone
from django.test import TestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory, AccountPropertyFactory,
)
from juloserver.graduation.constants import GraduationType, GraduationFailureType, \
    GraduationRedisConstant
from juloserver.graduation.models import GraduationCustomerHistory2, CustomerGraduation, \
    CustomerGraduationFailure, AccountLimitHistory
from juloserver.graduation.tests.factories import CustomerGraduationFactory, \
    GraduationCustomerHistoryFactory, CustomerGraduationFailureFactory
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    CustomerFactory, StatusLookupFactory, ApplicationFactory,
)
from juloserver.graduation.tasks import automatic_customer_graduation_new_flow, \
    graduation_customer, manual_graduation_customer, notify_slack_graduation_customer


class TestGraduationCustomerClass(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name="graduation_new_flow",
            is_active=True,
        )
        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, status=self.status
        )
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.account_limit = AccountLimitFactory(
            account=self.account,
            available_limit=3000000,
            set_limit=10_000_000,
            max_limit=15_000_000,
        )
        self.fake_redis = MockRedisHelper()

    @patch('juloserver.graduation.tasks.automatic_customer_graduation_new_flow')
    @patch('juloserver.graduation.tasks.timezone')
    @patch('juloserver.graduation.tasks.get_redis_client')
    def test_handle_invalid_partition_date(self, mock_redis_client, mock_timezone,
                                           mock_automatic_customer_graduation_new_flow):
        mock_redis_client.return_value = self.fake_redis
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=8, day=6, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        mock_invalid_partition_date = mock_now.replace(
            year=2022, month=12, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )

        CustomerGraduationFactory(
            account_id=self.account.id,
            customer_id=self.customer.id,
            partition_date=mock_invalid_partition_date
        )
        graduation_customer()
        mock_automatic_customer_graduation_new_flow.delay.assert_not_called()

    @patch('juloserver.graduation.tasks.notify_slack_graduation_customer')
    @patch('juloserver.graduation.tasks.automatic_customer_graduation_new_flow')
    @patch('juloserver.graduation.tasks.timezone')
    @patch('juloserver.graduation.tasks.get_redis_client')
    def test_success(self, mock_redis_client, mock_timezone, mock_automatic_customer_graduation,
                     mock_notify_slack):
        mock_redis_client.return_value = self.fake_redis
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=8, day=6, hour=10, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        mock_valid_partition_date = mock_now.replace(
            year=2022, month=8, day=6, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )

        mock_time = timezone.localtime(datetime.datetime(
            year=2022, month=8, day=6, hour=9, minute=5, second=0, microsecond=0
        ))
        gc = CustomerGraduationFactory(
            account_id=self.account.id,
            customer_id=self.customer.id,
            partition_date=mock_valid_partition_date.date(),
            new_set_limit=12_000_000,
            new_max_limit=15_000_000,
            cdate=mock_time,
            udate=mock_time
        )
        graduation_customer()
        mock_automatic_customer_graduation.delay.assert_has_calls([call(
            gc.id, self.account.id, 12000000, 15000000, gc.graduation_flow
        )])
        max_graduation_id = self.fake_redis.get(GraduationRedisConstant.MAX_CUSTOMER_GRADUATION_ID)
        last_customer_graduation = CustomerGraduation.objects.order_by('id').last()
        self.assertEqual(max_graduation_id, str(last_customer_graduation.id))

    @patch('juloserver.graduation.tasks.notify_slack_graduation_customer')
    @patch('juloserver.graduation.tasks.automatic_customer_graduation_new_flow')
    @patch('juloserver.graduation.tasks.timezone')
    @patch('juloserver.graduation.tasks.get_redis_client')
    def test_process_graduation(self, mock_redis_client, mock_timezone, mock_automatic_customer_graduation,
                                mock_notify_slack):
        mock_redis_client.return_value = self.fake_redis
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=10, day=20, hour=15, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now

        mock_time = timezone.localtime(datetime.datetime(
            year=2022, month=10, day=20, hour=14, minute=5, second=0, microsecond=0
        ))
        customer_graduation = CustomerGraduationFactory(
            account_id=self.account.id,
            customer_id=self.customer.id,
            partition_date=datetime.datetime(year=2022, month=10, day=20).date(),
            new_set_limit=20000000,
            new_max_limit=30000000,
            cdate=mock_time,
            udate=mock_time
        )
        graduation_customer()
        mock_automatic_customer_graduation.delay.assert_has_calls([call(
            customer_graduation.id, self.account.id, 20000000, 30000000,
            customer_graduation.graduation_flow)]
        )

        # trigger process automatic graduation
        automatic_customer_graduation_new_flow(
            customer_graduation.id, self.account.id, 20000000, 30000000,
            customer_graduation.graduation_flow
        )
        graduation = GraduationCustomerHistory2.objects.all()[0]
        self.assertEqual(graduation.graduation_type, GraduationType.ENTRY_LEVEL)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.available_limit, 13000000)
        self.assertEqual(self.account_limit.set_limit, 20000000)
        self.assertEqual(self.account_limit.max_limit, 30000000)
        account_limit_histories = AccountLimitHistory.objects.filter(account_limit=self.account_limit)
        available_limit_his = account_limit_histories.get(field_name='available_limit')
        max_limit_his = account_limit_histories.get(field_name='max_limit')
        set_limit_his = account_limit_histories.get(field_name='set_limit')
        self.assertEqual(int(max_limit_his.value_new), self.account_limit.max_limit)
        self.assertEqual(int(set_limit_his.value_new), self.account_limit.set_limit)
        self.assertEqual(int(available_limit_his.value_new), self.account_limit.available_limit)

        # check valid cdate column
        graduation = CustomerGraduation.objects.get(id=customer_graduation.id)
        graduation.cdate.replace(tzinfo=pytz.UTC)
        graduation.udate.replace(tzinfo=pytz.UTC)
        self.assertEqual(graduation.cdate, mock_time)
        self.assertEqual(graduation.udate, mock_time)

    @patch('juloserver.graduation.tasks.notify_slack_graduation_customer')
    @patch('juloserver.graduation.tasks.automatic_customer_graduation_new_flow')
    @patch('juloserver.graduation.tasks.timezone')
    @patch('juloserver.graduation.tasks.get_redis_client')
    def test_process_graduation_failed(self, mock_redis_client, mock_timezone,
                                       mock_automatic_customer_graduation, mock_notify_slack):
        mock_redis_client.return_value = self.fake_redis
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=10, day=20, hour=15, minute=0, second=0, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now

        # inactive account
        customer = CustomerFactory()
        inactive_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive)
        account = AccountFactory(customer=customer, status=inactive_status_code)
        ApplicationFactory(customer=customer, account=account, status=StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        ))

        mock_time = timezone.localtime(datetime.datetime(
            year=2022, month=10, day=20, hour=14, minute=5, second=0, microsecond=0
        ))
        customer_graduation = CustomerGraduationFactory(
            account_id=account.id,
            customer_id=customer.id,
            partition_date=datetime.datetime(year=2022, month=10, day=20).date(),
            new_set_limit=20000000,
            new_max_limit=30000000,
            cdate=mock_time,
            udate=mock_time
        )

        # application deleted
        customer_2 = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        account_2 = AccountFactory(customer=customer_2, status=active_status_code)
        ApplicationFactory(customer=customer_2, account=account_2, status=StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        ), is_deleted=True)

        customer_graduation_2 = CustomerGraduationFactory(
            account_id=account_2.id,
            customer_id=customer_2.id,
            partition_date=datetime.datetime(year=2022, month=10, day=20).date(),
            new_set_limit=20000000,
            new_max_limit=30000000,
            cdate=mock_time,
            udate=mock_time
        )
        graduation_customer()
        mock_automatic_customer_graduation.delay.assert_has_calls(
            [
                call(customer_graduation.id, account.id, 20000000, 30000000,
                     customer_graduation.graduation_flow),
                call(customer_graduation_2.id, account_2.id, 20000000, 30000000,
                     customer_graduation.graduation_flow)
            ]
        )

        # trigger process automatic graduation
        automatic_customer_graduation_new_flow(
            customer_graduation.id, account.id, 20000000, 30000000,
            customer_graduation.graduation_flow
        )
        automatic_customer_graduation_new_flow(
            customer_graduation_2.id, account_2.id, 20000000, 30000000,
            customer_graduation.graduation_flow
        )
        graduation = GraduationCustomerHistory2.objects.all()
        self.assertEqual(len(graduation), 0)

        graduation_failure = CustomerGraduationFailure.objects.get(
            customer_graduation_id=customer_graduation.id
        )
        self.assertEqual(graduation_failure.type, GraduationFailureType.GRADUATION)
        self.assertEqual(graduation_failure.failure_reason, 'invalid account status')

        graduation_failure = CustomerGraduationFailure.objects.get(
            customer_graduation_id=customer_graduation_2.id
        )
        self.assertEqual(graduation_failure.type, GraduationFailureType.GRADUATION)
        self.assertEqual(graduation_failure.failure_reason, 'application is deleted')

    @patch('juloserver.graduation.tasks.get_slack_bot_client')
    @patch('juloserver.graduation.tasks.timezone')
    def test_notify_slack_graduation_customer(self, mock_timezone,
                                              mock_mock_get_slack_bot_client):
        cg = CustomerGraduationFactory()
        cg_2 = CustomerGraduationFactory()
        cg_3 = CustomerGraduationFactory()
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=10, day=20, hour=15, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC
        )
        mock_timezone.localtime.return_value = mock_now

        # time graduation
        mock_time = datetime.datetime(
            year=2022, month=10, day=20, hour=14, minute=5, second=0, microsecond=0, tzinfo=pytz.UTC
        )
        gch = GraduationCustomerHistoryFactory(
            customer_graduation_id=cg.id,
            account_id=AccountFactory().id,
            graduation_type=GraduationType.REGULAR_CUSTOMER,
        )
        gch.update_safely(cdate=mock_time, udate=mock_time)
        gf = CustomerGraduationFailureFactory(
            customer_graduation_id=cg_2.id,
            failure_reason='invalid account status',
            type=GraduationFailureType.GRADUATION,
        )
        gf.update_safely(cdate=mock_time, udate=mock_time)
        gf = CustomerGraduationFailureFactory(
            customer_graduation_id=cg_3.id,
            failure_reason='application is deleted',
            type=GraduationFailureType.GRADUATION,
        )
        gf.update_safely(cdate=mock_time, udate=mock_time)
        cgs = CustomerGraduation.objects.all()
        notify_slack_graduation_customer(cgs.first().id, cgs.last().id, 3)
        mock_mock_get_slack_bot_client.return_value.api_call.assert_called_with(
            "chat.postMessage",
            channel="#graduation_alerts_test",
            text='Hi <!here> - '
                 'Graduation run done:```\nTotal: 3\nSucceed count: 1\nFailed count:\n\t'
                 'invalid account status: 1\n\tapplication is deleted: 1\n```'
        )

    @patch('juloserver.graduation.tasks.automatic_customer_graduation_new_flow')
    @patch('juloserver.graduation.tasks.timezone')
    def test_process_manual_graduation(self, mock_timezone, mock_automatic_customer_graduation):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=8, day=6, hour=0, minute=0, second=0, microsecond=0, tzinfo=pytz.utc
        )
        mock_timezone.localtime.return_value = mock_now
        mock_valid_partition_date = mock_now.replace(
            year=2022, month=8, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=pytz.utc
        )
        customer_graduation = CustomerGraduationFactory(
            account_id=self.account.id,
            customer_id=self.customer.id,
            partition_date=mock_valid_partition_date.date(),
            new_set_limit=20000000,
            new_max_limit=30000000,
        )
        customer_graduation.cdate = mock_now
        customer_graduation.udate = mock_now
        customer_graduation.save()
        manual_graduation_customer(date_run_str='2021-01-01')  # invalid date
        mock_automatic_customer_graduation.delay.assert_not_called()

        manual_graduation_customer(date_run_str='2022-08-06')  # valid date
        mock_automatic_customer_graduation.delay.assert_called()

        manual_graduation_customer()  # valid date with mock today
        mock_automatic_customer_graduation.delay.assert_called()
