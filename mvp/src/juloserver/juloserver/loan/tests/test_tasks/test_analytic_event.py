from unittest import mock
from mock import MagicMock, patch

from django.test import TestCase, SimpleTestCase
from datetime import datetime, date, timedelta

from juloserver.account.constants import AccountConstant
from juloserver.apiv2.tests.factories import PdCustomerLifetimeModelResultFactory
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditMatrixRepeatFactory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.services.loan_event import combine_x220_ftc_pct_mycroft_event
from juloserver.loan.tasks.analytic_event import (
    send_customer_lifetime_value_analytic_event,
    send_customer_lifetime_ga_appsflyer_event_by_batch,
)
from juloserver.ana_api.services import (
    LoanSelectionAnaAPIPayload,
    TransactionModelResult,
    predict_loan_selection,
)
from juloserver.julo.services2.redis_helper import MockRedisHelper


class TestAnalyticEvent(TestCase):
    def setUp(self):
        loan = LoanFactory(
            application=ApplicationFactory(
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            ),
        )

    def create_pd_customer_lifetime_model_results(self):
        today = date.today()
        PdCustomerLifetimeModelResultFactory(
            customer_id=1000000001,
            predict_date=today,
            lifetime_value='high',
            has_transact_in_range_date=1,
        )
        PdCustomerLifetimeModelResultFactory(
            customer_id=1000000002,
            predict_date=today,
            lifetime_value='high',
            has_transact_in_range_date=2,
        )
        PdCustomerLifetimeModelResultFactory(
            customer_id=1000000003,
            predict_date=today - timedelta(days=1),
            lifetime_value='high',
            has_transact_in_range_date=1,
        )
        PdCustomerLifetimeModelResultFactory(
            customer_id=1000000004,
            predict_date=today,
            lifetime_value='medium',
            has_transact_in_range_date=1,
        )

    @mock.patch('django.utils.timezone.localtime')
    @mock.patch(
        (
            'juloserver.loan.tasks.analytic_event.'
            'send_customer_lifetime_ga_appsflyer_event_by_batch.delay'
        )
    )
    def test_send_customer_lifetime_value_analytic_event(self, mock_event_by_batch, mock_localtime):
        mock_localtime.return_value = datetime.now()

        self.create_pd_customer_lifetime_model_results()

        send_customer_lifetime_value_analytic_event()
        self.assertEqual(mock_event_by_batch.call_count, 1)

    @mock.patch('juloserver.google_analytics.tasks.send_event_to_ga_task_async.apply_async')
    @mock.patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task.delay')
    def test_send_customer_lifetime_ga_appsflyer_event_by_batch(self, mock_appsflyer, mock_ga):
        now = datetime.now()
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            account=account,
            customer=customer,
        )
        customer.save()
        loan1 = LoanFactory(
            customer=customer,
            account=account,
            loan_amount=500000,
            loan_disbursement_amount=600000,
        )
        loan1.cdate = now - timedelta(days=7)

        loan2 = LoanFactory(
            customer=customer,
            account=account,
            loan_amount=1500000,
            loan_disbursement_amount=1600000,
        )
        loan2.cdate = now - timedelta(days=6)

        loan3 = LoanFactory(
            customer=customer,
            account=account,
            loan_amount=2500000,
            loan_disbursement_amount=2600000,
        )
        loan3.cdate = now - timedelta(days=8)

        send_customer_lifetime_ga_appsflyer_event_by_batch([customer.id])

        mock_ga.assert_called_with(
            kwargs={
                'customer_id': customer.id,
                'event': 'clv_high_3mo',
                'extra_params': {
                    'credit_limit_balance': 600000
                },
            }
        )

        mock_appsflyer.assert_called_with(
            application.id,
            'clv_high_3mo',
            extra_params={
                'credit_limit_balance': 600000,
            },
        )


class TestCombineEvent(SimpleTestCase):
    def test_combine_event_ftc_pct_mycroft(self):
        test_cases = [
            (['_ftc', '_pct80'], ['x_220_ftc_pct80']),  # Basic case with '_ftc' and '_pct80'
            (['_ftc', '_pct90'], ['x_220_ftc_pct90']),  # Basic case with '_ftc' and '_pct90'
            (['_ftc', '_pct80', '_mycroft90'],
             ['x_220_ftc_pct80', 'x_220_pct80_mycroft90', 'x_220_ftc_pct80_mycroft90']),
            # '_ftc' with '_pct80' and '_mycroft90'
            (['_ftc', '_pct90', '_mycroft90'],
             ['x_220_ftc_pct90', 'x_220_pct90_mycroft90', 'x_220_ftc_pct90_mycroft90']),
            # '_ftc' with '_pct90' and '_mycroft90'
            (['_repeat', '_pct80'], []),  # '_repeat' without '_mycroft90' (should return empty)
            (['_repeat', '_pct90'], []),  # '_repeat' without '_mycroft90' (should return empty)
            (['_repeat', '_pct80', '_mycroft90'], ['x_220_pct80_mycroft90']),
            # Valid '_repeat' case with '_pct80'
            (['_repeat', '_pct90', '_mycroft90'], ['x_220_pct90_mycroft90']),
            # Valid '_repeat' case with '_pct90'
            (['_ftc', '_pct80', '_pct90'], ['x_220_ftc_pct80']),
            # '_pct80' takes precedence over '_pct90'
            (['_ftc'], []),  # Missing pct suffix (should return empty)
            (['_repeat'], []),  # Missing pct suffix and '_mycroft90' (should return empty)
            (['_pct80'], []),  # Missing '_ftc' or '_repeat' (should return empty)
            (['_pct90'], []),  # Missing '_ftc' or '_repeat' (should return empty)
            (['_mycroft90'], []),  # Missing '_ftc' or '_repeat' and pct (should return empty)
            (['_ftc', '_mycroft90'], []),  # Missing pct suffix (should return empty)
            ([], [])  # Empty input (should return empty)
        ]

        for i, (input_list, expected_output) in enumerate(test_cases, 1):
            result = combine_x220_ftc_pct_mycroft_event(input_list)
            self.assertEqual(result, expected_output)


class TestHitAnaLoanSelectionTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=20_000_000,
            available_limit=5_000_000,
        )

        self.credit_matrix = CreditMatrixFactory(
            product=ProductLookupFactory(
                product_line=self.product_line,
            )
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=7,
            min_duration=2,
        )

        self.loan = LoanFactory(
            loan_amount=50000,
            account=self.account_limit.account,
            credit_matrix=self.credit_matrix,
            product=self.credit_matrix.product,
            customer=self.customer,
        )
        self.fake_redis = MockRedisHelper()

    @patch("juloserver.ana_api.services.requests.post")
    def test_hit_ana_loan_selection_api_task_normal_cm(self, mock_requests):
        transaction_method_id = 1
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_product_line.max_duration,
            min_loan_duration=self.credit_matrix_product_line.min_duration,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )

        post_anaserver_response = MagicMock()
        mock_requests.return_value = post_anaserver_response
        json_response_data = {
            "prediction_time": "2024-11-18 02:59:42.319671 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": 100000,
                "loan_duration_range": [3, 4, 5, 6, 7, 8, 9, 10],
            },
        }
        post_anaserver_response.status_code = 200
        post_anaserver_response.json.return_value = json_response_data

        is_success, response = predict_loan_selection(
            payload=payload,
        )
        mock_requests.assert_called_once()

        _, kwargs = mock_requests.call_args

        self.assertIn("/api/amp/v1/loan-selection", kwargs['url'])
        self.assertEqual(kwargs['json']['customer_id'], self.customer.id)
        self.assertEqual(
            kwargs['json']['min_loan_duration'], self.credit_matrix_product_line.min_duration
        )
        self.assertEqual(
            kwargs['json']['max_loan_duration'], self.credit_matrix_product_line.max_duration
        )
        self.assertEqual(kwargs['json']['set_limit'], self.account_limit.set_limit)
        self.assertEqual(kwargs['json']['available_limit'], self.account_limit.available_limit)
        self.assertEqual(kwargs['json']['transaction_method_id'], transaction_method_id)

        self.assertEqual(is_success, True)
        self.assertEqual(response, TransactionModelResult(**json_response_data))

    @patch("juloserver.ana_api.services.requests.post")
    def test_hit_ana_loan_selection_api_task_cm_repeat(self, mock_requests):
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method_id=1,
            max_tenure=6,
            min_tenure=3,
        )

        transaction_method_id = 3
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=self.credit_matrix_repeat.max_tenure,
            min_loan_duration=self.credit_matrix_repeat.min_tenure,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        post_anaserver_response = MagicMock()
        mock_requests.return_value = post_anaserver_response

        json_response = {
            "prediction_time": "2024-11-18 02:59:42.319671 UTC",
            "is_mercury": True,
            "allowed_loan_duration_amount": {
                "max_cashloan_amount": 100000,
                "loan_duration_range": [3, 4, 5, 6, 7, 8, 9, 10],
            },
        }
        post_anaserver_response.status_code = 200
        post_anaserver_response.json.return_value = json_response

        is_success, response = predict_loan_selection(
            payload=payload,
        )

        mock_requests.assert_called_once()

        _, kwargs = mock_requests.call_args

        self.assertIn("/api/amp/v1/loan-selection", kwargs['url'])
        self.assertEqual(kwargs['json']['customer_id'], self.customer.id)
        self.assertEqual(kwargs['json']['min_loan_duration'], self.credit_matrix_repeat.min_tenure)
        self.assertEqual(kwargs['json']['max_loan_duration'], self.credit_matrix_repeat.max_tenure)
        self.assertEqual(kwargs['json']['set_limit'], self.account_limit.set_limit)
        self.assertEqual(kwargs['json']['available_limit'], self.account_limit.available_limit)
        self.assertEqual(kwargs['json']['transaction_method_id'], transaction_method_id)

        self.assertEqual(is_success, True)
        self.assertEqual(response, TransactionModelResult(**json_response))

    @patch("juloserver.ana_api.services.requests.post")
    def test_hit_ana_loan_selection_api_other_statuses(self, mock_requests):

        # status 204
        transaction_method_id = 3
        payload = LoanSelectionAnaAPIPayload(
            customer_id=self.customer.id,
            max_loan_duration=10,
            min_loan_duration=2,
            available_limit=self.account_limit.available_limit,
            set_limit=self.account_limit.set_limit,
            transaction_method_id=transaction_method_id,
        )
        post_anaserver_response = MagicMock()
        mock_requests.return_value = post_anaserver_response

        post_anaserver_response.status_code = 204

        is_success, json_result = predict_loan_selection(
            payload=payload,
        )

        mock_requests.assert_called_once()

        self.assertEqual(is_success, True)
        self.assertEqual(json_result, None)

        # 500 status
        post_anaserver_response.status_code = 500

        mock_requests.reset_mock()
        is_success, json_result = predict_loan_selection(
            payload=payload,
        )

        mock_requests.assert_called_once()

        self.assertEqual(is_success, False)
        self.assertEqual(json_result, None)
