import datetime
import os
from datetime import date, timedelta
from unittest import mock
from unittest.mock import patch, call

from django.db.models import Q
from django.utils import timezone
from django.test import TestCase
from factory import Iterator
from rest_framework.exceptions import ValidationError

from juloserver.account.tests.factories import (
    AccountLimitFactory, AccountPropertyFactory, AccountLookupFactory
)
from juloserver.account.models import AccountLimit
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    StatusLookupFactory, FeatureSettingFactory, AuthUserFactory, CustomerFactory,
    ApplicationFactory, LoanFactory
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.services.use_cases import (
    send_event_moengage_for_rpc_sales_ops,
    send_event_moengage_for_rpc_sales_ops_pds,
)
from juloserver.promo.constants import PromoCodeCriteriaConst
from juloserver.promo.tests.factories import PromoCodeCriteriaFactory, PromoCodeFactory, \
    PromoCodeAgentMappingFactory
from juloserver.sales_ops.constants import SalesOpsVendorName
from juloserver.sales_ops.models import (
    SalesOpsRMScoring,
    SalesOpsAccountSegmentHistory,
    SalesOpsLineup,
    SalesOpsAgentAssignment,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.sales_ops.constants import (
    SalesOpsSettingConst,
    ScoreCriteria,
)
from juloserver.sales_ops.exceptions import MissingAccountSegmentHistory
from juloserver.sales_ops.services import sales_ops_services
from juloserver.sales_ops.services.autodialer_services import AutodialerDelaySetting
from juloserver.sales_ops.services.sales_ops_services import (
    bulk_calculate_recency_score,
    bulk_calculate_monetary_score,
    bulk_create_account_segment_history,
    save_setting,
    SalesOpsSetting,
    update_latest_lineup_info,
    set_rm_scoring,
    AgentAssignmentCsvImporter,
    get_bucket_code,
    get_minimum_transaction_promo_code,
)
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsMScoreFactory,
    SalesOpsRScoreFactory,
    SalesOpsRMScoringFactory,
    SalesOpsAccountSegmentHistoryFactory,
    SalesOpsAgentAssignmentFactory,
    SalesOpsAutodialerSessionFactory,
    SaleOpsBucketFactory,
    SalesOpsVendorFactory,
    SalesOpsVendorBucketMappingFactory,
    SalesOpsGraduationFactory,
)
from juloserver.sales_ops.services.sales_ops_services import RMScoreInfo


class TestSalesOpsSetting(TestCase):
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_available_limit(self, mock_julo_service):
        mock_julo_service.get_sales_ops_setting.return_value = '200000'
        value = sales_ops_services.SalesOpsSetting.get_available_limit()

        self.assertEqual(value, 200000)
        mock_julo_service.get_sales_ops_setting.assert_called_once_with(
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT,
            SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_LIMIT
        )

    def test_get_rm_percentages(self):
        r_percentages = sales_ops_services.SalesOpsSetting.get_r_percentages()
        self.assertEqual(r_percentages, [20, 20, 20, 20, 20])

        m_percentages = sales_ops_services.SalesOpsSetting.get_m_percentages()
        self.assertEqual(m_percentages, [20, 20, 20, 20, 20])

    @patch('juloserver.sales_ops.services.sales_ops_services.logger')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_available_limit_invalid_type(self, mock_julo_service, mock_logger):
        mock_julo_service.get_sales_ops_setting.return_value = 'invalid-data'

        value = sales_ops_services.SalesOpsSetting.get_available_limit()
        self.assertEqual(value, SalesOpsSettingConst.DEFAULT_LINEUP_MIN_AVAILABLE_LIMIT)
        mock_logger.warning.assert_called_once_with('Invalid integer type: invalid-data')

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_autodialer_delay_setting(self, mock_julo_services):
        parameters = {
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 1,
            SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 2,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 3,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 4,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 5,
        }
        mock_julo_services.get_sales_ops_setting.return_value = parameters

        ret_val = sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting()

        self.assertIsInstance(ret_val, sales_ops_services.AutodialerDelaySetting)
        self.assertEqual(1, ret_val.rpc_delay_hour)
        self.assertEqual(2, ret_val.rpc_assignment_delay_hour)
        self.assertEqual(3, ret_val.non_rpc_delay_hour)
        self.assertEqual(4, ret_val.non_rpc_final_delay_hour)
        self.assertEqual(5, ret_val.non_rpc_final_attempt_count)

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_autodialer_delay_setting_default(self, mock_julo_services):
        mock_julo_services.get_sales_ops_setting.return_value = None

        ret_val = sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting()

        self.assertEqual(
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR,
            ret_val.rpc_delay_hour
        )
        self.assertEqual(
            SalesOpsSettingConst.DEFAULT_AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR,
            ret_val.rpc_assignment_delay_hour
        )
        self.assertEqual(
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR,
            ret_val.non_rpc_delay_hour
        )
        self.assertEqual(
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR,
            ret_val.non_rpc_final_delay_hour
        )
        self.assertEqual(
            SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT,
            ret_val.non_rpc_final_attempt_count
        )

    def test_get_delay_paid_collection_call_day(self):
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters={
            SalesOpsSettingConst.LINEUP_DELAY_PAID_COLLECTION_CALL_DAY: '3'
        })

        ret_val = sales_ops_services.SalesOpsSetting.get_delay_paid_collection_call_day()

        self.assertEqual(timedelta(days=3), ret_val)

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_lineup_rpc_delay_call_hour(self, mock_julo_services):
        mock_julo_services.get_sales_ops_setting.return_value = 360

        ret_val = sales_ops_services.SalesOpsSetting.get_sales_ops_rpc_delay_call_hour()

        self.assertEqual(ret_val, 360)

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_lineup_non_rpc_attempt(self, mock_julo_services):
        mock_julo_services.get_sales_ops_setting.return_value = 2

        ret_val = sales_ops_services.SalesOpsSetting.get_sales_ops_non_rpc_attempt_count()

        self.assertEqual(ret_val, 2)

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_lineup_non_rpc_delay_call_hour(self, mock_julo_services):
        mock_julo_services.get_sales_ops_setting.return_value = 20

        ret_val = sales_ops_services.SalesOpsSetting.get_sales_ops_non_rpc_delay_call_hour()

        self.assertEqual(ret_val, 20)

    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_get_lineup_non_rpc_final_delay_call_hour(self, mock_julo_services):
        mock_julo_services.get_sales_ops_setting.return_value = 168

        ret_val = sales_ops_services.SalesOpsSetting.get_sales_ops_non_rpc_final_delay_call_hour()

        self.assertEqual(ret_val, 168)


