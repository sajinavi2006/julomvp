import pytz
import datetime
import random
from itertools import product
from collections import defaultdict

from django.test import TestCase
from unittest.mock import patch
from factory import Iterator

from juloserver.account.tests.factories import AccountFactory, CustomerFactory
from juloserver.sales_ops.models import SalesOpsLineup
from juloserver.sales_ops.services.sales_ops_revamp_services import (
    classify_m_score,
    classify_r_score,
    generate_sales_ops_line_up,
    assign_bucket_code_to_accounts
)
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsPrepareDataFactory,
    SalesOpsDailySummaryFactory,
    SalesOpsBucketFactory, FeatureSettingSalesOpsRevampFactory,
)


class TestClassifyRMScroing(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.customer = CustomerFactory(account=self.account)
        self.sales_ops_prepare_data = SalesOpsPrepareDataFactory(
            account=self.account,
            customer=self.customer,
            available_limit=500_000,
            customer_type='ftc',
            application_history_x190_cdate=datetime.datetime(2024, 8, 2, 12, 23, 34, tzinfo=pytz.UTC),
            latest_loan_fund_transfer_ts=datetime.datetime(2024, 7, 25, 12, 23, 34, tzinfo=pytz.UTC),
        )
        self.rm_score_mappings = {
            'monetary': {
                'field_name': 'available_limit',
                'data': {1: {'min_value': 2000000, 'max_value': float('inf'), 'score': 3},
                        2: {'min_value': 1000000, 'max_value': 2000000, 'score': 2},
                        3: {'min_value': float('-inf'), 'max_value': 1000000, 'score': 1}}
            },
            'recency_ftc': {
                'field_name': 'days_after_application_history_x190_cdate',
                'data': {4: {'min_value': 1, 'max_value': 14, 'score': 4},
                        5: {'min_value': 14, 'max_value': 30, 'score': 3},
                        6: {'min_value': 30, 'max_value': 60, 'score': 2},
                        7: {'min_value': 60, 'max_value': float('inf'), 'score': 1}}
            },
            'recency_repeat_os': {
                'field_name': 'days_after_latest_loan_fund_transfer_ts',
                'data': {8: {'min_value': 13, 'max_value': 30, 'score': 4},
                        9: {'min_value': 30, 'max_value': 60, 'score': 3},
                        10: {'min_value': 60, 'max_value': 90, 'score': 2},
                        11: {'min_value': 90, 'max_value': float('inf'), 'score': 1}}
            },
            'recency_repeat_no_os': {
                'field_name': 'days_after_latest_loan_fund_transfer_ts',
                'data': {8: {'min_value': 13, 'max_value': 30, 'score': 4},
                        9: {'min_value': 30, 'max_value': 60, 'score': 3},
                        10: {'min_value': 60, 'max_value': 90, 'score': 2},
                        11: {'min_value': 90, 'max_value': float('inf'), 'score': 1}}
            }
        }

    def test_classify_m1_score(self):
        account_m_score = classify_m_score(self.sales_ops_prepare_data, self.rm_score_mappings)
        m_score_id, m_score = account_m_score
        self.assertEqual(m_score, 1)
        self.assertEqual(m_score_id, 3)

    def test_classify_m2_score(self):
        self.sales_ops_prepare_data.available_limit = 2_000_000
        self.sales_ops_prepare_data.save()
        account_m_score = classify_m_score(self.sales_ops_prepare_data, self.rm_score_mappings)
        m_score_id, m_score = account_m_score
        self.assertEqual(m_score, 2)
        self.assertEqual(m_score_id, 2)

    def test_classify_m3_score(self):
        self.sales_ops_prepare_data.available_limit = 2_000_001
        self.sales_ops_prepare_data.save()
        account_m_score = classify_m_score(self.sales_ops_prepare_data, self.rm_score_mappings)
        m_score_id, m_score = account_m_score
        self.assertEqual(m_score, 3)
        self.assertEqual(m_score_id, 1)

    @patch('django.utils.timezone.now')
    def test_classify_r1_score(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 12, 31, 0, 0, 0)
        # For FTC
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 1)
        self.assertEqual(r_score_id, 7)

        # For repeat
        self.sales_ops_prepare_data.customer_type = 'repeat_os'
        self.sales_ops_prepare_data.save()
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 1)
        self.assertEqual(r_score_id, 11)

    @patch('django.utils.timezone.now')
    def test_classify_r2_score(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 9, 21, 0, 0, 0)
        # For FTC
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 2)
        self.assertEqual(r_score_id, 6)

        # For repeat
        self.sales_ops_prepare_data.customer_type = 'repeat_os'
        self.sales_ops_prepare_data.save()
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 3)
        self.assertEqual(r_score_id, 9)

    @patch('django.utils.timezone.now')
    def test_classify_r3_score(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 8, 22, 0, 0, 0)
        # For FTC
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 3)
        self.assertEqual(r_score_id, 5)

        # For repeat
        self.sales_ops_prepare_data.customer_type = 'repeat_os'
        self.sales_ops_prepare_data.save()
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 4)
        self.assertEqual(r_score_id, 8)

    @patch('django.utils.timezone.now')
    def test_classify_r4_score(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 8, 10, 0, 0, 0)
        # For FTC
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 4)
        self.assertEqual(r_score_id, 4)

        # For repeat
        self.sales_ops_prepare_data.customer_type = 'repeat_os'
        self.sales_ops_prepare_data.save()
        account_r_score = classify_r_score(self.sales_ops_prepare_data,
                                                              self.rm_score_mappings,
                                                              self.sales_ops_prepare_data.customer_type)
        r_score_id, r_score = account_r_score
        self.assertEqual(r_score, 4)
        self.assertEqual(r_score_id, 8)


