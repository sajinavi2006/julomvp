from datetime import timedelta
import datetime
from freezegun import freeze_time

from django.conf import settings
from django.utils import timezone
from unittest.mock import (
    patch,
    MagicMock,
)
from django.test import TestCase
from factory import Iterator

from juloserver.cfs.tasks import update_graduate_entry_level
from juloserver.graduation.services import update_account_limit_graduation
from juloserver.graduation.tasks import (
    evaluate_less_risky_customers_graduation,
    evaluate_risky_customers_graduation,
    regular_customer_graduation,
    refresh_materialized_view_graduation_regular_customer_accounts,
    automatic_customer_graduation,
    process_graduation,
    get_valid_approval_account_ids,
    run_downgrade_customers,
    run_downgrade_account,
    retry_downgrade_account,
    scan_customer_suspend_unsuspend_for_sending_to_me,
    notify_slack_downgrade_customer,
)
from juloserver.graduation.models import (
    CustomerGraduationFailure,
    DowngradeCustomerHistory,
    GraduationCustomerHistory2,
)
from juloserver.graduation.constants import (
    FeatureNameConst as GraduationFeatureName,
    RiskCategory,
    GraduationType,
    GraduationFailureType,
    GraduationFailureConst,
)
from juloserver.graduation.tests.factories import (
    CustomerGraduationFactory,
    CustomerGraduationFailureFactory,
    CustomerSuspendHistoryFactory,
    DowngradeCustomerHistoryFactory,
    GraduationCustomerHistoryFactory,
)
from juloserver.account.models import (
    AccountPropertyHistory,
    AccountProperty,
    AccountLimitHistory,
    AccountLimit,
)
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    CreditLimitGenerationFactory,
    AccountPropertyFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    ApplicationFactory, FeatureSettingFactory, ApplicationHistoryFactory, CleanLoanFactory,
    PaymentFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory, InitialFDCInquiryLoanDataFactory, LoanFactory,
)
from juloserver.cfs.tests.factories import PdClcsPrimeResultFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import (
    WorkflowConst, FeatureNameConst,
)
from juloserver.graduation.tests.factories import GraduationRegularCustomerAccountsFactory


class TestRefreshMaterializedViewGraduationAccounts(TestCase):
    @patch('juloserver.graduation.tasks.connection')
    def test_execute(self, mock_connection):
        self.feature_setting = FeatureSettingFactory(
            feature_name="graduation_regular_customer",
            is_active=True,
            parameters={
                "graduation_rule": {
                    "max_grace_payment": 3,
                    "max_late_payment": 1,
                    "max_not_paid_payment": 0,
                    "min_percentage_paid_per_credit_limit": 50,
                    "min_paid_off_loan": 1,
                },
            }
        )
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.__enter__.return_value = mock_cursor

        refresh_materialized_view_graduation_regular_customer_accounts()

        mock_cursor.execute.assert_called_once_with(
            'REFRESH MATERIALIZED VIEW ops.graduation_regular_customer_accounts'
        )


class TestValidApprovalApplication(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='John Doe 1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.update_safely(application_status_id=190)
        self.today = timezone.localtime(timezone.now()).date()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=190
        )

    @patch('juloserver.graduation.tasks.logger')
    def test_valid_approval_application(self, mock_logger):
        self.application_history.update_safely(cdate=self.today - timedelta(days=180))
        account_ids = get_valid_approval_account_ids([self.account.id], False)
        self.assertEqual(account_ids, [self.account.id])

        self.application_history.update_safely(cdate=self.today - timedelta(days=5))
        account_ids = get_valid_approval_account_ids([self.account.id], False)
        self.assertEqual(account_ids, [])

        mock_logger.info.assert_called_once_with({
            'invalid_account_ids': [self.account.id],
            'function': 'get_valid_approval_account_ids',
            'is_first_graduate': False
        })