class TestIsAccountValidForSalesOpsLineup(TestCase):
    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_success(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_sales_ops_setting.get_delay_paid_collection_call_day.return_value = timedelta(days=2)
        mock_sales_ops_setting.get_loan_restriction_call_day.return_value = 7
        mock_sales_ops_setting.get_loan_disbursement_date_call_day.return_value = 14
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.get_account_status_code_history_list.return_value = []
        mock_julo_services.is_julo1_account.return_value = True
        mock_julo_services.filter_invalid_account_ids_application_restriction.return_value = []
        mock_julo_services.filter_invalid_account_limit_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_paid_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_loan_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_disbursement_date_restriction.return_value = []

        is_valid = sales_ops_services.is_account_valid(account)

        mock_julo_services.get_latest_account_limit.assert_called_once_with(account.id)
        mock_julo_services.get_account_status_code_history_list.assert_called_once_with(account.id)
        mock_sales_ops_setting.get_available_limit.assert_called_once()
        mock_julo_services.is_julo1_account.assert_called_once_with(account)
        mock_julo_services.filter_invalid_account_ids_collection_restriction.assert_called_once_with(
            [account.id], timedelta(days=5))
        mock_julo_services.filter_invalid_account_ids_paid_collection_restriction.assert_called_once_with(
            [account.id], timedelta(days=2)
        )
        mock_julo_services.filter_invalid_account_ids_loan_restriction.assert_called_once_with(
            [account.id], 7
        )
        mock_julo_services.filter_invalid_account_ids_disbursement_date_restriction.assert_called_once_with(
            [account.id], 14
        )

        self.assertTrue(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_success_max_420(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.get_account_status_code_history_list.return_value = [420]
        mock_julo_services.is_julo1_account.return_value = True
        mock_julo_services.filter_invalid_account_ids_application_restriction.return_value = []
        mock_julo_services.filter_invalid_account_limit_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_paid_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_loan_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_disbursement_date_restriction.return_value = []

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertTrue(is_valid)

    def test_failed_account_inactive(self):
        account = AccountFactory(status=StatusLookupFactory())

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_is_suspended_users(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500000)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.get_account_status_code_history_list.return_value = [420]
        mock_julo_services.is_julo1_account.return_value = True
        mock_julo_services.filter_invalid_account_ids_application_restriction.return_value = []
        mock_julo_services.filter_invalid_account_limit_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_paid_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_loan_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_disbursement_date_restriction.return_value = []
        mock_julo_services.filter_suspended_users.return_value = [account.id]

        is_valid = sales_ops_services.is_account_valid(account)
        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_account_lower_equal_threshold(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500000)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_account_status_code_history_list.return_value = [420]
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.is_julo1_account.return_value = True

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_account_status_history_not_420(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_account_status_code_history_list.return_value = [420, 430]
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.is_julo1_account.return_value = True

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_not_julo1(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_julo_services.is_julo1_account.return_value = False

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_has_collection_call(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.get_account_status_code_history_list.return_value = []
        mock_julo_services.is_julo1_account.return_value = True
        mock_julo_services.filter_invalid_account_ids_application_restriction.return_value = []
        mock_julo_services.filter_invalid_account_limit_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_collection_restriction.return_value = [1]

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)

    @patch('juloserver.sales_ops.services.sales_ops_services.SalesOpsSetting')
    @patch('juloserver.sales_ops.services.sales_ops_services.julo_services')
    def test_failed_has_paid_prev_collection_call(self, mock_julo_services, mock_sales_ops_setting):
        account = AccountFactory(status=StatusLookupFactory(status_code=420))
        account_limit = AccountLimitFactory(account=account, available_limit=500001)

        mock_sales_ops_setting.get_available_limit.return_value = 500000
        mock_julo_services.get_latest_account_limit.return_value = account_limit
        mock_julo_services.get_account_status_code_history_list.return_value = []
        mock_julo_services.is_julo1_account.return_value = True
        mock_julo_services.filter_invalid_account_ids_collection_restriction.return_value = []
        mock_julo_services.filter_invalid_account_ids_paid_collection_restriction.return_value = [1]

        is_valid = sales_ops_services.is_account_valid(account)

        self.assertFalse(is_valid)


class TestSalesopsRMScoring(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS,
            is_active=True,
            parameters={
                SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
                SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
            }
        )

    def test_handle_rm_scoring(self):
        db_r_percentages = SalesOpsSetting.get_r_percentages()
        db_m_percentages = SalesOpsSetting.get_m_percentages()
        set_rm_scoring(db_m_percentages, ScoreCriteria.MONETARY)
        set_rm_scoring(db_r_percentages, ScoreCriteria.RECENCY)
        rm_scores = SalesOpsRMScoring.objects.order_by('criteria', '-score').all()
        rm_scoring_tuples = [
            (rm_score.score, rm_score.criteria, rm_score.top_percentile, rm_score.bottom_percentile)
            for rm_score in rm_scores
        ]
        expect_result_rm_scoring = [
            (5, ScoreCriteria.MONETARY, 100, 80),
            (4, ScoreCriteria.MONETARY, 80, 60),
            (3, ScoreCriteria.MONETARY, 60, 40),
            (2, ScoreCriteria.MONETARY, 40, 20),
            (1, ScoreCriteria.MONETARY, 20, 0),
            (5, ScoreCriteria.RECENCY, 100, 80),
            (4, ScoreCriteria.RECENCY, 80, 60),
            (3, ScoreCriteria.RECENCY, 60, 40),
            (2, ScoreCriteria.RECENCY, 40, 20),
            (1, ScoreCriteria.RECENCY, 20, 0)
        ]
        self.assertEqual(rm_scoring_tuples, expect_result_rm_scoring)


class TestSalesOpsLineUp(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS,
            is_active=True,
            parameters={
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 1,
                SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 2,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 3,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 4,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 5,
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
                SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
                SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
                "buckets": [
                    {
                        "code": "sales_ops_a",
                        "name": "SALES OPS A",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [2, 3],
                        "description": "Sales Ops A: R-score 2 and 3",
                        "is_active": True,
                    },
                    {
                        "code": "sales_ops_b",
                        "name": "SALES OPS B",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [1, 4, 5],
                        "description": "Sales Ops B: R-score 1,4, and 5",
                        "is_active": True,
                    }
                ],
            },
        )
        save_setting(self.feature_setting.parameters)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.julo1_account_lookup = AccountLookupFactory(name='JULO1')
        self.account = AccountFactory(
            customer=self.customer, account_lookup=self.julo1_account_lookup
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            paid_date=date.today() + timedelta(days=10),
            is_restructured=False
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000
        )
        self.sales_ops_line_up = SalesOpsLineupFactory(
            account=self.account,
            latest_account_property_id=self.account_property.id,
            latest_application_id=self.application.id,
            latest_account_limit_id=self.account_limit.id,
            latest_disbursed_loan_id=self.loan.id,
            latest_account_payment_id=self.account_payment.id,
        )
        self.account_payment.status_id = 330
        self.account_payment.save()
        self.sales_ops_line_up.save()
        self.sales_ops_m_score = SalesOpsMScoreFactory(
            account_id=self.account.id,
            latest_account_limit_id=1,
            available_limit=1000000,
            ranking=1,
        )

        self.sales_ops_r_score = SalesOpsRScoreFactory(
            account_id=self.account.id,
            latest_active_dates=timezone.localtime(timezone.now()).date(),
            ranking=1,
        )

    @patch('juloserver.sales_ops.services.sales_ops_services.bulk_calculate_recency_score')
    @patch('juloserver.sales_ops.services.sales_ops_services.bulk_calculate_monetary_score')
    def test_create_account_segment_history(self, mock_bulk_calculate_recency_score,
                                            mock_bulk_calculate_monetary_score):
        mock_bulk_calculate_recency_score.return_value = {
            self.account.id: (
                SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY),
                {
                    "score": 1,
                    "account_id": self.account.id,
                    "latest_active_dates": "2020-12-16"
                }
            )
        }
        mock_bulk_calculate_monetary_score.return_value = {
            self.account.id: (
                SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY),
                {
                    "score": 1,
                    "account_id": self.account.id,
                    "available_limit": 7000000,
                    "account_limit_id": 514
                }
            )
        }
        bulk_create_account_segment_history([self.sales_ops_line_up])
        self.assertIsNotNone(SalesOpsAccountSegmentHistory.objects.filter(account_id=self.account.id))

    def test_bulk_update_lineups(self):
        accounts = AccountFactory.create_batch(3)
        lineups = []
        for account in accounts:
            lineups.append(SalesOpsLineupFactory(is_active=True, account=account))

        normal_account = accounts[0]
        m_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=2)
        r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=2)
        account_score_mappings = {
            normal_account.id: (m_score.score, r_score.score)
        }
        graduation_account = accounts[1]
        SalesOpsGraduationFactory(
            account_id=graduation_account.id,
            last_graduation_date='2023-10-02',
            limit_amount_increased=2000000,
            ranking=1
        )
        sales_ops_services.bulk_update_lineups(lineups, account_score_mappings)
        normal_lineup = SalesOpsLineup.objects.get(account_id=normal_account.id)
        self.assertEqual(normal_lineup.bucket_code, 'sales_ops_a')
        self.assertEqual(normal_lineup.prioritization, 4)

        graduation_lineup = SalesOpsLineup.objects.get(account_id=graduation_account.id)
        self.assertEqual(graduation_lineup.bucket_code, 'graduation')
        self.assertEqual(graduation_lineup.prioritization, 1)

        unexpected_lineups = SalesOpsLineup.objects.exclude(
            Q(account_id=normal_account.id) | Q(account_id=graduation_account.id)
        )
        for unexpected_lineup in unexpected_lineups:
            self.assertIsNone(unexpected_lineup.bucket_code)
            self.assertEqual(unexpected_lineup.prioritization, 0)

    def test_update_latest_lineup_info(self):
        self.account_limit.available_limit = 2000000
        self.account_limit.save()
        update_latest_lineup_info(self.sales_ops_line_up.id)
        self.sales_ops_line_up.refresh_from_db()
        account_limit = AccountLimit.objects.get(pk=self.sales_ops_line_up.latest_account_limit_id)
        available_limit = account_limit.available_limit
        self.assertEqual(available_limit, 2000000)

    def test_save_setting(self):
        self.feature_setting.parameters = {
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 1,
            SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 2,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 3,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 4,
            SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 5,
            SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
            SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,30,10,20',
            SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,30,10,20',
        }
        save_setting(self.feature_setting.parameters)
        rm_scoring = SalesOpsRMScoring.objects.filter(
            criteria=ScoreCriteria.MONETARY, is_active=True, score__in=[3, 2]).all()
        rm_score_dict = {
            item.score: item.top_percentile - item.bottom_percentile for item in rm_scoring
        }
        self.assertEqual(rm_score_dict[3], 30)
        self.assertEqual(rm_score_dict[2], 10)


class TestPrivateCalculateMonetaryScore(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.accounts = AccountFactory.create_batch(4)
        self.rm_scores = SalesOpsRMScoringFactory.create_batch(
            5,
            is_active=True,
            criteria=ScoreCriteria.MONETARY,
            score=Iterator([5, 4, 3, 2, 1]),
            top_percentile=Iterator([100, 80, 60, 40, 20]),
            bottom_percentile=Iterator([80, 60, 40, 20, 0]),
        )
        self.sales_ops_lineup = SalesOpsLineupFactory(account=self.account)

    def test_score_criteria(self):
        self.accounts.insert(0, self.account)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            5,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99, 98, 97, 96]),
            ranking=Iterator([1, 2, 3, 4, 5]),
        )

        ret_val = bulk_calculate_monetary_score([self.account.id])
        m_score, m_score_criteria = ret_val[self.account.id]

        self.assertEqual(m_score.score, 5)
        self.assertEqual({
            'account_limit_id': None,
            'available_limit': 100,
            'account_id': self.account.id,
            'score': 5,
        }, m_score_criteria)

    def test_with_6_data(self):
        self.accounts = AccountFactory.create_batch(6)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            6,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99, 98, 97, 96, 95]),
            ranking=Iterator([1, 2, 3, 4, 5, 6]),
        )

        expected_score_map = [
            5, 5, 4, 3, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)

    def test_with_5_data(self):
        self.accounts = AccountFactory.create_batch(5)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            5,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99, 98, 97, 96]),
            ranking=Iterator([1, 2, 3, 4, 5]),
        )

        expected_score_map = [
            5, 4, 3, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)

    def test_with_4_data(self):
        self.accounts = AccountFactory.create_batch(4)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            4,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99, 98, 97]),
            ranking=Iterator([1, 2, 3, 4]),
        )

        expected_score_map = [
            5, 4, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)

    def test_with_3_data(self):
        self.accounts = AccountFactory.create_batch(3)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            3,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99, 98]),
            ranking=Iterator([1, 2, 3]),
        )

        expected_score_map = [
            5, 3, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)

    def test_with_2_data(self):
        self.accounts = AccountFactory.create_batch(2)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            2,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100, 99]),
            ranking=Iterator([1, 2]),
        )

        expected_score_map = [
            5, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)

    def test_with_1_data(self):
        self.accounts = AccountFactory.create_batch(1)
        self.m_scores = SalesOpsMScoreFactory.create_batch(
            1,
            account_id=Iterator([account.id for account in self.accounts]),
            available_limit=Iterator([100]),
            ranking=Iterator([1]),
        )

        expected_score_map = [
            5,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_monetary_score([account.id])
            m_score, m_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], m_score.score)


