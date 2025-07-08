import datetime
import math
from io import StringIO
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.db.models import signals
from django.test import TestCase
from django.utils import timezone
from factory import (
    Iterator,
    django,
)

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountStatusHistory
from juloserver.account.tests.factories import (
    AccountLookupFactory, AccountLimitFactory, AccountFactory, AccountPropertyFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.tests.factories import SkiptraceHistoryFactory
from juloserver.graduation.tests.factories import CustomerSuspendFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    StatusLookupFactory,
    LoanFactory,
    ApplicationFactory,
    WorkflowFactory,
    ProductLineFactory,
    PartnerFactory,
    AffordabilityHistoryFactory,
    ApplicationHistoryFactory,
    VoiceCallRecordFactory,
    CootekRobocallFactory,
    PaymentFactory,
)
from juloserver.sales_ops.constants import SalesOpsSettingConst
from juloserver.sales_ops.models import SalesOpsLineup, SalesOpsDailySummary, SalesOpsLineupHistory
from juloserver.sales_ops.services.sales_ops_services import InitSalesOpsLineup
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsLineupHistoryFactory,
    SalesOpsAgentAssignmentFactory,
)

PACKAGE_NAME = 'juloserver.sales_ops.services.sales_ops_services'


class TestInitSalesOpsLineup(TestCase):
    """
    The test case is not efficient, Don't focus on reuse the existing code.
    """
    def setUp(self):
        self.julo1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.julo1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.active_status_lookup = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.suspended_status_lookup = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.active_application_lookup = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.julo1_account_lookup = AccountLookupFactory(name='JULO1')
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters={
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_DAYS: 30,
            SalesOpsSettingConst.LINEUP_MAX_USED_LIMIT_PERCENTAGE: 0.9,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 720,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 2,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 15,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 168,
        })

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_valid_data(self, total):
        half_total = math.ceil(total)
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = []
        for account in accounts:
            account_limits.append(AccountLimitFactory(
                account=account,
                available_limit=500001,
                latest_credit_score=None,
                used_limit=5000)
            )
            ApplicationFactory(
                account=account, product_line=self.julo1_product_line, workflow=self.julo1_workflow,
                partner=None, application_status=self.active_application_lookup,
            )
            loan = LoanFactory(
                account=account, loan_status=StatusLookupFactory(status_code=250), loan_duration=1,
                fund_transfer_ts=timezone.localtime(
                    timezone.now() + datetime.timedelta(days=-30)
                ).date()
            )
            loan.payment_set.last().update_safely(
                paid_date='2019-02-02', payment_status=StatusLookupFactory(status_code=330)
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.active)
            for account in accounts[0:half_total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_invalid_data_available_limit(self, total):
        half_total = math.ceil(total)
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = [
            AccountLimitFactory(account=account, available_limit=500000, latest_credit_score=None)
            for account in accounts
        ]

        for account in accounts:
            ApplicationFactory(
                account=account, product_line=self.julo1_product_line, workflow=self.julo1_workflow,
                partner=None, application_status=self.active_application_lookup,
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.active)
            for account in accounts[0:half_total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_invalid_data_status_history(self, total):
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = [AccountLimitFactory(account=account, available_limit=500000, latest_credit_score=None) for account in accounts]

        for account in accounts:
            ApplicationFactory(
                account=account, product_line=self.julo1_product_line, workflow=self.julo1_workflow,
                partner=None, application_status=self.active_application_lookup,
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.inactive)
            for account in accounts[0:total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_invalid_data_julo_one_product_line(self, total):
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = []
        for account in accounts:
            account_limits.append(AccountLimitFactory(account=account, available_limit=500001, latest_credit_score=None))
            ApplicationFactory(
                account=account, product_line=None, workflow=self.julo1_workflow,
                partner=None, application_status=self.active_application_lookup,
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.active)
            for account in accounts[0:total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_invalid_data_julo_one_workflow(self, total):
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = []
        for account in accounts:
            account_limits.append(AccountLimitFactory(account=account, available_limit=500001, latest_credit_score=None))
            ApplicationFactory(
                account=account, product_line=self.julo1_product_line, workflow=None,
                partner=None, application_status=self.active_application_lookup
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.active)
            for account in accounts[0:total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    def generate_invalid_data_julo_one_partner(self, total):
        partner = PartnerFactory()
        accounts = AccountFactory.create_batch(total, status=self.active_status_lookup,
                                               account_lookup=self.julo1_account_lookup)
        account_limits = []
        for account in accounts:
            account_limits.append(AccountLimitFactory(account=account, available_limit=500001, latest_credit_score=None))
            ApplicationFactory(
                account=account, product_line=self.julo1_product_line, workflow=self.julo1_workflow,
                partner=partner, application_status=self.active_application_lookup
            )

        account_status_histories = [
            AccountStatusHistory.objects.create(account_id=account.id, status_new_id=AccountConstant.STATUS_CODE.active)
            for account in accounts[0:total]
        ]
        return accounts, account_limits, account_status_histories

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command(self, mock_tasks):
        self.generate_valid_data(10)
        self.generate_invalid_data_available_limit(5)
        self.generate_invalid_data_status_history(3)
        self.generate_invalid_data_julo_one_product_line(3)
        self.generate_invalid_data_julo_one_partner(3)
        self.generate_invalid_data_julo_one_workflow(3)

        # query['sql'] for query in self.captured_queries

        with self.assertNumQueries(45):
            InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(total, 10)
        daily_summary = SalesOpsDailySummary.objects.first()
        self.assertIsNotNone(daily_summary)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_with_suspended_users(self, mock_tasks):
        accounts, _, _ = self.generate_valid_data(10)
        CustomerSuspendFactory(customer_id=accounts[0].customer.id)
        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(9, total)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_with_sub_tasks(self, mock_tasks):
        self.generate_valid_data(10)
        self.generate_invalid_data_available_limit(5)
        self.generate_invalid_data_status_history(3)
        self.generate_invalid_data_julo_one_product_line(3)
        self.generate_invalid_data_julo_one_partner(3)
        self.generate_invalid_data_julo_one_workflow(3)

        InitSalesOpsLineup(query_limit=2).prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(total, 10)
        daily_summary = SalesOpsDailySummary.objects.first()
        self.assertEqual(daily_summary.total, 10)
        self.assertEqual(daily_summary.progress, 5)
        self.assertEqual(daily_summary.number_of_task, 5)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_with_update(self, mock_tasks):
        accounts, _, _ = self.generate_valid_data(10)
        invalid_accounts, _, _ = self.generate_invalid_data_available_limit(5)
        self.generate_invalid_data_status_history(3)

        active_lineup = SalesOpsLineupFactory(account=invalid_accounts[0], is_active=True)
        inactive_lineup = SalesOpsLineupFactory(account=accounts[0], is_active=False)
        SalesOpsLineupHistoryFactory(lineup_id=active_lineup.id, new_values={'is_active': True})

        with self.assertNumQueries(46):
            InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.filter(is_active=True).count()
        updated_active_lineup = SalesOpsLineup.objects.get(pk=inactive_lineup.id)
        updated_inactive_lineup = SalesOpsLineup.objects.get(pk=active_lineup.id)
        self.assertEqual(total, 10)
        self.assertTrue(updated_active_lineup.is_active)
        self.assertFalse(updated_inactive_lineup.is_active)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_more_than_query_limit(self, mock_tasks):
        self.generate_valid_data(10)
        self.generate_invalid_data_available_limit(5)
        self.generate_invalid_data_status_history(3)

        out = StringIO()
        InitSalesOpsLineup(query_limit=1).prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(total, 10)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_with_latest_info(self, mock_tasks):
        # make sure the auto increment doesn't affect the test
        LoanFactory.create_batch(2)
        AccountLimitFactory.create_batch(3, latest_credit_score=None)
        AccountPropertyFactory.create_batch(4)

        accounts, account_limits, _ = self.generate_valid_data(1)

        account = accounts[0]
        expected_account_limit = account_limits[0]
        expected_loan = LoanFactory(loan_disbursement_amount=10000,
                                    fund_transfer_ts=timezone.localtime(
                                        timezone.now() + datetime.timedelta(days=-30)
                                    ).date(),
                                    account=account)
        expected_account_property = AccountPropertyFactory(account=account)
        expected_application = ApplicationFactory(account=account)
        expected_application.application_status_id = 190
        expected_application.save()

        InitSalesOpsLineup().prepare_data()

        lineup = SalesOpsLineup.objects.last()
        self.assertEqual(lineup.latest_account_limit_id, expected_account_limit.id)
        self.assertEqual(lineup.latest_application_id, expected_application.id)
        self.assertEqual(lineup.latest_account_property_id, expected_account_property.id)
        self.assertEqual(lineup.latest_disbursed_loan_id, expected_loan.id)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_command_ignore_suspended_status(self, mock_tasks):
        accounts, _, _ = self.generate_valid_data(10)
        accounts[0].status = self.suspended_status_lookup
        accounts[0].save()
        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(9, total)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_generate_invalid_old_status_is_430(self, mock_tasks):
        accounts, account_limits, account_status_histories = self.generate_valid_data(10)
        first_account = accounts[0]
        AccountStatusHistory.objects.filter(
            account=first_account
        ).update(status_old=self.suspended_status_lookup)
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(10, total)

    @django.mute_signals(signals.pre_save)  # To mute Application signal
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_multiple_application(self, mock_tasks):
        accounts, _, _ = self.generate_valid_data(1)
        ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch(f'{PACKAGE_NAME}.timezone.now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_affordability_pass_check(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 1, tzinfo=timezone.utc)
        accounts, account_limits, _ = self.generate_valid_data(1)
        account = accounts[0]
        account_limit = account_limits[0]
        AccountPaymentFactory.create_batch(
            2,
            account=account,
            due_date=Iterator([datetime.date(2020, 2, 20), datetime.date(2020, 3, 20)]),
            due_amount=Iterator([100000, 120000]),
            principal_amount=Iterator([90000, 90000]),
            interest_amount=Iterator([10000, 0]),
            status_id=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE).status_code,
        )
        account_limit.update_safely(
            latest_affordability_history=AffordabilityHistoryFactory(affordability_value=100001)
        )

        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_invalid_account_limit_restriction(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 1, tzinfo=timezone.utc)
        accounts, account_limits, _ = self.generate_valid_data(1)
        account = accounts[0]
        account_limit = account_limits[0]
        AccountPaymentFactory.create_batch(
            2,
            account=account,
            due_date=Iterator([datetime.date(2020, 2, 20), datetime.date(2020, 3, 20)]),
            due_amount=Iterator([100000, 120000]),
            principal_amount=Iterator([90000, 90000]),
            interest_amount=Iterator([10000, 0]),
            status_id=StatusLookupFactory(
                status_code=PaymentStatusCodes.PAYMENT_NOT_DUE).status_code,
        )
        account_limit.update_safely(
            latest_affordability_history=AffordabilityHistoryFactory(affordability_value=100001),
            used_limit=10000
        )

        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch(f'{PACKAGE_NAME}.timezone.now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_affordability_fail_due_amount_less_than_principal(self, nock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 20, tzinfo=timezone.utc)
        accounts, account_limits, _ = self.generate_valid_data(1)
        account = accounts[0]
        account_limit = account_limits[0]
        AccountPaymentFactory.create_batch(
            3,
            account=account,
            due_date=Iterator([
                datetime.date(2020, 2, 20),
                datetime.date(2020, 2, 21),
                datetime.date(2020, 3, 20)
            ]),
            due_amount=Iterator([50000, 100000, 120000]),
            principal_amount=Iterator([90000, 90000, 100000]),
            interest_amount=Iterator([10000, 10000, 20000]),
            status_id=StatusLookupFactory(
                    status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
                ).status_code,
        )
        account_limit.update_safely(
            latest_affordability_history=AffordabilityHistoryFactory(affordability_value=100000)
        )

        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch(f'{PACKAGE_NAME}.timezone.now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_affordability_fail_check(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 20, tzinfo=timezone.utc)
        accounts, account_limits, _ = self.generate_valid_data(1)
        account = accounts[0]
        account_limit = account_limits[0]
        AccountPaymentFactory.create_batch(
            2,
            account=account,
            due_date=Iterator([datetime.date(2020, 2, 20), datetime.date(2020, 3, 20)]),
            due_amount=Iterator([100000, 99999]),
            principal_amount=Iterator([100000, 120000]),
            interest_amount=Iterator([1, 0]),
            status_id=StatusLookupFactory(
                status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
                ).status_code,
        )
        account_limit.update_safely(
            latest_affordability_history=AffordabilityHistoryFactory(affordability_value=100000)
        )

        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_collection_fail_check_dpd(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 15)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        next_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_not_due.status_code,
            due_date=datetime.date(2020, 2, 20)
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=Iterator([status_paid_on_time.status_code, status_not_due.status_code]),
            due_date=Iterator(['2020-01-20', '2020-03-20']),
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_collection_success_check_dpd(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 14)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        next_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_not_due.status_code,
            due_date=datetime.date(2020, 2, 20)
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=Iterator([status_paid_on_time.status_code, status_not_due.status_code]),
            due_date=Iterator(['2020-01-20', '2020-03-20']),
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_paid_prev_collection_success_check_no_call(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        last_paid_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_paid_on_time.status_code,
            due_date=datetime.date(2020, 1, 20), paid_date='2020-02-11'
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=status_not_due.status_code,
            due_date=Iterator(['2020-02-20', '2020-03-20']),
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_paid_prev_collection_success_check_pass_date(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 12)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        last_paid_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_paid_on_time.status_code,
            due_date=datetime.date(2020, 1, 20), paid_date='2020-02-11'
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=status_not_due.status_code,
            due_date=Iterator(['2020-02-20', '2020-03-20']),
        )
        SkiptraceHistoryFactory(
            account_payment=last_paid_account_payment,
            source='Intelix',
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_paid_prev_collection_fail_check_skiptrace_call(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        last_paid_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_paid_on_time.status_code,
            due_date=datetime.date(2020, 1, 20), paid_date='2020-02-11'
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=status_not_due.status_code,
            due_date=Iterator(['2020-02-20', '2020-03-20']),
        )
        SkiptraceHistoryFactory(
            account_payment=last_paid_account_payment,
            source='Intelix',
            payment=PaymentFactory(loan=LoanFactory()),
            application=ApplicationFactory(account=accounts[0]),
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_paid_prev_collection_fail_check_nexmo_call(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        last_paid_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_paid_on_time.status_code,
            due_date=datetime.date(2020, 1, 20), paid_date='2020-02-11'
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=status_not_due.status_code,
            due_date=Iterator(['2020-02-20', '2020-03-20']),
        )
        VoiceCallRecordFactory(
            account_payment=last_paid_account_payment,
            application=ApplicationFactory(account=accounts[0])
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch.object(timezone, 'now')
    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_has_paid_prev_collection_fail_check_cootek_call(self, mock_tasks, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        status_not_due = StatusLookupFactory(status_code=310)
        status_paid_on_time = StatusLookupFactory(status_code=330)
        accounts, _, _ = self.generate_valid_data(1)
        last_paid_account_payment = AccountPaymentFactory(
            account=accounts[0], status_id=status_paid_on_time.status_code,
            due_date=datetime.date(2020, 1, 20), paid_date='2020-02-11'
        )
        AccountPaymentFactory.create_batch(
            2,
            account=accounts[0],
            status_id=status_not_due.status_code,
            due_date=Iterator(['2020-02-20', '2020-03-20']),
        )
        CootekRobocallFactory(
            account_payment=last_paid_account_payment,
            task_status='finished',
            call_status='completed',
        )

        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_sales_ops_lineup_restriction(self, mock_tasks):
        accounts, _, _ = self.generate_valid_data(1)
        self.application = ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        #  case invalid lineup with invalid setting `lineup_min_available_days`
        prev_30_days = timezone.localtime(
            timezone.now().replace(hour=23, minute=59, second=59)
        ) - relativedelta(days=30)
        with patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = prev_30_days
            self.application_history = ApplicationHistoryFactory(
                application_id=self.application.id,
                status_old=150,
                status_new=190,
                cdate=prev_30_days
            )
        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(0, total)

        #  case valid lineup with valid setting `lineup_min_available_days`
        prev_31_days = timezone.localtime(timezone.now()) - relativedelta(days=31)
        with patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = prev_31_days
            self.application_history.cdate = prev_31_days
            self.application_history.save()
            self.application_history.refresh_from_db()
        InitSalesOpsLineup().prepare_data()

        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_block_feature_expiring(self, mock_tasks):
        # generate a valid sales ops row
        accounts, _, _ = self.generate_valid_data(1)
        ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

        # test blocking expiration
        lineup = SalesOpsLineup.objects.first()

        # case not expired
        the_future = timezone.localtime(timezone.now()) + datetime.timedelta(days=1)
        lineup.inactive_until = the_future
        lineup.is_active = False
        lineup.save()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, False)

        # case expired
        the_past = timezone.localtime(timezone.now()) - datetime.timedelta(days=1)
        lineup.inactive_until = the_past
        lineup.is_active = False
        lineup.save()

        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, True)
        qs = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).last()
        self.assertEqual(qs.old_values, {"is_active": False})
        self.assertEqual(qs.new_values, {"is_active": True})

    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_block_rpc_delay(self, mock_tasks):
        # generate a valid sales ops row
        accounts, _, _ = self.generate_valid_data(1)
        ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

        # test blocking rpc_delay
        rpc_delay = timezone.localtime(timezone.now()) - datetime.timedelta(hours=720)
        lineup = SalesOpsLineup.objects.first()
        rpc_agent_assignment = SalesOpsAgentAssignmentFactory(lineup=lineup, is_rpc=True)
        lineup.latest_rpc_agent_assignment = rpc_agent_assignment
        lineup.save()

        # case not expired
        rpc_agent_assignment.completed_date = rpc_delay + datetime.timedelta(days=2)
        rpc_agent_assignment.save()
        rpc_agent_assignment.refresh_from_db()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, True)

        # case expired
        rpc_agent_assignment.completed_date = rpc_delay - datetime.timedelta(days=2)
        rpc_agent_assignment.save()
        rpc_agent_assignment.refresh_from_db()
        lineup.is_active = False
        lineup.save()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, True)

        qs = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).last()
        self.assertEqual(qs.old_values, {"is_active": False})
        self.assertEqual(qs.new_values, {"is_active": True})

    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_block_non_rpc_delay(self, mock_tasks):
        # generate a valid sales ops row
        accounts, _, _ = self.generate_valid_data(1)
        ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

        # test blocking rpc_delay
        non_rpc_delay = timezone.localtime(timezone.now()) - datetime.timedelta(hours=15)
        lineup = SalesOpsLineup.objects.first()
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=lineup.id, is_rpc=False, non_rpc_attempt=1
        )
        lineup.latest_agent_assignment_id = agent_assignment.id
        lineup.save()

        # case not expired
        agent_assignment.completed_date = non_rpc_delay + datetime.timedelta(days=2)
        agent_assignment.save()
        agent_assignment.refresh_from_db()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, False)

        # case expired
        agent_assignment.completed_date = non_rpc_delay - datetime.timedelta(days=2)
        agent_assignment.save()
        agent_assignment.refresh_from_db()
        lineup.is_active = False
        lineup.save()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, True)

        qs = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).last()
        self.assertEqual(qs.old_values, {"is_active": False})
        self.assertEqual(qs.new_values, {"is_active": True})

    @patch(f'{PACKAGE_NAME}.tasks.sync_sales_ops_lineup.delay')
    def test_block_non_rpc_final_delay(self, mock_tasks):
        # generate a valid sales ops row
        accounts, _, _ = self.generate_valid_data(1)
        ApplicationFactory(
            account=accounts[0],
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.julo1_product_line,
            workflow=self.julo1_workflow,
            partner=None,
        )
        InitSalesOpsLineup().prepare_data()
        total = SalesOpsLineup.objects.count()
        self.assertEqual(1, total)

        # test blocking rpc_delay
        non_rpc_final_delay = timezone.localtime(timezone.now()) - datetime.timedelta(hours=168)
        lineup = SalesOpsLineup.objects.first()
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=lineup.id, is_rpc=False, non_rpc_attempt=4
        )
        lineup.latest_agent_assignment_id = agent_assignment.id
        lineup.save()

        # case not expired
        agent_assignment.completed_date = non_rpc_final_delay + datetime.timedelta(days=2)
        agent_assignment.save()
        agent_assignment.refresh_from_db()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, False)

        # case expired
        agent_assignment.completed_date = non_rpc_final_delay - datetime.timedelta(days=2)
        agent_assignment.save()
        agent_assignment.refresh_from_db()
        lineup.is_active = False
        lineup.save()
        InitSalesOpsLineup().prepare_data()
        lineup.refresh_from_db()
        self.assertEqual(lineup.is_active, True)

        qs = SalesOpsLineupHistory.objects.filter(lineup_id=lineup.id).last()
        self.assertEqual(qs.old_values, {"is_active": False})
        self.assertEqual(qs.new_values, {"is_active": True})