class TestGraduationEvaluation(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='John Doe'
        )
        self.client.force_login(self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=2_000_000,
            set_limit=1100000,
            used_limit=100000
        )
        log = '{"simple_limit": 9944172.0, ' \
              '"max_limit (pre-matrix)": 10000000, ' \
              '"set_limit (pre-matrix)": 8000000, ' \
              '"limit_adjustment_factor": 0.8, ' \
              '"reduced_limit": 7955337.0}'
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            max_limit=10000000,
            set_limit=self.account_limit.set_limit,
            log=log
        )
        self.account_property = AccountPropertyFactory(
            account=self.account
        )
        self.feature_setting_2 = FeatureSettingFactory(
            feature_name='graduation_fdc_check',
            is_active=True
        )
        self.fdc_inquiry = FDCInquiryFactory(application_id=self.application.id)
        self.fdc_inquiry_loan = FDCInquiryLoanFactory.create_batch(
            5, fdc_inquiry_id=self.fdc_inquiry.id, is_julo_loan=False,
            dpd_terakhir=Iterator([1, 1, 1, 1, 1]), status_pinjaman='Outstanding'
        )
        self.init_fdc_inquiry_loan_data = InitialFDCInquiryLoanDataFactory(
            fdc_inquiry=self.fdc_inquiry, initial_outstanding_loan_count_x100=10
        )

    @patch('juloserver.graduation.tasks.regular_customer_graduation.delay')
    def test_evaluate_less_risky_customer_graduation(self, mock_regular_customer_graduation):
        self.account_limit.set_limit = 100000
        self.account_limit.used_limit = 100000
        self.account_limit.save()

        # can't pass with limit utilization > 0.9, will do evaluate on risky case
        is_success = evaluate_less_risky_customers_graduation([self.account.id])
        self.assertFalse(is_success)

        # will pass with limit utilization < 0.9
        self.account_limit.used_limit = 100000
        self.account_limit.set_limit = 1000000
        self.account_limit.save()
        evaluate_less_risky_customers_graduation([self.account.id])
        mock_regular_customer_graduation.assert_called_once()

    @patch('juloserver.graduation.tasks.regular_customer_graduation.delay')
    def test_evaluate_risky_customer_graduation(self, mock_regular_customer_graduation):
        self.pd_clcs = PdClcsPrimeResultFactory(
            customer_id=self.customer.id, clcs_prime_score=0.5
        )

        # can't pass with clcs score <= 0.95
        is_success = evaluate_risky_customers_graduation([self.account.id])
        self.assertFalse(is_success)

        # will pass with clcs score >= 0.95
        self.pd_clcs = PdClcsPrimeResultFactory(
            customer_id=self.customer.id, clcs_prime_score=0.95
        )
        self.pd_clcs.save()
        evaluate_risky_customers_graduation([self.account.id])
        mock_regular_customer_graduation.assert_called_once_with([self.account.id], RiskCategory.RISKY)

    @patch('juloserver.graduation.tasks.automatic_customer_graduation.delay')
    def test_function_called_automatic_customer_graduation(self, mock_automatic_graduation):
        regular_customer_graduation.delay([self.account.id], RiskCategory.LESS_RISKY)
        mock_automatic_graduation.assert_called_once_with(self.account.id, RiskCategory.LESS_RISKY)

    @patch('juloserver.graduation.tasks.logger')
    def test_logger_automatic_customer_graduation(self, mock_logger):
        regular_customer_graduation.delay([self.account.id], RiskCategory.LESS_RISKY)
        mock_logger.info.assert_called_once_with({
            'action': 'regular_customer_graduation',
            'account_ids': [self.account.id],
            'risk_category': RiskCategory.LESS_RISKY
        })

    @patch('juloserver.graduation.tasks')
    def test_customer_automatic_graduation_less_risky(self, mock_update_post_graduation):
        self.account_limit.set_limit = 500000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.LESS_RISKY)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 1000000)

        self.account_limit.update_safely(set_limit=10000000)
        automatic_customer_graduation(self.account.id, RiskCategory.LESS_RISKY)
        mock_update_post_graduation.assert_not_called()
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 10000000)

    @patch('juloserver.graduation.tasks')
    def test_customer_automatic_graduation_risky(self, mock_update_post_graduation):
        self.account_limit.set_limit = 1100000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.RISKY)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 2100000)

        self.account_limit.set_limit = 800000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.RISKY)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 1000000)

        self.account_limit.set_limit = 1000000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.RISKY)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 2000000)

        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.RISKY)
        mock_update_post_graduation.assert_not_called()
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 10000000)

        self.account_limit.set_limit = 15000000
        self.account_limit.save()
        automatic_customer_graduation(self.account.id, RiskCategory.RISKY)
        self.account_limit.refresh_from_db()
        self.assertEqual(self.account_limit.set_limit, 10000000)

    def test_creation_graduation_regular_customer_history(self):
        automatic_customer_graduation(self.account.id, RiskCategory.LESS_RISKY)
        graduation_history_obj = GraduationCustomerHistory2.objects.get(account_id=self.account.id)
        self.assertIsNotNone(graduation_history_obj)
        self.assertEqual(graduation_history_obj.graduation_type, GraduationType.REGULAR_CUSTOMER)

    def test_creation_account_property_history(self):
        automatic_customer_graduation(self.account.id, RiskCategory.LESS_RISKY)
        account_property_history_obj = AccountPropertyHistory.objects.get(
            account_property=self.account_property)
        today = timezone.localtime(timezone.now()).date().strftime("%Y-%m-%d")
        self.assertIsNotNone(account_property_history_obj)
        self.assertEqual(account_property_history_obj.field_name, 'last_graduation_date')
        self.assertEqual(account_property_history_obj.value_new, today)
        self.assertEqual(account_property_history_obj.value_old, None)

    def test_update_of_graduation_customer_history(self):
        automatic_customer_graduation(self.account.id, RiskCategory.LESS_RISKY)
        today = timezone.localtime(timezone.now()).date()
        account_property_obj = AccountProperty.objects.get(account_id=self.account.id)
        self.assertIsNotNone(account_property_obj)
        self.assertEqual(account_property_obj.last_graduation_date, today)
        graduation_customer_history = GraduationCustomerHistory2.objects.get(account_id=self.account.id)
        self.assertIsNotNone(graduation_customer_history)
        self.assertEqual(graduation_customer_history.cdate.date(), today)
        account_limit_histories = AccountLimitHistory.objects.filter(account_limit=self.account_limit)
        available_limit_his = account_limit_histories.get(field_name='available_limit')
        max_limit_his = account_limit_histories.get(field_name='max_limit')
        set_limit_his = account_limit_histories.get(field_name='set_limit')
        self.assertEqual(graduation_customer_history.available_limit_history_id, available_limit_his.id)
        self.assertEqual(graduation_customer_history.max_limit_history_id, max_limit_his.id)
        self.assertEqual(graduation_customer_history.set_limit_history_id, set_limit_his.id)
        self.account_limit.refresh_from_db()
        self.assertEqual(int(max_limit_his.value_new), self.account_limit.max_limit)
        self.assertEqual(int(set_limit_his.value_new), self.account_limit.set_limit)
        self.assertEqual(int(available_limit_his.value_new), self.account_limit.available_limit)

    @patch('juloserver.graduation.tasks.get_valid_approval_account_ids')
    @patch('juloserver.graduation.services.get_passed_manual_rules_account_ids')
    @patch('juloserver.graduation.tasks.evaluate_less_risky_customers_graduation.delay')
    @patch('juloserver.graduation.services.timezone')
    def test_process_graduation(self, mock_timezone, mock_evaluate_less_risky_customers_graduation, mock_manual_rules, mock_get_valid_approval_account_ids):
        account_ids = []
        parameters = {
                        "graduation_rule": {
                            "max_grace_payment": 3,
                            "max_late_payment": 1,
                            "max_not_paid_payment": 0,
                            "min_percentage_paid_per_credit_limit": 50,
                            "min_paid_off_loan": 1,
                        },
                    }
        graduation_rule = parameters['graduation_rule']

        mock_now = timezone.localtime(timezone.now())

        first_graduate_accounts = GraduationRegularCustomerAccountsFactory.create_batch(6)
        account_ids.extend([i.account_id for i in first_graduate_accounts])

        # repeat graduation
        mock_last_graduation_date = timezone.localtime(timezone.now())
        mock_last_graduation_date = mock_last_graduation_date.replace(
            year=2022, month=6, day=12, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        repeat_graduate_accounts = GraduationRegularCustomerAccountsFactory.create_batch(
            8, last_graduation_date=mock_last_graduation_date,
        )
        account_ids.extend([i.account_id for i in repeat_graduate_accounts])
        mock_get_valid_approval_account_ids.return_value = account_ids
        process_graduation([account_ids], mock_now, graduation_rule, True)
        self.assertIsNotNone(mock_evaluate_less_risky_customers_graduation.call_count)
        mock_manual_rules.assert_called_once()


class TestGraduationEntryCustomers(TestCase):
    @patch('django.utils.timezone.now')
    def setUp(self, mock_timezone):
        mock_timezone.return_value = datetime.datetime(2022, 9, 30, 0, 0, 0)
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            cdate=datetime.datetime(2022, 9, 30).strftime('%Y-%m-%d')
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        mock_timezone.return_value = timezone.localtime(timezone.now())

        self.loan = CleanLoanFactory.create_batch(
            3, customer=self.customer, account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF), loan_duration=2,
            loan_amount=Iterator([200000, 500000, 500000])
        )
        self.payment = PaymentFactory.create_batch(
            6, loan=Iterator([
                self.loan[0], self.loan[0], self.loan[1], self.loan[1], self.loan[2], self.loan[2]
            ]),
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 250000, 250000, 250000, 250000]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        self.account_property = AccountPropertyFactory(
            account=self.account, is_entry_level=True
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=600000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
                '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 17000000, '
                '"set_limit (pre-matrix)": 15000000}',
            max_limit=5000000,
            set_limit=500000
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
                "graduation_rules": [
                    {
                        "max_account_limit": 300000,
                        "min_account_limit": 100000,
                        "max_grace_payment": 1,
                        "max_late_payment": 0,
                        "min_percentage_limit_usage": 300,
                        "min_percentage_paid_amount": 100,
                        "new_account_limit": 500000
                    },
                    {
                        "max_account_limit": 500000,
                        "min_account_limit": 500000,
                        "max_grace_payment": 1,
                        "max_late_payment": 0,
                        "min_percentage_limit_usage": 200,
                        "min_percentage_paid_amount": 100,
                        "new_account_limit": 1000000
                    }
                ],
                "is_active_graduation": True,
            }
        )
        self.feature_setting_2 = FeatureSettingFactory(
            feature_name='graduation_fdc_check',
            is_active=True
        )
        self.fdc_inquiry = FDCInquiryFactory(application_id=self.application.id)
        self.fdc_inquiry_loan = FDCInquiryLoanFactory.create_batch(
            5, fdc_inquiry_id=self.fdc_inquiry.id, is_julo_loan=False,
            dpd_terakhir=Iterator([1, 1, 1, 1, 1]), status_pinjaman='Outstanding'
        )
        self.init_fdc_inquiry_loan_data = InitialFDCInquiryLoanDataFactory(
            fdc_inquiry=self.fdc_inquiry, initial_outstanding_loan_count_x100=10
        )

    def test_graduate_entry_500_limit_success(self):
        today = timezone.localtime(timezone.now()).date().strftime('%Y-%m-%d')
        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 1000000)
        self.assertEquals(self.account_limit.available_limit, 600000)
        self.account_property.refresh_from_db()
        self.assertEquals(self.account_property.last_graduation_date,
                          timezone.localtime(timezone.now()).date())
        self.assertFalse(self.account_property.is_entry_level)
        history_graduation_date = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='last_graduation_date'
        ).last()
        self.assertEquals(history_graduation_date.value_new, today)
        self.assertEquals(history_graduation_date.value_old, None)
        history_is_entry_level = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='is_entry_level'
        ).last()
        self.assertEquals(history_is_entry_level.value_new, 'False')
        self.assertEquals(history_is_entry_level.value_old, 'True')
        account_limit_histories = AccountLimitHistory.objects.filter(
            account_limit=self.account_limit)
        available_limit_his = account_limit_histories.get(field_name='available_limit')
        max_limit_his = account_limit_histories.get(field_name='max_limit')
        set_limit_his = account_limit_histories.get(field_name='set_limit')
        self.assertEqual(int(max_limit_his.value_new), self.account_limit.max_limit)
        self.assertEqual(int(set_limit_his.value_new), self.account_limit.set_limit)
        self.assertEqual(int(available_limit_his.value_new), self.account_limit.available_limit)
        history_grad = GraduationCustomerHistory2.objects.filter(
            account_id=self.account.id, graduation_type=GraduationType.ENTRY_LEVEL, latest_flag=True,
            available_limit_history_id=available_limit_his.id, max_limit_history_id=max_limit_his.id,
            set_limit_history_id=set_limit_his.id
        ).last()
        self.assertIsNotNone(history_grad)

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_graduate_entry_300_limit_success(self, mock_execute_after_transaction_safely):
        self.account_limit.update_safely(
            max_limit=300000,
            set_limit=300000,
            available_limit=100000,
            used_limit=200000
        )
        for loan in self.loan:
            loan.update_safely(loan_amount=300000)
        for payment in self.payment:
            payment.update_safely(paid_amount=150000)

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 300000)

        loan = CleanLoanFactory(
            customer=self.customer, account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT), loan_duration=2,
            loan_amount=200000
        )
        payments = PaymentFactory.create_batch(
            2, loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        loan.update_safely(loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF))
        for payment in payments:
            payment.update_safely(payment_status=StatusLookupFactory(
                status_code=PaymentStatusCodes.PAID_ON_TIME)
            )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 300000)
        self.assertEquals(6, mock_execute_after_transaction_safely.call_count)

    def test_graduate_entry_level_twice(self):
        self.account_limit.update_safely(
            max_limit=300000,
            set_limit=300000,
            available_limit=300000,
            used_limit=0
        )
        for loan in self.loan:
            loan.update_safely(loan_amount=300000)
        for payment in self.payment:
            payment.update_safely(paid_amount=150000)

        loan_1 = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT), loan_duration=1,
            loan_amount=50000
        )

        loan_2 = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT), loan_duration=1,
            loan_amount=50000
        )

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )
        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )
        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)

    def test_graduate_entry_out_of_limit_failed(self):
        self.account_limit.update_safely(
            max_limit=450000,
            set_limit=450000,
            available_limit=250000,
            used_limit=200000
        )

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 450000)
        self.assertEquals(self.account_limit.available_limit, 250000)

    def test_graduate_entry_late_payment_failed(self):
        for payment in self.payment:
            payment.update_safely(
                payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_LATE)
            )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 100000)

    def test_graduate_entry_min_limit_usage_failed(self):
        for loan in self.loan:
            loan.update_safely(loan_amount=100000)

        for payment in self.payment:
            payment.update_safely(paid_amount=50000)

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 100000)

    @patch('django.utils.timezone.now')
    def test_graduate_entry_min_paid_amount_failed(self, mock_timezone):
        mock_timezone.return_value = datetime.datetime(2022, 9, 30, 0, 0, 0)
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            cdate=datetime.datetime(2022, 9, 30).strftime('%Y-%m-%d')
        )
        application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        application_history = ApplicationHistoryFactory(
            application_id=application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        mock_timezone.return_value = timezone.localtime(timezone.now())

        loan = CleanLoanFactory.create_batch(
            3, customer=customer, account=account,
            loan_status=Iterator([
                StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
                StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
                StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
            ]),
            loan_duration=2,
            loan_amount=Iterator([500000, 500000, 500000])
        )
        payment = PaymentFactory.create_batch(
            6, loan=Iterator([
                self.loan[0], self.loan[0], self.loan[1], self.loan[1], self.loan[2], self.loan[2]
            ]),
            due_amount=Iterator([0, 0, 250000, 250000, 250000, 250000]),
            paid_amount=Iterator([250000, 250000, 0, 0, 0, 0]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        account_property = AccountPropertyFactory(
            account=account, is_entry_level=True
        )
        account_limit = AccountLimitFactory(
            account=account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

    @patch('juloserver.cfs.tasks.update_post_graduation')
    def test_application_invalid(self, mock_update_post_graduation):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        application_history = ApplicationHistoryFactory(
            application_id=application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )

        loan = CleanLoanFactory.create_batch(
            3, customer=customer, account=account,
            loan_status=Iterator([
                StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
                StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
                StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
            ]),
            loan_duration=2,
            loan_amount=Iterator([500000, 500000, 500000])
        )
        payment = PaymentFactory.create_batch(
            6, loan=Iterator([
                self.loan[0], self.loan[0], self.loan[1], self.loan[1], self.loan[2], self.loan[2]
            ]),
            due_amount=Iterator([0, 0, 250000, 250000, 250000, 250000]),
            paid_amount=Iterator([250000, 250000, 0, 0, 0, 0]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        account_property = AccountPropertyFactory(
            account=account, is_entry_level=True
        )
        account_limit = AccountLimitFactory(
            account=account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )

        update_graduate_entry_level(
            account.id, self.feature_setting.parameters['graduation_rules']
        )
        mock_update_post_graduation.assert_not_called()

    @patch('juloserver.cfs.tasks.update_post_graduation')
    def test_new_acc_limit_is_set_limit(self, mock_update_post_graduation):
        self.feature_setting.parameters['graduation_rules'][1]['new_account_limit'] = 500000
        self.feature_setting.save()

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )
        mock_update_post_graduation.assert_not_called()

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_graduate_entry_feature_setting_off(self, mock_execute_after_transaction_safely):
        self.feature_setting.parameters['is_active_graduation'] = False
        self.feature_setting.save()

        for payment in self.payment:
            payment.update_safely(
                payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_LATE)
            )

        self.assertEquals(0, mock_execute_after_transaction_safely.call_count)

    def test_graduate_entry_500_limit_failed_fdc_check_delinquent_loan(self):
        self.fdc_inquiry_loan[1].update_safely(dpd_terakhir=9)

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 100000)
        self.account_property.refresh_from_db()
        self.assertIsNone(self.account_property.last_graduation_date)
        self.assertTrue(self.account_property.is_entry_level)
        history_graduation_date = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='last_graduation_date'
        ).last()
        self.assertIsNone(history_graduation_date)
        history_is_entry_level = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='is_entry_level'
        ).last()
        self.assertIsNone(history_is_entry_level)
        history_grad = GraduationCustomerHistory2.objects.filter(
            account_id=self.account.id, graduation_type=GraduationType.ENTRY_LEVEL, latest_flag=True
        ).last()
        self.assertIsNone(history_grad)

    def test_graduate_entry_500_limit_failed_fdc_check_graduation_ongoing_loan(self):
        self.init_fdc_inquiry_loan_data.update_safely(initial_outstanding_loan_count_x100=1)

        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        self.account_limit.refresh_from_db()
        self.assertEquals(self.account_limit.set_limit, 500000)
        self.assertEquals(self.account_limit.available_limit, 100000)
        self.account_property.refresh_from_db()
        self.assertIsNone(self.account_property.last_graduation_date)
        self.assertTrue(self.account_property.is_entry_level)
        history_graduation_date = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='last_graduation_date'
        ).last()
        self.assertIsNone(history_graduation_date)
        history_is_entry_level = AccountPropertyHistory.objects.filter(
            account_property=self.account_property, field_name='is_entry_level'
        ).last()
        self.assertIsNone(history_is_entry_level)
        history_grad = GraduationCustomerHistory2.objects.filter(
            account_id=self.account.id, graduation_type=GraduationType.ENTRY_LEVEL,
            latest_flag=True
        ).last()
        self.assertIsNone(history_grad)

    @patch('juloserver.cfs.tasks.update_post_graduation')
    @patch('juloserver.graduation.services.check_fdc_graduation_conditions')
    def test_fdc_check_graduation_feature_setting_off(self, mock_feature_setting, mock_update):
        self.feature_setting_2.update_safely(is_active=False)
        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )

        mock_feature_setting.assert_not_called()
        mock_update.assert_called_once()