class TestPrivateCalculateRecencyScore(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.accounts = AccountFactory.create_batch(4)
        self.rm_scores = SalesOpsRMScoringFactory.create_batch(
            5,
            criteria=ScoreCriteria.RECENCY,
            is_active=True,
            score=Iterator([5, 4, 3, 2, 1]),
            top_percentile=Iterator([100, 80, 60, 40, 20]),
            bottom_percentile=Iterator([80, 60, 40, 20, 0]),
        )

    def test_score_criteria(self):
        self.accounts.insert(0, self.account)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            5,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29', '2021-10-28', '2021-10-27', '2021-10-26']
            ),
            ranking=Iterator([1, 2, 3, 4, 5]),
        )

        ret_val = bulk_calculate_recency_score([self.account.id])
        r_score, r_score_criteria = ret_val[self.account.id]

        self.assertEqual(r_score.score, 5)
        self.assertEqual({
            'latest_active_dates': '2021-10-30',
            'account_id': self.account.id,
            'score': 5,
        }, r_score_criteria)

    def test_with_6_data(self):
        self.accounts = AccountFactory.create_batch(6)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            6,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29', '2021-10-28', '2021-10-27', '2021-10-26', '2021-10-25']
            ),
            ranking=Iterator([1, 2, 3, 4, 5, 6]),
        )

        expected_score_map = [
            5, 5, 4, 3, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)

    def test_with_5_data(self):
        self.accounts = AccountFactory.create_batch(5)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            5,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29', '2021-10-28', '2021-10-27', '2021-10-26']
            ),
            ranking=Iterator([1, 2, 3, 4, 5]),
        )

        expected_score_map = [
            5, 4, 3, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)

    def test_with_4_data(self):
        self.accounts = AccountFactory.create_batch(4)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            4,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29', '2021-10-28', '2021-10-27']
            ),
            ranking=Iterator([1, 2, 3, 4]),
        )

        expected_score_map = [
            5, 4, 2, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)

    def test_with_3_data(self):
        self.accounts = AccountFactory.create_batch(3)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            3,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29', '2021-10-28']
            ),
            ranking=Iterator([1, 2, 3]),
        )

        expected_score_map = [
            5, 3, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)

    def test_with_2_data(self):
        self.accounts = AccountFactory.create_batch(2)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            2,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30', '2021-10-29']
            ),
            ranking=Iterator([1, 2]),
        )

        expected_score_map = [
            5, 1,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)

    def test_with_1_data(self):
        self.accounts = AccountFactory.create_batch(1)
        self.r_scores = SalesOpsRScoreFactory.create_batch(
            1,
            account_id=Iterator([account.id for account in self.accounts]),
            latest_active_dates=Iterator(
                ['2021-10-30']
            ),
            ranking=Iterator([1]),
        )

        expected_score_map = [
            5,
        ]
        for idx, account in enumerate(self.accounts):
            ret_val = bulk_calculate_recency_score([account.id])
            r_score, r_score_criteria = ret_val[account.id]
            self.assertEqual(expected_score_map[idx], r_score.score)