class TestSalesOpsLineupGenerate(TestCase):
    def setUp(self):
        self.accounts, self.customers, self.sales_ops_prepare_data = self.set_up_prepared_data()
        self.daily_summary = SalesOpsDailySummaryFactory(
            total=3,
            number_of_task=1,
        )
        SalesOpsBucketFactory.create_batch(5,
            code=Iterator(['a', 'b', 'c', 'd', 'e']),
            is_active=True
        )
        FeatureSettingSalesOpsRevampFactory()
        SalesOpsLineupFactory.create_batch(3, account=Iterator(self.accounts), is_active=False)

    def set_up_prepared_data(self):
        accounts = AccountFactory.create_batch(3)
        customers = CustomerFactory.create_batch(3, account=Iterator(accounts))
        sales_ops_prepare_data = SalesOpsPrepareDataFactory.create_batch(3,
            account=Iterator(accounts),
            customer=Iterator(customers),
            available_limit=Iterator([0, 1_500_000, 500_000]),
            customer_type=Iterator(['ftc', 'repeat_os', 'repeat_no_os']),
            application_history_x190_cdate=datetime.datetime(
                2024, 8, 2, 12, 23, 34, tzinfo=pytz.UTC
            ),
            latest_loan_fund_transfer_ts=datetime.datetime(
                2024, 7, 25, 12, 23, 34, tzinfo=pytz.UTC
            ),
        )
        return accounts, customers, sales_ops_prepare_data

    def set_up_input_data(self):
        input_data = []
        m_scores = [(1, 3), (2, 2), (3, 1)]
        r_scores = [(4, 1), (3, 2), (2, 3)]
        for sales_ops_prepare_data, r_score, m_score in zip(
            self.sales_ops_prepare_data, r_scores, m_scores
        ):
            input_data.append({
                'account_id': sales_ops_prepare_data.account_id,
                'customer_type': sales_ops_prepare_data.customer_type,
                'm_score': m_score[0],
                'm_score_id': m_score[1],
                'r_score': r_score[0],
                'r_score_id': r_score[1],
                'available_limit': sales_ops_prepare_data.available_limit,
            })
        return input_data

    def test_generate_sales_ops_line_up(self):
        input_data = self.set_up_input_data()
        generate_sales_ops_line_up(input_data)

        lineup_qs = SalesOpsLineup.objects.filter(is_active=True)
        count_lineup = lineup_qs.count()

        self.assertEqual(count_lineup, 3)
        self.assertNotEqual(lineup_qs[0].bucket_code, lineup_qs[1].bucket_code)
        self.assertNotEqual(lineup_qs[0].bucket_code, lineup_qs[2].bucket_code)
        self.assertNotEqual(lineup_qs[1].bucket_code, lineup_qs[2].bucket_code)

    def test_assign_bucket_code_to_accounts(self):
        customer_type = ['ftc', 'repeat_os', 'repeat_no_os']
        r_scores = [4, 3, 2, 1]
        m_scores = [3, 2, 1]

        n_accounts = 0
        group = defaultdict(list)
        keys = list(product(customer_type, r_scores, m_scores))
        for idx, key in enumerate(keys):
            start_id = 10_000 * (idx + 1)
            end_id = start_id + 8_000
            r = list(range(0, 530))
            r.extend([0]*300)
            r.extend([1]*300)
            r.extend([2]*300)
            n = random.choice(r)

            account_ids = random.sample(range(start_id, end_id), k=n)
            group[key].extend(account_ids)
            n_accounts += n

        bucket_assignments = assign_bucket_code_to_accounts(group, keys)

        for bucket_code, account_ids in bucket_assignments.items():
            n = len(account_ids)
            ratio = (n / n_accounts) * 100
            self.assertLessEqual(ratio, 22)
            self.assertGreaterEqual(ratio, 18)