class TestMuteSignalsAccountLimit(TestCase):
    @patch('django.utils.timezone.now')
    def setUp(self, mock_timezone):
        mock_timezone.return_value = datetime.datetime(2022, 9, 30, 0, 0, 0)
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            cdate=datetime.datetime(2022, 9, 30).strftime('%Y-%m-%d')
        )
        self.account_property = AccountPropertyFactory(
            account=self.account, is_entry_level=True
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch('juloserver.graduation.services.execute_after_transaction_safely')
    def test_mute_signals_account_limit(self, mock_execute_after_transaction_safely_graduation,
                                        mock_execute_after_transaction_safely_signals):
        update_account_limit_graduation(self.account_limit, 1000000, 2000000)
        mock_execute_after_transaction_safely_signals.assert_not_called()
        mock_execute_after_transaction_safely_graduation.assert_called()


class TestDowngradeCustomers(TestCase):
    def setUp(self):
        self.timezone_now = timezone.localtime(timezone.datetime(2023, 11, 11, 0, 0, 0))
        customer1 = CustomerFactory()
        account1 = AccountFactory(
            customer=customer1, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        customer_graduation = CustomerGraduationFactory(
            account_id=account1.id,
            customer_id=customer1.id,
            partition_date=datetime.date(2023, 11, 11),
            old_set_limit=2000000,
            new_set_limit=1000000,
            new_max_limit=1000000,
            is_graduate=False
        )

    @freeze_time("2023-11-11 00:00:00")
    @patch('juloserver.graduation.tasks.run_downgrade_account')
    def test_run_downgrade_customers(self, mock_run_downgrade_account):
        run_downgrade_customers()
        mock_run_downgrade_account.delay.assert_called()


class TestDowngradeAccount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=5_000_000, set_limit=2000000,
            available_limit=100000, used_limit=1900000
        )
        self.customer.save()
        self.account.save()
        self.account_limit.save()

        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=GraduationFeatureName.DOWNGRADE_CRITERIA_CONFIG_FS,
            category='graduation',
            parameters={
                'account_exist_checking': True,
                'next_period_days': 1,
            },
        )

    def get_customer_graduation(self):
        return {
            'id': 1000,
            'cdate': datetime.datetime(2023, 10, 10, 0, 0, 0),
            'udate': datetime.datetime(2023, 10, 10, 0, 0, 0),
            'customer_id': self.customer.id,
            'account_id': self.account.id,
            'partition_date': datetime.date(2023, 10, 10),
            'old_set_limit': 2000000,
            'new_set_limit': 1000000,
            'new_max_limit': 3000000,
            'is_graduate': False,
            'graduation_flow': 'FTC repeat',
        }

    def test_success_criteria_status_code(self):
        # status != 420 can downgrade
        customer_graduation = self.get_customer_graduation()
        self.account.update_safely(status_id=AccountConstant.STATUS_CODE.active_in_grace)
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

    def test_criteria_exists_graduation_action_fail(self):
        next_period_days = self.feature_setting.parameters['next_period_days']
        customer_graduation = self.get_customer_graduation()
        exist_graduation = GraduationCustomerHistoryFactory(account_id=self.account.id)
        exist_graduation.cdate = datetime.datetime(2023, 10, 10, 0, 0, 0) \
            - timedelta(days=(next_period_days + 1))

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)
        self.assertFalse(failure.is_resolved)

    def test_criteria_exists_downgrade_action_fail(self):
        next_period_days = self.feature_setting.parameters['next_period_days']
        customer_graduation = self.get_customer_graduation()
        exist_downgrade = DowngradeCustomerHistoryFactory(account_id=self.account.id)
        exist_downgrade.cdate = datetime.datetime(2023, 10, 10, 0, 0, 0) \
            - timedelta(days=(next_period_days + 1))

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)
        self.assertFalse(failure.is_resolved)

    def test_criteria_feature_setting_is_active(self):
        customer_graduation = self.get_customer_graduation()

        # feature setting is_active = False don't check criteria downgrade
        self.feature_setting.update_safely(is_active=False)
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

    def test_criteria_feature_setting_acc_exist_checking_false(self):
        customer_graduation = self.get_customer_graduation()

        # feature setting account_exist_checking = False don't check account criteria
        self.account.update_safely(status_id=AccountConstant.STATUS_CODE.active_in_grace)
        self.feature_setting.update_safely(
            is_active=True,
            parameters={
                'account_exist_checking': False,
                'next_period_days': 0,
            }
        )
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

    def test_criteria_feature_setting_acc_exist_checking_true(self):
        customer_graduation = self.get_customer_graduation()
        # feature setting account_exist_checking = True check account criteria
        self.account.update_safely(status_id=AccountConstant.STATUS_CODE.active)
        self.feature_setting.update_safely(
            is_active=True,
            parameters={
                'account_exist_checking': True,
                'next_period_days': 0,
            }
        )
        next_period_days = self.feature_setting.parameters['next_period_days']
        customer_graduation = self.get_customer_graduation()
        exist_graduation = GraduationCustomerHistoryFactory(account_id=self.account.id)
        exist_graduation.cdate = datetime.datetime(2023, 10, 10, 0, 0, 0) \
            - timedelta(days=next_period_days)

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

    def test_criteria_feature_setting_fail_period_days(self):
        customer_graduation = self.get_customer_graduation()
        # feature setting account_exist_checking = True check account criteria
        self.account.update_safely(status_id=AccountConstant.STATUS_CODE.active)
        self.feature_setting.update_safely(
            is_active=True,
            parameters={
                'account_exist_checking': True,
                'next_period_days': 1,
            }
        )
        next_period_days = self.feature_setting.parameters['next_period_days']
        customer_graduation = self.get_customer_graduation()
        exist_graduation = GraduationCustomerHistoryFactory(account_id=self.account.id)
        exist_graduation.cdate = datetime.datetime(2023, 10, 10, 0, 0, 0) \
            - timedelta(days=next_period_days + 1)

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)

    def test_downgrade_new_set_limit_greater_fail(self):
        customer_graduation = self.get_customer_graduation()
        customer_graduation['new_set_limit'] = 3000000

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)
        self.assertEqual(failure.type, GraduationFailureType.DOWNGRADE)
        self.assertEqual(failure.failure_reason, GraduationFailureConst.FAILED_BY_SET_LIMIT)

    def test_downgrade_new_set_limit_equal_fail(self):
        customer_graduation = self.get_customer_graduation()
        customer_graduation['new_set_limit'] = 2000000

        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)
        self.assertEqual(failure.type, GraduationFailureType.DOWNGRADE)
        self.assertEqual(failure.failure_reason, GraduationFailureConst.FAILED_BY_SET_LIMIT)

    def test_downgrade_new_max_limit_greater_fail(self):
        customer_graduation = self.get_customer_graduation()
        # max limit < new max_limit
        customer_graduation['new_max_limit'] = 10000000
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNotNone(failure)
        self.assertEqual(failure.type, GraduationFailureType.DOWNGRADE)
        self.assertEqual(failure.failure_reason, GraduationFailureConst.FAILED_BY_MAX_LIMIT)

    def test_downgrade_new_max_limit_equal_fail(self):
        customer_graduation = self.get_customer_graduation()
        # new_max_limit = max_limit
        customer_graduation['new_max_limit'] = 5_000_000
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

        downgrade_hist = DowngradeCustomerHistory.objects.filter(
            account_id=self.account.id,
            latest_flag=True
        ).last()
        set_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.set_limit_history_id
        ).last()
        self.assertEqual(
            int(set_limit_history.value_new),
            customer_graduation['new_set_limit']
        )
        max_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.max_limit_history_id
        ).last()
        # New max limit equal max_limit --> no record history
        self.assertIsNone(max_limit_history)

        value_new = int(set_limit_history.value_new)
        value_old = int(set_limit_history.value_old)
        new_available_limit = self.account_limit.available_limit - (value_old - value_new)
        available_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.available_limit_history_id
        ).last()
        self.assertEqual(
            int(available_limit_history.value_new),
            new_available_limit
        )

    def test_downgrade_success(self):
        customer_graduation = self.get_customer_graduation()
        run_downgrade_account(customer_graduation)
        failure = CustomerGraduationFailure.objects.filter(
            customer_graduation_id=customer_graduation['id']
        ).last()
        self.assertIsNone(failure)

        downgrade_hist = DowngradeCustomerHistory.objects.filter(
            account_id=self.account.id,
            latest_flag=True
        ).last()
        set_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.set_limit_history_id
        ).last()
        self.assertEqual(
            int(set_limit_history.value_new),
            customer_graduation['new_set_limit']
        )
        max_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.max_limit_history_id
        ).last()
        self.assertEqual(
            int(max_limit_history.value_new),
            customer_graduation['new_max_limit']
        )

        value_new = int(set_limit_history.value_new)
        value_old = int(set_limit_history.value_old)
        new_available_limit = self.account_limit.available_limit - (value_old - value_new)
        available_limit_history = AccountLimitHistory.objects.filter(
            id=downgrade_hist.available_limit_history_id
        ).last()
        self.assertEqual(
            int(available_limit_history.value_new),
            new_available_limit
        )