class TestGetLatestScore(TestCase):
    def test_success(self):
        account = AccountFactory()
        r_score = SalesOpsRMScoringFactory(score=5, criteria=ScoreCriteria.RECENCY)
        m_score = SalesOpsRMScoringFactory(score=4, criteria=ScoreCriteria.MONETARY)
        SalesOpsAccountSegmentHistoryFactory.create_batch(5, account_id=account.id)
        latest_account_segment = SalesOpsAccountSegmentHistoryFactory(
            account_id=account.id,
            r_score_id=r_score.id,
            m_score_id=m_score.id
        )
        SalesOpsAccountSegmentHistoryFactory.create_batch(5)  # random account

        value = sales_ops_services.get_latest_score(account.id)

        self.assertIsInstance(value, RMScoreInfo)
        self.assertEqual(5, value.r_score)
        self.assertEqual(4, value.m_score)
        self.assertEqual(latest_account_segment, value.account_rm_segment)
        self.assertEqual(r_score, value.r_score_model)
        self.assertEqual(m_score, value.m_score_model)

    def test_missing(self):
        account = AccountFactory()

        with self.assertRaises(MissingAccountSegmentHistory):
            sales_ops_services.get_latest_score(account.id)


class TestGetLatestScore(TestCase):
    def test_success(self):
        account = AccountFactory()
        r_score = SalesOpsRMScoringFactory(score=5, criteria=ScoreCriteria.RECENCY)
        m_score = SalesOpsRMScoringFactory(score=4, criteria=ScoreCriteria.MONETARY)
        SalesOpsAccountSegmentHistoryFactory.create_batch(5, account_id=account.id)
        latest_account_segment = SalesOpsAccountSegmentHistoryFactory(
            account_id=account.id,
            r_score_id=r_score.id,
            m_score_id=m_score.id
        )
        SalesOpsAccountSegmentHistoryFactory.create_batch(5)  # random account

        value = sales_ops_services.get_latest_score(account.id)

        self.assertIsInstance(value, RMScoreInfo)
        self.assertEqual(5, value.r_score)
        self.assertEqual(4, value.m_score)
        self.assertEqual(latest_account_segment, value.account_rm_segment)
        self.assertEqual(r_score, value.r_score_model)
        self.assertEqual(m_score, value.m_score_model)

    def test_missing(self):
        account = AccountFactory()

        with self.assertRaises(MissingAccountSegmentHistory):
            sales_ops_services.get_latest_score(account.id)


class TestAgentAssignmentCsvImporter(TestCase):
    def test_validate_success(self):
        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_success_1.csv'
        )

        importer = AgentAssignmentCsvImporter(filepath)
        ret_val = importer.validate()
        self.assertTrue(ret_val)

    def test_validate_fail(self):
        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_fail_1.csv'
        )
        importer = AgentAssignmentCsvImporter(filepath)
        with self.assertRaises(ValidationError):
            importer.validate()

    def test_save(self):
        AccountFactory.create_batch(2, id=Iterator([11, 22]))
        AgentFactory.create_batch(2, id=Iterator([1, 2]))

        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_success_1.csv'
        )
        importer = AgentAssignmentCsvImporter(filepath)

        importer.save()
        self.assertEquals(1, SalesOpsAgentAssignment.objects.count())

        lineup = SalesOpsLineup.objects.get(account_id=22, is_active=False)
        latest_agent_assignment = SalesOpsAgentAssignment.objects.get(
            pk=lineup.latest_agent_assignment_id
        )
        self.assertIsNotNone(lineup.latest_agent_assignment_id)
        self.assertEqual(2, latest_agent_assignment.agent_id)
        self.assertFalse(latest_agent_assignment.is_active)
        self.assertTrue(latest_agent_assignment.is_rpc)

    def test_save_updated_lineup(self):
        accounts = AccountFactory.create_batch(2, id=Iterator([11, 22]))
        AgentFactory.create_batch(2, id=Iterator([1, 2]))
        lineup = SalesOpsLineupFactory(
            account=accounts[1], is_active=True, latest_agent_assignment_id=None
        )

        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_success_1.csv'
        )
        importer = AgentAssignmentCsvImporter(filepath)

        importer.save()
        self.assertEquals(1, SalesOpsAgentAssignment.objects.count())

        lineup = SalesOpsLineup.objects.get(account_id=22, is_active=True)
        latest_agent_assignment = SalesOpsAgentAssignment.objects.get(
            pk=lineup.latest_agent_assignment_id
        )
        agent_id = latest_agent_assignment.agent_id
        self.assertEqual(2, agent_id)

    def test_save_no_update_lineup(self):
        accounts = AccountFactory.create_batch(2, id=Iterator([11, 22]))
        agents = AgentFactory.create_batch(2)
        lineup = SalesOpsLineupFactory(
            account=accounts[1], is_active=True, latest_agent_assignment_id=None
        )
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup=lineup, completed_date='2021-05-12', agent_id=agents[0].id
        )
        lineup.update_safely(latest_agent_assignment_id=agent_assignment.id)

        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_success_1.csv'
        )
        importer = AgentAssignmentCsvImporter(filepath)

        importer.save()
        self.assertEquals(2, SalesOpsAgentAssignment.objects.count())

        lineup = SalesOpsLineup.objects.get(account_id=22, is_active=True)
        self.assertEqual(agent_assignment.id, lineup.latest_agent_assignment_id)

    def test_multiple_run(self):
        AccountFactory.create_batch(2, id=Iterator([11, 22]))
        AgentFactory.create_batch(2, id=Iterator([1, 2]))

        filepath = os.path.join(
            os.path.dirname(__file__),
            '../stubs/agent_assignment_importer_success_1.csv'
        )
        importer = AgentAssignmentCsvImporter(filepath)
        importer.save()

        importer2 = AgentAssignmentCsvImporter(filepath)
        importer2.save()
        self.assertEquals(1, SalesOpsAgentAssignment.objects.count())


class TestCanSubmitLineupSkiptraceHistory(TestCase):
    def setUp(self):
        self.lineup = SalesOpsLineupFactory(is_active=True)

    def test_no_assignment(self):
        ret_val = sales_ops_services.can_submit_lineup_skiptrace_history(self.lineup)
        self.assertTrue(ret_val)

    def test_non_rpc_assignment(self):
        latest_agent_assignment = SalesOpsAgentAssignmentFactory(
            completed_date=timezone.now(), is_rpc=False
        )
        self.lineup.update_safely(latest_agent_assignment_id=latest_agent_assignment.id)
        ret_val = sales_ops_services.can_submit_lineup_skiptrace_history(self.lineup)

        self.assertTrue(ret_val)

    def test_active_assignment(self):
        latest_agent_assignment = SalesOpsAgentAssignmentFactory(
            is_active=True,
            is_rpc=None,
        )
        self.lineup.update_safely(latest_agent_assignment_id=latest_agent_assignment.id)
        ret_val = sales_ops_services.can_submit_lineup_skiptrace_history(self.lineup)

        self.assertFalse(ret_val)

    @patch.object(SalesOpsSetting, 'get_autodialer_delay_setting')
    @patch.object(timezone, 'now')
    def test_rpc_assignment_success(self, mock_now, mock_get_autodialer_delay_setting):
        now = datetime.datetime(2022, 1, 1, 10, 0, 0)
        mock_now.return_value = now
        mock_get_autodialer_delay_setting.return_value = AutodialerDelaySetting(rpc_delay_hour=1)

        completed_date = now - timedelta(hours=1)
        latest_agent_assignment = SalesOpsAgentAssignmentFactory(
            is_active=False,
            completed_date=completed_date,
            is_rpc=True,
        )
        self.lineup.update_safely(latest_agent_assignment_id=latest_agent_assignment.id)
        ret_val = sales_ops_services.can_submit_lineup_skiptrace_history(self.lineup)

        self.assertTrue(ret_val)

    @patch.object(SalesOpsSetting, 'get_autodialer_delay_setting')
    @patch.object(timezone, 'now')
    def test_rpc_assignment_fails(self, mock_now, mock_get_autodialer_delay_setting):
        now = datetime.datetime(2022, 1, 1, 10, 0, 0)
        mock_now.return_value = now
        mock_get_autodialer_delay_setting.return_value = AutodialerDelaySetting(rpc_delay_hour=2)

        completed_date = now - timedelta(hours=1)
        latest_agent_assignment = SalesOpsAgentAssignmentFactory(
            is_active=False,
            completed_date=completed_date,
            is_rpc=True,
        )
        self.lineup.update_safely(latest_agent_assignment_id=latest_agent_assignment.id)
        ret_val = sales_ops_services.can_submit_lineup_skiptrace_history(self.lineup)

        self.assertFalse(ret_val)