class TestRetryDowngradeAccount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=2000000, set_limit=2000000,
            available_limit=100000, used_limit=1900000
        )

        self.customer_graduation = CustomerGraduationFactory(
            account_id=self.account.id,
            customer_id=self.customer.id,
            old_set_limit=2000000,
            new_set_limit=1000000,
            new_max_limit=1000000,
        )

        self.failure = CustomerGraduationFailureFactory(
            customer_graduation_id=self.customer_graduation.id,
            retries=0,
            is_resolved=False,
            type=GraduationFailureType.DOWNGRADE,
        )

        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=GraduationFeatureName.DOWNGRADE_CRITERIA_CONFIG_FS,
            category='graduation',
            parameters={
                'account_exist_checking': True,
                'next_period_days': 1,
            },
        )

    @patch('juloserver.graduation.services.check_action_period_time_downgrade')
    def test_retry_downgrade_account_fail(self, mock_check_action_period_time_downgrade):
        mock_check_action_period_time_downgrade.return_value = (
            False, 'account had graduation action in the last 1 days'
        )
        old_retries = self.failure.retries
        self.account.update_safely(status_id=AccountConstant.STATUS_CODE.active_in_grace)
        retry_downgrade_account(self.failure.id, self.customer_graduation.id)
        self.failure.refresh_from_db()

        self.assertFalse(self.failure.is_resolved)
        self.assertEqual(self.failure.retries, old_retries + 1)

    def test_retry_downgrade_account_success(self):
        retry_downgrade_account(self.failure.id, self.customer_graduation.id)
        self.failure.refresh_from_db()

        self.assertTrue(self.failure.is_resolved)