class TestGetBucketCode(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS,
            parameters={
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_DAYS: 30,
                SalesOpsSettingConst.LINEUP_MAX_USED_LIMIT_PERCENTAGE: 0.9,
                "buckets": [
                    {
                        "code": "sales_ops_a",
                        "name": "SALES OPS A",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [2, 3],
                        "description": "Sales Ops A: R-score 2 and 3",
                        "is_active": True,
                    },
                    {
                        "code": "sales_ops_b",
                        "name": "SALES OPS B",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [1, 4, 5],
                        "description": "Sales Ops B: R-score 1,4, and 5",
                        "is_active": True,
                    }
                ]
            })

    def test_get_bucket_code(self):
        bucket_code = get_bucket_code(self.feature_setting, 1)
        self.assertEqual('sales_ops_b', bucket_code)


class TestConstructDataAfterRpcCall(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.julo1_account_lookup = AccountLookupFactory(name='JULO1')
        self.account = AccountFactory(
            customer=self.customer, account_lookup=self.julo1_account_lookup
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.agent = AgentFactory()
        self.lineup = SalesOpsLineupFactory(latest_application_id=self.application.id)
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2023, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            agent_id=self.agent.id, lineup=self.lineup, completed_date=mock_now
        )
        self.agent_assignment.update_safely(cdate=mock_now)
        self.r_score = SalesOpsRMScoringFactory(score=5, criteria=ScoreCriteria.RECENCY)
        self.m_score = SalesOpsRMScoringFactory(score=4, criteria=ScoreCriteria.MONETARY)
        SalesOpsAccountSegmentHistoryFactory(
            account_id=self.account.id, r_score_id=self.r_score.id, m_score_id=self.m_score.id
        )
        self.criterion_r_score = PromoCodeCriteriaFactory(
            name='Sike, it is Damian Wayne',
            type=PromoCodeCriteriaConst.R_SCORE,
            value={
                'r_scores': [1]
            }
        )
        self.criterion_minimum_loan_transaction = PromoCodeCriteriaFactory(
            name='Minimum transaction',
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={"minimum_loan_amount": 500000}
        )
        self.promo_code = PromoCodeFactory(
            criteria=[self.criterion_r_score.id, self.criterion_minimum_loan_transaction.id],
            promo_code='BATMAN01',
            is_active=True,
        )
        PromoCodeAgentMappingFactory(promo_code=self.promo_code, agent_id=self.agent.id)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    def test_construct_data_after_rpc_called(self, mock_send_to_moengage):
        #  invalid r_score
        is_valid = sales_ops_services.validate_promo_code_by_r_score(
            self.promo_code, self.r_score.score
        )
        self.assertFalse(is_valid)

        #  valid r_score
        self.criterion_r_score.update_safely(value={'r_scores': [5]})
        is_valid = sales_ops_services.validate_promo_code_by_r_score(
            self.promo_code, self.r_score.score
        )
        self.assertTrue(is_valid)
        minimum_transaction = get_minimum_transaction_promo_code(self.promo_code)
        self.assertEqual(minimum_transaction, 500000)

        send_event_moengage_for_rpc_sales_ops(self.agent_assignment.id)
        event_time = timezone.localtime(self.agent_assignment.cdate)
        customer_id = self.customer.id
        completed_date_plus6 = self.agent_assignment.completed_date + timedelta(days=6)
        completed_date_plus6 = datetime.datetime.strftime(
            timezone.localtime(completed_date_plus6), "%Y-%m-%d %H:%M:%S"
        )
        data_to_send = [
            {
                'type': 'event',
                'customer_id': customer_id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.IS_SALES_OPS_RPC,
                        'attributes': {
                            'r_score': 5,
                            'promo_code_salesops': 'BATMAN01',
                            'completed_date_plus6': completed_date_plus6,
                            'minimum_transaction': 500000,
                        },
                        'platform': 'ANDROID',
                        'current_time': event_time.timestamp(),
                        'user_timezone_offset': event_time.utcoffset().seconds,
                    }
                ]
            }
        ]

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.IS_SALES_OPS_RPC,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    def test_construct_data_after_rpc_called_case_all_criteria(self, mock_send_to_moengage):
        self.promo_code.criteria = [self.criterion_minimum_loan_transaction.id]
        self.promo_code.save()
        is_valid = sales_ops_services.validate_promo_code_by_r_score(
            self.promo_code, self.r_score.score
        )
        self.assertTrue(is_valid)

        minimum_transaction = get_minimum_transaction_promo_code(self.promo_code)
        self.assertEqual(minimum_transaction, 500000)

        send_event_moengage_for_rpc_sales_ops(self.agent_assignment.id)
        event_time = timezone.localtime(self.agent_assignment.cdate)
        customer_id = self.customer.id
        completed_date_plus6 = self.agent_assignment.completed_date + timedelta(days=6)
        completed_date_plus6 = datetime.datetime.strftime(
            timezone.localtime(completed_date_plus6), "%Y-%m-%d %H:%M:%S"
        )
        data_to_send = [
            {
                'type': 'event',
                'customer_id': customer_id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.IS_SALES_OPS_RPC,
                        'attributes': {
                            'r_score': 5,
                            'promo_code_salesops': 'BATMAN01',
                            'completed_date_plus6': completed_date_plus6,
                            'minimum_transaction': 500000,
                        },
                        'platform': 'ANDROID',
                        'current_time': event_time.timestamp(),
                        'user_timezone_offset': event_time.utcoffset().seconds,
                    }
                ]
            }
        ]

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.IS_SALES_OPS_RPC,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)


class TestConstructDataAfterUploadingRPCCall(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.julo1_account_lookup = AccountLookupFactory(name='JULO1')
        self.account = AccountFactory(
            customer=self.customer, account_lookup=self.julo1_account_lookup
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.agent = AgentFactory()
        self.lineup = SalesOpsLineupFactory(latest_application=self.application)
        self.autodialer_session = SalesOpsAutodialerSessionFactory(lineup=self.lineup)
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2023, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        self.agent_assignment = SalesOpsAgentAssignmentFactory(
            agent=self.agent, lineup=self.lineup, completed_date=mock_now
        )
        self.agent_assignment.update_safely(cdate=mock_now)
        self.criterion_minimum_loan_transaction = PromoCodeCriteriaFactory(
            name='Minimum transaction',
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={"minimum_loan_amount": 500000}
        )
        self.promo_code = PromoCodeFactory(
            criteria=[],
            promo_code='BATMAN01',
            is_active=True,
        )
        PromoCodeAgentMappingFactory(promo_code=self.promo_code, agent_id=self.agent.id)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    def test_construct_data_after_uploading_rpc_called(self, mock_send_to_moengage):
        self.promo_code.criteria = [self.criterion_minimum_loan_transaction.id]
        self.promo_code.save()

        send_event_moengage_for_rpc_sales_ops_pds(
            agent_assignment_id=self.agent_assignment.id,
            promo_code_id=self.promo_code.id
        )
        event_time = timezone.localtime(self.agent_assignment.cdate)
        customer_id = self.customer.id
        completed_date = datetime.datetime.strftime(
            timezone.localtime(self.agent_assignment.completed_date), "%Y-%m-%d %H:%M:%S"
        )
        data_to_send = [
            {
                'type': 'event',
                'customer_id': customer_id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.IS_SALES_OPS_RPC_PDS,
                        'attributes': {
                            'promo_code': 'BATMAN01',
                            'completed_date': completed_date,
                            'minimum_transaction': 500000,
                        },
                        'platform': 'ANDROID',
                        'current_time': event_time.timestamp(),
                        'user_timezone_offset': event_time.utcoffset().seconds,
                    }
                ]
            }
        ]

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.IS_SALES_OPS_RPC_PDS,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    def test_construct_data_after_uploading_rpc_called_no_criteria(self, mock_send_to_moengage):
        send_event_moengage_for_rpc_sales_ops_pds(
            agent_assignment_id=self.agent_assignment.id,
            promo_code_id=self.promo_code.id
        )
        event_time = timezone.localtime(self.agent_assignment.cdate)
        customer_id = self.customer.id
        completed_date = datetime.datetime.strftime(
            timezone.localtime(self.agent_assignment.completed_date), "%Y-%m-%d %H:%M:%S"
        )
        data_to_send = [
            {
                'type': 'event',
                'customer_id': customer_id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.IS_SALES_OPS_RPC_PDS,
                        'attributes': {
                            'promo_code': 'BATMAN01',
                            'completed_date': completed_date,
                            'minimum_transaction': 0,
                        },
                        'platform': 'ANDROID',
                        'current_time': event_time.timestamp(),
                        'user_timezone_offset': event_time.utcoffset().seconds,
                    }
                ]
            }
        ]

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.IS_SALES_OPS_RPC_PDS,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)