class TestScanCustomerSuspendForSendingME(TestCase):
    def setUp(self):
        now = datetime.datetime(2023, 10, 10, 7, 0, 0)
        cus_suspend_1 = CustomerSuspendHistoryFactory(
            cdate=now-datetime.timedelta(days=1)
        )
        cus_suspend_2 = CustomerSuspendHistoryFactory(
            cdate=now-datetime.timedelta(days=1)
        )
        cus_suspend_3 = CustomerSuspendHistoryFactory(
            cdate=now-datetime.timedelta(days=2)
        )

    @patch('django.utils.timezone.now')
    @patch(f'juloserver.graduation.tasks.%s.delay' %
           'send_user_attributes_to_moengage_customer_suspended_unsuspended'
    )
    def test_scan(self, send_me, mock_timezone_now):
        mock_timezone_now.return_value = datetime.datetime(2023, 10, 10, 7, 0, 0)
        scan_customer_suspend_unsuspend_for_sending_to_me()
        self.assertEqual(send_me.call_count, 2)


class TestNotifySlackDowngradeCustomer(TestCase):
    @patch('juloserver.graduation.services.calc_summary_downgrade_customer')
    @patch('juloserver.graduation.tasks.get_slack_bot_client')
    def test_notify_slack_downgrade_customer(self, mock_slack_bot_client, mock_calc_downgrade):
        today_str = '01-02-2024 08:30'
        total = 7
        total_success = 3
        total_failed = 4
        mock_calc_downgrade.return_value = (total_success, total_failed)

        notify_slack_downgrade_customer(7, False, today_str)

        message = (
            f'Downgrade customer report at {today_str}\n'
            f'  - Total: {total}\n' +\
            f'  - Successed: {total_success}\n' +\
            f'  - Failed: {total_failed}\n'
        )

        mock_slack_bot_client.return_value.api_call.assert_called_with(
            "chat.postMessage",
            channel=settings.SLACK_GRADUATION_ALERTS,
            text=message
        )