class TestSalesOpsLineUpBucketLogic(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SALES_OPS,
            is_active=True,
            parameters={
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR: 1,
                SalesOpsSettingConst.AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR: 2,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR: 3,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR: 4,
                SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT: 5,
                SalesOpsSettingConst.LINEUP_MIN_AVAILABLE_LIMIT: 500000,
                SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20',
                SalesOpsSettingConst.RECENCY_PERCENTAGES: '20,20,20,20,20',
                "buckets": [
                    {
                        "code": "sales_ops_a",
                        "name": "SALES OPS A",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [2, 3],
                        "description": "Sales Ops A: R-score 2 and 3",
                        "is_active": True,
                    },
                    {
                        "code": "sales_ops_b",
                        "name": "SALES OPS B",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [1, 4],
                        "description": "Sales Ops B: R-score 1, and 4",
                        "is_active": True,
                    },
                    {
                        "code": "sales_ops_c",
                        "name": "SALES OPS C",
                        "criteria": ScoreCriteria.RECENCY,
                        "scores": [5],
                        "description": "Sales Ops C: R-score 5",
                        "is_active": True,
                    }
                ],
            },
        )
        save_setting(self.feature_setting.parameters)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.julo1_account_lookup = AccountLookupFactory(name='JULO1')
        self.account = AccountFactory(
            customer=self.customer, account_lookup=self.julo1_account_lookup
        )
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            paid_date=date.today() + timedelta(days=10),
            is_restructured=False
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000
        )
        self.sales_ops_line_up = SalesOpsLineupFactory(
            account=self.account,
            latest_account_property_id=self.account_property.id,
            latest_application_id=self.application.id,
            latest_account_limit_id=self.account_limit.id,
            latest_disbursed_loan_id=self.loan.id,
            latest_account_payment_id=self.account_payment.id,
        )
        self.account_payment.status_id = 330
        self.account_payment.save()
        self.sales_ops_line_up.save()
        self.sales_ops_m_score = SalesOpsMScoreFactory(
            account_id=self.account.id,
            latest_account_limit_id=1,
            available_limit=1000000,
            ranking=1,
        )

        self.sales_ops_r_score = SalesOpsRScoreFactory(
            account_id=self.account.id,
            latest_active_dates=timezone.localtime(timezone.now()).date(),
            ranking=1,
        )
        self.vendor_1 = SalesOpsVendorFactory(name='Vendor 1')
        self.vendor_2 = SalesOpsVendorFactory(name='Vendor 2')
        self.bucket = SaleOpsBucketFactory(code='sales_ops_a')
        self.mapping_vendor1 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_1,
            bucket=self.bucket,
            ratio=30
        )
        self.mapping_vendor2 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_2,
            bucket=self.bucket,
            ratio=25
        )

        self.vendor_3 = SalesOpsVendorFactory(name='Vendor 3')
        self.vendor_4 = SalesOpsVendorFactory(name='Vendor 4')
        self.bucket_b = SaleOpsBucketFactory(code='sales_ops_b', scores={'r_scores': [3]})
        self.mapping_vendor3 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_3,
            bucket=self.bucket_b,
            ratio=33
        )
        self.mapping_vendor4 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_4,
            bucket=self.bucket_b,
            ratio=77
        )

        self.vendor_5 = SalesOpsVendorFactory(name='Vendor 5')
        self.vendor_6 = SalesOpsVendorFactory(name='Vendor 6')
        self.vendor_7 = SalesOpsVendorFactory(name='Vendor 7')
        self.bucket_graduation = SaleOpsBucketFactory(code='graduation')
        self.mapping_vendor5 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_5,
            bucket=self.bucket_graduation,
            ratio=50
        )
        self.mapping_vendor6 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_6,
            bucket=self.bucket_graduation,
            ratio=50
        )
        self.mapping_vendor7 = SalesOpsVendorBucketMappingFactory(
            vendor=self.vendor_7,
            bucket=self.bucket_graduation,
            ratio=100,
            is_active=False
        )
        self.bucket_c = SaleOpsBucketFactory(code='sales_ops_c')

    def calculate_total_vendor(self, ratio, total_ratio, total_lineups):
        percent_of_lineups = round((ratio / total_ratio), 2)
        return round(percent_of_lineups * total_lineups)

    def test_bulk_update_bucket_lineups_logic(self):
        accounts = AccountFactory.create_batch(11)
        lineups = []

        for account in accounts:
            lineups.append(SalesOpsLineupFactory(is_active=True, account=account))
            if account.id % 2:
                SalesOpsGraduationFactory(account_id=account.id)

        m_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=2)
        r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=2)

        account_score_mappings = {}
        list_account_ids = [account.pk for account in accounts]
        for account_id in list_account_ids:
            account_score_mappings[account_id] = (m_score.score, r_score.score)

        account_2 = AccountFactory.create_batch(11)
        m_score_b = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=1)
        r_score_b = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=1)
        list_account_ids_2 = [account.pk for account in account_2]

        for account_id in list_account_ids_2:
            account_score_mappings[account_id] = (m_score_b.score, r_score_b.score)
        for account in account_2:
            lineups.append(SalesOpsLineupFactory(is_active=True, account=account))
            if not account.id % 2:
                SalesOpsGraduationFactory(account_id=account.id)

        lineup_ids = [lineup.pk for lineup in lineups]
        sales_ops_services.bulk_update_lineups(lineups, account_score_mappings)
        sales_ops_services.bulk_update_bucket_lineups_logic(lineup_ids)
        total_lineups = len(list(filter(lambda acc: not acc.id % 2, accounts)))
        total_ratio = self.mapping_vendor1.ratio + self.mapping_vendor2.ratio

        total_vendor_lineup_1 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_1.name, bucket_code=self.bucket.code).count()
        expected_total = self.calculate_total_vendor(
            self.mapping_vendor1.ratio, total_ratio, total_lineups)

        assert total_vendor_lineup_1 == expected_total

        total_vendor_lineup_2 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_2.name, bucket_code=self.bucket.code).count()

        assert total_vendor_lineup_2 == total_lineups - total_vendor_lineup_1

        # test bucket b
        total_lineups_b = len(list(filter(lambda acc: acc.id % 2, account_2)))
        total_ratio = self.mapping_vendor3.ratio + self.mapping_vendor4.ratio

        total_vendor_lineup_3 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_3.name, bucket_code=self.bucket_b.code).count()
        expected_total = self.calculate_total_vendor(
            self.mapping_vendor3.ratio, total_ratio, total_lineups_b)

        assert total_vendor_lineup_3 == expected_total

        total_vendor_lineup_4 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_4.name, bucket_code=self.bucket_b.code).count()

        assert total_vendor_lineup_4 == total_lineups_b - total_vendor_lineup_3

        # test bucket graduation
        total_lineups_graduation = (len(accounts) - total_lineups) + (len(account_2) - total_lineups_b)
        total_ratio_gradution = self.mapping_vendor5.ratio + self.mapping_vendor6.ratio

        total_vendor_lineup_5 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_5.name, bucket_code=self.bucket_graduation.code).count()
        expected_total = self.calculate_total_vendor(
            self.mapping_vendor5.ratio, total_ratio_gradution, total_lineups_graduation)

        assert total_vendor_lineup_5 == expected_total

        total_vendor_lineup_6 = SalesOpsLineup.objects.filter(
            vendor_name=self.vendor_6.name, bucket_code=self.bucket_graduation.code).count()

        assert total_vendor_lineup_6 == total_lineups_graduation - total_vendor_lineup_5

    def test_bulk_update_bucket_lineups_logic_with_small_lineup(self):
        total = 1
        accounts = AccountFactory.create_batch(total)
        lineups = []

        for account in accounts:
            lineups.append(SalesOpsLineupFactory(is_active=True, account=account))

        m_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=2)
        r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=2)

        account_score_mappings = {}
        list_account_ids = [account.pk for account in accounts]
        for account_id in list_account_ids:
            account_score_mappings[account_id] = (m_score.score, r_score.score)

        lineup_ids = [lineup.pk for lineup in lineups]
        sales_ops_services.bulk_update_lineups(lineups, account_score_mappings)
        sales_ops_services.bulk_update_bucket_lineups_logic(lineup_ids)

        total_vendor_lineups = SalesOpsLineup.objects.filter(bucket_code=self.bucket.code).count()
        assert total == total_vendor_lineups

    def test_bulk_update_bucket_lineups_logic_no_bucket_vendor_mapping(self):
        total = 10
        accounts = AccountFactory.create_batch(total)
        lineups = []

        for account in accounts:
            lineups.append(SalesOpsLineupFactory(is_active=True, account=account))

        m_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.MONETARY, score=5)
        r_score = SalesOpsRMScoringFactory(criteria=ScoreCriteria.RECENCY, score=5)

        account_score_mappings = {}
        list_account_ids = [account.pk for account in accounts]
        for account_id in list_account_ids:
            account_score_mappings[account_id] = (m_score.score, r_score.score)

        lineup_ids = [lineup.pk for lineup in lineups]
        sales_ops_services.bulk_update_lineups(lineups, account_score_mappings)
        sales_ops_services.bulk_update_bucket_lineups_logic(lineup_ids)

        default_vendor_name = SalesOpsVendorName.IN_HOUSE
        total_vendor_lineups = SalesOpsLineup.objects.filter(
            bucket_code=self.bucket_c.code, vendor_name=default_vendor_name).count()
        assert total == total_vendor_lineups
